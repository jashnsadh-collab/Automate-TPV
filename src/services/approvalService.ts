import { pool, query } from '../db/pool';
import { completeWorkflow } from './workflowService';
import * as budgetService from './budgetService';
import { logAuditEvent } from './auditService';
import { startWorkflow } from './workflowService';
import { AppError } from '../middleware/errorHandler';

export async function listTasks(
  companyId: string,
  filters: { assigneeUserId?: string; status?: string },
) {
  let sql = `
    SELECT at.*, wi.entity_type, wi.entity_id, wi.workflow_type, wi.status AS workflow_status
    FROM approval_task at
    JOIN approval_workflow_instance wi ON wi.workflow_instance_id = at.workflow_instance_id
    WHERE wi.company_id = $1
  `;
  const params: any[] = [companyId];
  let idx = 2;

  if (filters.assigneeUserId) {
    sql += ` AND at.assignee_user_id = $${idx}`;
    params.push(filters.assigneeUserId);
    idx++;
  }

  if (filters.status) {
    sql += ` AND at.status = $${idx}`;
    params.push(filters.status);
    idx++;
  }

  sql += ' ORDER BY at.sla_due_at ASC NULLS LAST';

  const result = await query(sql, params);
  return result.rows;
}

export async function decideTask(
  companyId: string,
  userId: string,
  taskId: string,
  decision: 'APPROVE' | 'REJECT' | 'ESCALATE',
  reason?: string,
) {
  const client = await pool.connect();
  try {
    await client.query('BEGIN');

    const taskRes = await client.query(
      `SELECT at.*, wi.entity_type, wi.entity_id, wi.workflow_type, wi.company_id, wi.workflow_instance_id
       FROM approval_task at
       JOIN approval_workflow_instance wi ON wi.workflow_instance_id = at.workflow_instance_id
       WHERE at.approval_task_id = $1 AND wi.company_id = $2`,
      [taskId, companyId],
    );
    if (taskRes.rows.length === 0) throw new AppError(404, 'NOT_FOUND', 'Approval task not found');
    const task = taskRes.rows[0];

    if (task.status !== 'PENDING') {
      throw new AppError(400, 'INVALID_STATUS', `Task is already ${task.status}`);
    }

    // Update the task
    await client.query(
      `UPDATE approval_task SET decision = $1, decision_reason = $2, status = 'COMPLETED', decided_at = NOW()
       WHERE approval_task_id = $3`,
      [decision, reason || null, taskId],
    );

    if (decision === 'APPROVE') {
      // Check if this was the last pending task
      const pendingRes = await client.query(
        `SELECT COUNT(*) AS cnt FROM approval_task
         WHERE workflow_instance_id = $1 AND status = 'PENDING'`,
        [task.workflow_instance_id],
      );
      const pendingCount = parseInt(pendingRes.rows[0].cnt, 10);

      if (pendingCount === 0) {
        // All tasks approved — complete the workflow
        await completeWorkflow(task.workflow_instance_id, 'APPROVED', client);

        // Update entity status based on type
        await updateEntityOnApproval(task.entity_type, task.entity_id, client);
      }
    } else if (decision === 'REJECT') {
      await completeWorkflow(task.workflow_instance_id, 'REJECTED', client);

      // Update entity status + release budget for requisitions
      await updateEntityOnRejection(companyId, task.entity_type, task.entity_id, client);
    } else if (decision === 'ESCALATE') {
      // Create new tasks for escalation roles
      const escalationRoles = ['PROCUREMENT_HEAD', 'FINANCE_CONTROLLER'];
      for (let i = 0; i < escalationRoles.length; i++) {
        const role = escalationRoles[i];
        const userRes = await client.query(
          `SELECT user_id FROM app_user WHERE company_id = $1 AND role_code = $2 AND is_active = TRUE LIMIT 1`,
          [companyId, role],
        );
        const assigneeUserId = userRes.rows.length > 0 ? userRes.rows[0].user_id : null;
        const slaDue = new Date(Date.now() + 24 * 60 * 60 * 1000);

        // Get max step_no
        const maxStepRes = await client.query(
          `SELECT COALESCE(MAX(step_no), 0) AS max_step FROM approval_task WHERE workflow_instance_id = $1`,
          [task.workflow_instance_id],
        );
        const nextStep = parseInt(maxStepRes.rows[0].max_step, 10) + 1 + i;

        await client.query(
          `INSERT INTO approval_task (workflow_instance_id, step_no, assignee_user_id, assignee_role_code, status, sla_due_at)
           VALUES ($1, $2, $3, $4, 'PENDING', $5)`,
          [task.workflow_instance_id, nextStep, assigneeUserId, role, slaDue],
        );
      }

      await client.query(
        `UPDATE approval_workflow_instance SET status = 'ESCALATED' WHERE workflow_instance_id = $1`,
        [task.workflow_instance_id],
      );
    }

    await logAuditEvent({
      companyId,
      actorUserId: userId,
      actorType: 'USER',
      actionCode: `APPROVAL_TASK_${decision}`,
      entityType: task.entity_type,
      entityId: task.entity_id,
      payload: { taskId, decision, reason, workflowType: task.workflow_type },
      client,
    });

    await client.query('COMMIT');
    return { taskId, decision, entityType: task.entity_type, entityId: task.entity_id };
  } catch (err) {
    await client.query('ROLLBACK');
    throw err;
  } finally {
    client.release();
  }
}

