import { pool } from '../db/pool';
import { generateNumber } from './numberingService';
import { logAuditEvent } from './auditService';
import * as budgetService from './budgetService';
import { AppError } from '../middleware/errorHandler';

interface POLine {
  itemId?: string;
  categoryId: string;
  description?: string;
  quantityOrdered: number;
  unitPrice: number;
  taxAmount?: number;
  requisitionLineId?: string;
}

interface CreatePOParams {
  companyId: string;
  userId: string;
  vendorId: string;
  requisitionId?: string;
  currency: string;
  expectedDeliveryDate?: string;
  paymentTermsDays?: number;
  lines: POLine[];
}

export async function createPO(params: CreatePOParams) {
  const client = await pool.connect();
  try {
    await client.query('BEGIN');

    // Validate vendor is APPROVED or ACTIVE
    const vendorRes = await client.query(
      `SELECT status FROM vendor WHERE vendor_id = $1 AND company_id = $2`,
      [params.vendorId, params.companyId],
    );
    if (vendorRes.rows.length === 0) throw new AppError(404, 'NOT_FOUND', 'Vendor not found');
    const vendorStatus = vendorRes.rows[0].status;
    if (!['APPROVED', 'ACTIVE'].includes(vendorStatus)) {
      throw new AppError(400, 'INVALID_VENDOR_STATUS', `Vendor status ${vendorStatus} is not eligible for PO`);
    }

    const poNumber = await generateNumber('PO', 'purchase_order', 'po_number', params.companyId, client);
    const totalAmount = params.lines.reduce(
      (sum, l) => sum + l.quantityOrdered * l.unitPrice + (l.taxAmount || 0),
      0,
    );

    const poRes = await client.query(
      `INSERT INTO purchase_order (company_id, po_number, vendor_id, requisition_id, buyer_id, status, currency, total_amount, expected_delivery_date, payment_terms_days)
       VALUES ($1, $2, $3, $4, $5, 'DRAFT', $6, $7, $8, $9)
       RETURNING *`,
      [
        params.companyId,
        poNumber,
        params.vendorId,
        params.requisitionId || null,
        params.userId,
        params.currency,
        totalAmount,
        params.expectedDeliveryDate || null,
        params.paymentTermsDays || 30,
      ],
    );
    const po = poRes.rows[0];

    for (let i = 0; i < params.lines.length; i++) {
      const line = params.lines[i];
      const lineTotal = line.quantityOrdered * line.unitPrice + (line.taxAmount || 0);
      await client.query(
        `INSERT INTO purchase_order_line (po_id, line_no, item_id, category_id, description, quantity_ordered, unit_price, tax_amount, line_total, requisition_line_id)
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)`,
        [
          po.po_id,
          i + 1,
          line.itemId || null,
          line.categoryId,
          line.description || null,
          line.quantityOrdered,
          line.unitPrice,
          line.taxAmount || 0,
          lineTotal,
          line.requisitionLineId || null,
        ],
      );
    }

    await logAuditEvent({
      companyId: params.companyId,
      actorUserId: params.userId,
      actorType: 'USER',
      actionCode: 'PO_CREATED',
      entityType: 'PO',
      entityId: po.po_id,
      payload: { poNumber, vendorId: params.vendorId, totalAmount },
      client,
    });

    await client.query('COMMIT');
    return po;
  } catch (err) {
    await client.query('ROLLBACK');
    throw err;
  } finally {
    client.release();
  }
}

export async function issuePO(companyId: string, userId: string, poId: string) {
  const client = await pool.connect();
  try {
    await client.query('BEGIN');

    const poRes = await client.query(
      `SELECT * FROM purchase_order WHERE po_id = $1 AND company_id = $2`,
      [poId, companyId],
    );
    if (poRes.rows.length === 0) throw new AppError(404, 'NOT_FOUND', 'Purchase order not found');
    const po = poRes.rows[0];

    if (po.status !== 'DRAFT' && po.status !== 'APPROVED') {
      throw new AppError(400, 'INVALID_STATUS', `Cannot issue PO in status ${po.status}`);
    }

    // Convert PRE_ENCUMBRANCE to ENCUMBRANCE if requisition exists
    if (po.requisition_id) {
      const linesRes = await client.query(
        `SELECT pol.po_line_id, pol.category_id, pol.line_total
         FROM purchase_order_line pol WHERE pol.po_id = $1`,
        [poId],
      );

      const reqRes = await client.query(
        `SELECT cost_center_id FROM requisition WHERE requisition_id = $1`,
        [po.requisition_id],
      );
      const costCenterId = reqRes.rows[0]?.cost_center_id;

      if (costCenterId) {
        for (const line of linesRes.rows) {
          const budgetLineId = await budgetService.findBudgetLine(companyId, costCenterId, line.category_id, client);
          if (budgetLineId) {
            // Release the pre-encumbrance
            await budgetService.recordTransaction(
              budgetLineId,
              'RELEASE',
              'REQUISITION',
              po.requisition_id,
              parseFloat(line.line_total),
              client,
            );
            // Record encumbrance
            await budgetService.recordTransaction(
              budgetLineId,
              'ENCUMBRANCE',
              'PURCHASE_ORDER',
              poId,
              parseFloat(line.line_total),
              client,
            );
          }
        }
      }
    }

    await client.query(
      `UPDATE purchase_order SET status = 'ISSUED', issue_date = CURRENT_DATE, approved_at = NOW() WHERE po_id = $1`,
      [poId],
    );

    await logAuditEvent({
      companyId,
      actorUserId: userId,
      actorType: 'USER',
      actionCode: 'PO_ISSUED',
      entityType: 'PO',
      entityId: poId,
      payload: { poNumber: po.po_number },
      client,
    });

    await client.query('COMMIT');
    return { poId, status: 'ISSUED' };
  } catch (err) {
    await client.query('ROLLBACK');
    throw err;
  } finally {
    client.release();
  }
}
