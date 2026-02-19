import { pool } from '../db/pool';
import { logAuditEvent } from './auditService';
import { evaluateRules } from '../rules/engine';
import * as budgetService from './budgetService';
import { AppError } from '../middleware/errorHandler';

interface InvoiceLineInput {
  poLineId?: string;
  itemId?: string;
  description?: string;
  quantityInvoiced?: number;
  unitPrice?: number;
  lineSubtotal: number;
  lineTax?: number;
  lineTotal: number;
}

interface CreateInvoiceParams {
  companyId: string;
  userId: string;
  vendorId: string;
  poId?: string;
  invoiceNumber: string;
  invoiceDate: string;
  dueDate?: string;
  currency: string;
  amountSubtotal: number;
  amountTax?: number;
  amountTotal: number;
  sourceChannel?: string;
  lines: InvoiceLineInput[];
}

export async function createInvoice(params: CreateInvoiceParams) {
  const client = await pool.connect();
  try {
    await client.query('BEGIN');

    // Duplicate check
    const dupRes = await client.query(
      `SELECT invoice_id FROM invoice WHERE company_id = $1 AND vendor_id = $2 AND invoice_number = $3`,
      [params.companyId, params.vendorId, params.invoiceNumber],
    );
    if (dupRes.rows.length > 0) {
      throw new AppError(409, 'DUPLICATE_INVOICE', `Invoice ${params.invoiceNumber} already exists for this vendor`);
    }

    // Validate vendor
    const vendorRes = await client.query(
      `SELECT vendor_id FROM vendor WHERE vendor_id = $1 AND company_id = $2`,
      [params.vendorId, params.companyId],
    );
    if (vendorRes.rows.length === 0) throw new AppError(404, 'NOT_FOUND', 'Vendor not found');

    // Validate PO if provided
    if (params.poId) {
      const poRes = await client.query(
        `SELECT po_id FROM purchase_order WHERE po_id = $1 AND company_id = $2`,
        [params.poId, params.companyId],
      );
      if (poRes.rows.length === 0) throw new AppError(404, 'NOT_FOUND', 'Purchase order not found');
    }

    const matchType = params.poId ? '3WAY' : '2WAY';

    const invRes = await client.query(
      `INSERT INTO invoice (company_id, vendor_id, po_id, invoice_number, invoice_date, due_date, currency, amount_subtotal, amount_tax, amount_total, status, match_type, source_channel)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, 'RECEIVED', $11, $12)
       RETURNING *`,
      [
        params.companyId,
        params.vendorId,
        params.poId || null,
        params.invoiceNumber,
        params.invoiceDate,
        params.dueDate || null,
        params.currency,
        params.amountSubtotal,
        params.amountTax || 0,
        params.amountTotal,
        matchType,
        params.sourceChannel || 'API',
      ],
    );
    const invoice = invRes.rows[0];

    for (let i = 0; i < params.lines.length; i++) {
      const line = params.lines[i];
      await client.query(
        `INSERT INTO invoice_line (invoice_id, line_no, po_line_id, item_id, description, quantity_invoiced, unit_price, line_subtotal, line_tax, line_total)
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)`,
        [
          invoice.invoice_id,
          i + 1,
          line.poLineId || null,
          line.itemId || null,
          line.description || null,
          line.quantityInvoiced || null,
          line.unitPrice || null,
          line.lineSubtotal,
          line.lineTax || 0,
          line.lineTotal,
        ],
      );
    }

    await logAuditEvent({
      companyId: params.companyId,
      actorUserId: params.userId,
      actorType: 'USER',
      actionCode: 'INVOICE_CREATED',
      entityType: 'INVOICE',
      entityId: invoice.invoice_id,
      payload: { invoiceNumber: params.invoiceNumber, vendorId: params.vendorId, amountTotal: params.amountTotal },
      client,
    });

    await client.query('COMMIT');
    return invoice;
  } catch (err) {
    await client.query('ROLLBACK');
    throw err;
  } finally {
    client.release();
  }
}

