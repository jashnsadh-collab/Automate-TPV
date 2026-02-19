import { PoolClient } from 'pg';
import { query } from '../db/pool';

/**
 * Generates a sequential number like REQ-20260219-0001.
 * Counts existing rows for today and increments.
 */
export async function generateNumber(
  prefix: string,
  table: string,
  column: string,
  companyId: string,
  client?: PoolClient,
): Promise<string> {
  const today = new Date();
  const datePart =
    today.getFullYear().toString() +
    String(today.getMonth() + 1).padStart(2, '0') +
    String(today.getDate()).padStart(2, '0');

  const pattern = `${prefix}-${datePart}-%`;

  // Allowlist of valid table/column combinations
  const allowed: Record<string, string[]> = {
    requisition: ['req_number'],
    purchase_order: ['po_number'],
    receipt: ['receipt_number'],
    invoice: ['invoice_number'],
    payment_batch: ['batch_number'],
    vendor: ['vendor_code'],
  };

  if (!allowed[table] || !allowed[table].includes(column)) {
    throw new Error(`Invalid table/column for numbering: ${table}.${column}`);
  }

  const sql = `SELECT COUNT(*) AS cnt FROM ${table} WHERE company_id = $1 AND ${column} LIKE $2`;
  const result = client ? await client.query(sql, [companyId, pattern]) : await query(sql, [companyId, pattern]);
  const count = parseInt(result.rows[0].cnt, 10) + 1;
  const seq = String(count).padStart(4, '0');
  return `${prefix}-${datePart}-${seq}`;
}