async function updateEntityOnApproval(entityType: string, entityId: string, client: any) {
  switch (entityType) {
    case 'VENDOR':
      await client.query(`UPDATE vendor SET status = 'APPROVED', approved_at = NOW(), updated_at = NOW() WHERE vendor_id = $1`, [entityId]);
      break;
    case 'REQUISITION':
      await client.query(`UPDATE requisition SET status = 'APPROVED' WHERE requisition_id = $1`, [entityId]);
      break;
    case 'PO':
      await client.query(`UPDATE purchase_order SET status = 'APPROVED', approved_at = NOW() WHERE po_id = $1`, [entityId]);
      break;
    case 'INVOICE':
      await client.query(`UPDATE invoice SET status = 'APPROVED_FOR_PAYMENT' WHERE invoice_id = $1`, [entityId]);
      break;
    case 'PAYMENT_BATCH':
      await client.query(`UPDATE payment_batch SET status = 'APPROVED', approved_at = NOW() WHERE payment_batch_id = $1`, [entityId]);
      break;
  }
}

async function updateEntityOnRejection(companyId: string, entityType: string, entityId: string, client: any) {
  switch (entityType) {
    case 'VENDOR':
      await client.query(`UPDATE vendor SET status = 'REJECTED', updated_at = NOW() WHERE vendor_id = $1`, [entityId]);
      break;
    case 'REQUISITION':
      await client.query(`UPDATE requisition SET status = 'REJECTED' WHERE requisition_id = $1`, [entityId]);
      // Release pre-encumbrance
      const reqRes = await client.query(
        `SELECT rl.category_id, rl.line_total, r.cost_center_id
         FROM requisition_line rl JOIN requisition r ON r.requisition_id = rl.requisition_id
         WHERE r.requisition_id = $1`,
        [entityId],
      );
      for (const line of reqRes.rows) {
        const budgetLineId = await budgetService.findBudgetLine(companyId, line.cost_center_id, line.category_id, client);
        if (budgetLineId) {
          await budgetService.recordTransaction(budgetLineId, 'RELEASE', 'REQUISITION', entityId, parseFloat(line.line_total), client);
        }
      }
      break;
    case 'PO':
      await client.query(`UPDATE purchase_order SET status = 'REJECTED' WHERE po_id = $1`, [entityId]);
      break;
    case 'INVOICE':
      await client.query(`UPDATE invoice SET status = 'REJECTED' WHERE invoice_id = $1`, [entityId]);
      break;
    case 'PAYMENT_BATCH':
      await client.query(`UPDATE payment_batch SET status = 'CANCELLED' WHERE payment_batch_id = $1`, [entityId]);
      break;
  }
}
