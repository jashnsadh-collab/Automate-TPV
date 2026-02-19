import { PoolClient } from 'pg';
import { query } from '../db/pool';

interface BudgetAvailability {
  budgetLineId: string;
  allocated: number;
  committed: number;
  consumed: number;
  available: number;
  canProceed: boolean;
}

export async function checkAvailability(
  budgetLineId: string,
  amount: number,
  client?: PoolClient,
): Promise<BudgetAvailability> {
  const sql = `
    SELECT budget_line_id, allocated_amount, committed_amount, consumed_amount
    FROM budget_line WHERE budget_line_id = $1
  `;
  const result = client ? await client.query(sql, [budgetLineId]) : await query(sql, [budgetLineId]);
  if (result.rows.length === 0) {
    throw new Error(`Budget line ${budgetLineId} not found`);
  }
  const row = result.rows[0];
  const allocated = parseFloat(row.allocated_amount);
  const committed = parseFloat(row.committed_amount);
  const consumed = parseFloat(row.consumed_amount);
  const available = allocated - committed - consumed;

  return {
    budgetLineId,
    allocated,
    committed,
    consumed,
    available,
    canProceed: available >= amount,
  };
}

export async function findBudgetLine(
  companyId: string,
  costCenterId: string,
  categoryId: string,
  client?: PoolClient,
): Promise<string | null> {
  const sql = `
    SELECT bl.budget_line_id
    FROM budget_line bl
    JOIN budget b ON b.budget_id = bl.budget_id
    WHERE b.company_id = $1
      AND bl.cost_center_id = $2
      AND bl.category_id = $3
      AND b.status = 'ACTIVE'
      AND b.valid_from <= CURRENT_DATE
      AND b.valid_to >= CURRENT_DATE
    LIMIT 1
  `;
  const result = client
    ? await client.query(sql, [companyId, costCenterId, categoryId])
    : await query(sql, [companyId, costCenterId, categoryId]);
  return result.rows.length > 0 ? result.rows[0].budget_line_id : null;
}

type TxnType = 'PRE_ENCUMBRANCE' | 'ENCUMBRANCE' | 'ACTUAL' | 'RELEASE';
type SourceType = 'REQUISITION' | 'PURCHASE_ORDER' | 'INVOICE' | 'PAYMENT' | 'ADJUSTMENT';

export async function recordTransaction(
  budgetLineId: string,
  txnType: TxnType,
  sourceType: SourceType,
  sourceId: string,
  amount: number,
  client: PoolClient,
): Promise<void> {
  await client.query(
    `INSERT INTO budget_transaction (budget_line_id, txn_type, source_type, source_id, amount)
     VALUES ($1, $2, $3, $4, $5)
     ON CONFLICT (budget_line_id, source_type, source_id, txn_type) DO NOTHING`,
    [budgetLineId, txnType, sourceType, sourceId, amount],
  );

  // Update the budget_line summary columns
  if (txnType === 'PRE_ENCUMBRANCE' || txnType === 'ENCUMBRANCE') {
    await client.query(
      `UPDATE budget_line SET committed_amount = committed_amount + $1, updated_at = NOW() WHERE budget_line_id = $2`,
      [amount, budgetLineId],
    );
  } else if (txnType === 'ACTUAL') {
    await client.query(
      `UPDATE budget_line SET consumed_amount = consumed_amount + $1, updated_at = NOW() WHERE budget_line_id = $2`,
      [amount, budgetLineId],
    );
  } else if (txnType === 'RELEASE') {
    await client.query(
      `UPDATE budget_line SET committed_amount = GREATEST(committed_amount - $1, 0), updated_at = NOW() WHERE budget_line_id = $2`,
      [amount, budgetLineId],
    );
  }
}