export async function runMatch(companyId: string, userId: string, invoiceId: string) {
  const client = await pool.connect();
  try {
    await client.query('BEGIN');

    const invRes = await client.query(
      `SELECT * FROM invoice WHERE invoice_id = $1 AND company_id = $2`,
      [invoiceId, companyId],
    );
    if (invRes.rows.length === 0) throw new AppError(404, 'NOT_FOUND', 'Invoice not found');
    const invoice = invRes.rows[0];

    if (invoice.status !== 'RECEIVED' && invoice.status !== 'UNDER_REVIEW') {
      throw new AppError(400, 'INVALID_STATUS', `Cannot run match for invoice in status ${invoice.status}`);
    }

    // Check for duplicate within same vendor
    const dupRes = await client.query(
      `SELECT invoice_id FROM invoice
       WHERE company_id = $1 AND vendor_id = $2 AND invoice_number = $3 AND invoice_id != $4`,
      [companyId, invoice.vendor_id, invoice.invoice_number, invoiceId],
    );
    const duplicateInvoiceFound = dupRes.rows.length > 0;

    await client.query(
      `INSERT INTO invoice_match_result (invoice_id, check_name, passed, detail)
       VALUES ($1, 'DUPLICATE_CHECK', $2, $3)`,
      [invoiceId, !duplicateInvoiceFound, duplicateInvoiceFound ? 'Duplicate found' : 'No duplicate'],
    );

    let matchPassed = true;
    let priceVariancePercent = 0;
    let qtyVariancePercent = 0;

    // 2-way match: compare invoice total vs PO total
    if (invoice.po_id) {
      const poRes = await client.query(
        `SELECT total_amount FROM purchase_order WHERE po_id = $1`,
        [invoice.po_id],
      );
      const poTotal = parseFloat(poRes.rows[0].total_amount);
      const invTotal = parseFloat(invoice.amount_total);
      priceVariancePercent = poTotal > 0 ? Math.abs((invTotal - poTotal) / poTotal) * 100 : 0;

      const pricePassed = priceVariancePercent <= 1; // 1% tolerance
      await client.query(
        `INSERT INTO invoice_match_result (invoice_id, check_name, passed, tolerance_applied, detail)
         VALUES ($1, 'PO_TOTAL_CHECK', $2, $3, $4)`,
        [invoiceId, pricePassed, 1.0, `Invoice: ${invTotal}, PO: ${poTotal}, Variance: ${priceVariancePercent.toFixed(2)}%`],
      );
      if (!pricePassed) matchPassed = false;

      // 3-way match: compare receipt qty vs invoice qty
      if (invoice.match_type === '3WAY') {
        const invLinesRes = await client.query(
          `SELECT il.po_line_id, il.quantity_invoiced FROM invoice_line il WHERE il.invoice_id = $1 AND il.po_line_id IS NOT NULL`,
          [invoiceId],
        );

        for (const invLine of invLinesRes.rows) {
          if (!invLine.po_line_id || !invLine.quantity_invoiced) continue;
          const rcptRes = await client.query(
            `SELECT COALESCE(SUM(rl.accepted_qty), 0) AS total_received
             FROM receipt_line rl
             JOIN receipt r ON r.receipt_id = rl.receipt_id
             WHERE rl.po_line_id = $1 AND r.status = 'POSTED'`,
            [invLine.po_line_id],
          );
          const received = parseFloat(rcptRes.rows[0].total_received);
          const invoiced = parseFloat(invLine.quantity_invoiced);
          const qtyVar = received > 0 ? Math.abs((invoiced - received) / received) * 100 : (invoiced > 0 ? 100 : 0);
          if (qtyVar > qtyVariancePercent) qtyVariancePercent = qtyVar;

          const qtyPassed = qtyVar <= 2; // 2% tolerance
          await client.query(
            `INSERT INTO invoice_match_result (invoice_id, check_name, passed, tolerance_applied, detail)
             VALUES ($1, 'RECEIPT_QTY_CHECK', $2, $3, $4)`,
            [invoiceId, qtyPassed, 2.0, `PO Line ${invLine.po_line_id}: invoiced ${invoiced}, received ${received}, variance ${qtyVar.toFixed(2)}%`],
          );
          if (!qtyPassed) matchPassed = false;
        }
      }
    }

    // Evaluate invoice rules
    const context = {
      duplicateInvoiceFound,
      matchPassed,
      priceVariancePercent,
      qtyVariancePercent,
      priceTolerancePercent: 1,
      quantityTolerancePercent: 2,
    };

    const ruleResult = await evaluateRules(companyId, 'INVOICE', context);

    let finalStatus = matchPassed ? 'MATCHED' : 'EXCEPTION';

    if (ruleResult.matched && ruleResult.finalOutcome) {
      const outcome = ruleResult.finalOutcome;
      if (outcome.action === 'AUTO_APPROVE_FOR_PAYMENT') {
        finalStatus = 'APPROVED_FOR_PAYMENT';
      } else if (outcome.action === 'AUTO_REJECT') {
        finalStatus = 'REJECTED';
      } else if (outcome.action === 'ROUTE_EXCEPTION') {
        finalStatus = 'EXCEPTION';
      }
    }

    // Record ACTUAL budget transaction on approval
    if (finalStatus === 'APPROVED_FOR_PAYMENT' && invoice.po_id) {
      const poRes = await client.query(
        `SELECT requisition_id FROM purchase_order WHERE po_id = $1`,
        [invoice.po_id],
      );
      const reqId = poRes.rows[0]?.requisition_id;
      if (reqId) {
        const reqRes = await client.query(
          `SELECT cost_center_id FROM requisition WHERE requisition_id = $1`,
          [reqId],
        );
        const costCenterId = reqRes.rows[0]?.cost_center_id;
        if (costCenterId) {
          const invLinesRes = await client.query(
            `SELECT il.po_line_id, il.line_total FROM invoice_line il WHERE il.invoice_id = $1`,
            [invoiceId],
          );
          for (const il of invLinesRes.rows) {
            if (!il.po_line_id) continue;
            const polRes = await client.query(
              `SELECT category_id FROM purchase_order_line WHERE po_line_id = $1`,
              [il.po_line_id],
            );
            const catId = polRes.rows[0]?.category_id;
            if (catId) {
              const budgetLineId = await budgetService.findBudgetLine(companyId, costCenterId, catId, client);
              if (budgetLineId) {
                // Release encumbrance
                await budgetService.recordTransaction(
                  budgetLineId, 'RELEASE', 'PURCHASE_ORDER', invoice.po_id, parseFloat(il.line_total), client,
                );
                // Record actual
                await budgetService.recordTransaction(
                  budgetLineId, 'ACTUAL', 'INVOICE', invoiceId, parseFloat(il.line_total), client,
                );
              }
            }
          }
        }
      }
    }

    await client.query(`UPDATE invoice SET status = $1 WHERE invoice_id = $2`, [finalStatus, invoiceId]);

    await logAuditEvent({
      companyId,
      actorUserId: userId,
      actorType: 'USER',
      actionCode: 'INVOICE_MATCHED',
      entityType: 'INVOICE',
      entityId: invoiceId,
      payload: { finalStatus, matchPassed, priceVariancePercent, qtyVariancePercent, ruleOutcome: ruleResult.finalOutcome },
      client,
    });

    await client.query('COMMIT');

    return { invoiceId, status: finalStatus, matchPassed, priceVariancePercent, qtyVariancePercent, ruleOutcome: ruleResult.finalOutcome };
  } catch (err) {
    await client.query('ROLLBACK');
    throw err;
  } finally {
    client.release();
  }
}
