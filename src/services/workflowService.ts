import { PoolClient } from 'pg';
import { query } from '../db/pool';

interface StartWorkflowParams {
  companyId: string;
  entityType: 'VENDOR' | 'REQUISITION' | 'PO' | 'INVOICE' | 'PAYMENT_BATCH';
  entityId: string;
  workflowType: 'VENDOR_ONBOARDING' | 'PO_APPROVAL' | 'INVOICE_APPROVAL' | 'PAYMENT_APPROVAL';
  assigneeRoles: string[];
  client: PoolClient;
}

export async function startWorkflow(params: StartWorkflowParams): Promise<string> {
  const wfRes = await params.client.query(
    `INSERT INTO approval_workflow_instance (company_id, entity_type, entity_id, workflow_type, status)
     VALUES ($1, $2, $3, $4, 'OPEN')
     RETURNING workflow_instance_id`,
    [params.companyId, params.entityType, params.entityId, params.workflowType],
  );
  const workflowInstanceId = wfRes.rows[0].workflow_instance_id;

  // Look up users for each role and create tasks
  for (let i = 0; i < params.assigneeRoles.length; i++) {
    const role = params.assigneeRoles[i];
    const userRes = await params.client.query(
      `SELECT user_id FROM app_user WHERE company_id = $1 AND role_code = $2 AND is_active = TRUE LIMIT 1`,
      [params.companyId, role],
    );
    const assigneeUserId = userRes.rows.length > 0 ? userRes.rows[0].user_id : null;
    const slaDue = new Date(Date.now() + 24 * 60 * 60 * 1000); // 24h SLA

    await params.client.query(
      `INSERT INTO approval_task (workflow_instance_id, step_no, assignee_user_id, assignee_role_code, status, sla_due_at)
       VALUES ($1, $2, $3, $4, 'PENDING', $5)`,
      [workflowInstanceId, i + 1, assigneeUserId, role, slaDue],
    );
  }

  return workflowInstanceId;
}

export async function completeWorkflow(
  workflowInstanceId: string,
  status: 'APPROVED' | 'REJECTED' | 'CANCELLED',
  client: PoolClient,
): Promise<void> {
  await client.query(
    `UPDATE approval_workflow_instance SET status = $1, completed_at = NOW() WHERE workflow_instance_id = $2`,
    [status, workflowInstanceId],
  );
  // Mark remaining pending tasks as SKIPPED
  await client.query(
    `UPDATE approval_task SET status = 'SKIPPED' WHERE workflow_instance_id = $1 AND status = 'PENDING'`,
    [workflowInstanceId],
  );
}

export async function getWorkflowForEntity(
  companyId: string,
  entityType: string,
  entityId: string,
  client?: PoolClient,
): Promise<any | null> {
  const sql = `
    SELECT * FROM approval_workflow_instance
    WHERE company_id = $1 AND entity_type = $2 AND entity_id = $3
    ORDER BY started_at DESC LIMIT 1
  `;
  const result = client
    ? await client.query(sql, [companyId, entityType, entityId])
    : await query(sql, [companyId, entityType, entityId]);
  return result.rows[0] || null;
}
