import { pool } from '../db/pool';
import { generateNumber } from './numberingService';
import { logAuditEvent } from './auditService';
import { evaluateRules } from '../rules/engine';
import { startWorkflow, completeWorkflow } from './workflowService';
import * as budgetService from './budgetService';
import { AppError } from '../middleware/errorHandler';

interface RequisitionLine {
  itemId?: string;
  categoryId: string;
  description?: string;
  quantity: number;
  unitPrice: number;
  taxAmount?: number;
  vendorId?: string;
}

interface CreateRequisitionParams {
  companyId: string;
  userId: string;
  costCenterId: string;
  currency: string;
  neededByDate?: string;
  justification?: string;
  lines: RequisitionLine[];
}

export async function createRequisition(params: CreateRequisitionParams) {
  const client = await pool.connect();
  try {
    await client.query('BEGIN');

    const reqNumber = await generateNumber('REQ', 'requisition', 'req_number', params.companyId, client);

    const totalAmount = params.lines.reduce((sum, l) => sum + l.quantity * l.unitPrice + (l.taxAmount || 0), 0);

    const reqRes = await client.query(
      `INSERT INTO requisition (company_id, req_number, requester_id, cost_center_id, status, currency, total_amount, needed_by_date, justification)
       VALUES ($1, $2, $3, $4, 'DRAFT', $5, $6, $7, $8)
       RETURNING *`,
      [
        params.companyId,
        reqNumber,
        params.userId,
        params.costCenterId,
        params.currency,
        totalAmount,
        params.neededByDate || null,
        params.justification || null,
      ],
    );
    const req = reqRes.rows[0];

    for (let i = 0; i < params.lines.length; i++) {
      const line = params.lines[i];
      const lineTotal = line.quantity * line.unitPrice + (line.taxAmount || 0);
      await client.query(
        `INSERT INTO requisition_line (requisition_id, line_no, item_id, category_id, description, quantity, unit_price, tax_amount, line_total, vendor_id)
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)`,
        [
          req.requisition_id,
          i + 1,
          line.itemId || null,
          line.categoryId,
          line.description || null,
          line.quantity,
          line.unitPrice,
          line.taxAmount || 0,
          lineTotal,
          line.vendorId || null,
        ],
      );
    }

    await logAuditEvent({
      companyId: params.companyId,
      actorUserId: params.userId,
      actorType: 'USER',
      actionCode: 'REQUISITION_CREATED',
      entityType: 'REQUISITION',
      entityId: req.requisition_id,
      payload: { reqNumber, totalAmount, lineCount: params.lines.length },
      client,
    });

    await client.query('COMMIT');
    return req;
  } catch (err) {
    await client.query('ROLLBACK');
    throw err;
  } finally {
    client.release();
  }
}

export async function submitRequisition(companyId: string, userId: string, requisitionId: string) {
  const client = await pool.connect();
  try {
    await client.query('BEGIN');

    const reqRes = await client.query(
      `SELECT * FROM requisition WHERE requisition_id = $1 AND company_id = $2`,
      [requisitionId, companyId],
    );
    if (reqRes.rows.length === 0) throw new AppError(404, 'NOT_FOUND', 'Requisition not found');
    const req = reqRes.rows[0];

    if (req.status !== 'DRAFT') {
      throw new AppError(400, 'INVALID_STATUS', `Cannot submit requisition in status ${req.status}`);
    }

    // Get lines for budget check
    const linesRes = await client.query(
      `SELECT * FROM requisition_line WHERE requisition_id = $1 ORDER BY line_no`,
      [requisitionId],
    );

    // Budget check per line
    let budgetAvailable = true;
    for (const line of linesRes.rows) {
      const budgetLineId = await budgetService.findBudgetLine(companyId, req.cost_center_id, line.category_id, client);
      if (budgetLineId) {
        const avail = await budgetService.checkAvailability(budgetLineId, parseFloat(line.line_total), client);
        if (!avail.canProceed) {
          budgetAvailable = false;
          break;
        }
      } else {
        budgetAvailable = false;
        break;
      }
    }

    // Get vendor info for first line's vendor (if any)
    let vendorStatus = 'APPROVED';
    let vendorRiskScore = 100;
    const firstVendorLine = linesRes.rows.find((l: any) => l.vendor_id);
    if (firstVendorLine) {
      const vendorRes = await client.query(`SELECT status, risk_score FROM vendor WHERE vendor_id = $1`, [
        firstVendorLine.vendor_id,
      ]);
      if (vendorRes.rows.length > 0) {
        vendorStatus = vendorRes.rows[0].status;
        vendorRiskScore = parseFloat(vendorRes.rows[0].risk_score);
      }
    }

    const context = {
      totalAmount: parseFloat(req.total_amount),
      budgetAvailable,
      budgetControlMode: 'HARD_STOP',
      vendorStatus,
      vendorRiskScore,
    };

    // Evaluate requisition rules
    const ruleResult = await evaluateRules(companyId, 'REQUISITION', context);

    let finalStatus = 'SUBMITTED';

    if (ruleResult.matched && ruleResult.finalOutcome) {
      const outcome = ruleResult.finalOutcome;
      if (outcome.action === 'AUTO_APPROVE') {
        finalStatus = 'APPROVED';
      } else if (outcome.action === 'AUTO_REJECT') {
        finalStatus = 'REJECTED';
      } else if (outcome.action === 'ROUTE_APPROVAL') {
        const roles = outcome.routeToRoles || ['COST_CENTER_MANAGER'];
        await startWorkflow({
          companyId,
          entityType: 'REQUISITION',
          entityId: requisitionId,
          workflowType: 'PO_APPROVAL',
          assigneeRoles: roles,
          client,
        });
      }
    } else {
      // No rule matched — route for manual approval
      await startWorkflow({
        companyId,
        entityType: 'REQUISITION',
        entityId: requisitionId,
        workflowType: 'PO_APPROVAL',
        assigneeRoles: ['COST_CENTER_MANAGER'],
        client,
      });
    }

    // Record pre-encumbrance for approved or submitted
    if (finalStatus !== 'REJECTED') {
      for (const line of linesRes.rows) {
        const budgetLineId = await budgetService.findBudgetLine(companyId, req.cost_center_id, line.category_id, client);
        if (budgetLineId) {
          await budgetService.recordTransaction(
            budgetLineId,
            'PRE_ENCUMBRANCE',
            'REQUISITION',
            requisitionId,
            parseFloat(line.line_total),
            client,
          );
        }
      }
    }

    await client.query(
      `UPDATE requisition SET status = $1, submitted_at = NOW() WHERE requisition_id = $2`,
      [finalStatus, requisitionId],
    );

    await logAuditEvent({
      companyId,
      actorUserId: userId,
      actorType: 'USER',
      actionCode: 'REQUISITION_SUBMITTED',
      entityType: 'REQUISITION',
      entityId: requisitionId,
      payload: { finalStatus, context, ruleOutcome: ruleResult.finalOutcome },
      client,
    });

    await client.query('COMMIT');

    return { requisitionId, status: finalStatus, ruleOutcome: ruleResult.finalOutcome, budgetAvailable };
  } catch (err) {
    await client.query('ROLLBACK');
    throw err;
  } finally {
    client.release();
  }
}
