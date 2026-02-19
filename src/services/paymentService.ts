import { pool } from '../db/pool';
import { generateNumber } from './numberingService';
import { logAuditEvent } from './auditService';
import { AppError } from '../middleware/errorHandler';

interface CreateBatchParams {
  companyId: string;
  userId: string;
  invoiceIds: string[];
  paymentMethod: 'ACH' | 'WIRE' | 'SEPA' | 'CHECK' | 'VIRTUAL_CARD';
  currency: string;
}

export async function createBatch(params: CreateBatchParams) {
  const client = await pool.connect();
  try {
    await client.query('BEGIN');

    // Validate all invoices are APPROVED_FOR_PAYMENT
    for (const invId of params.invoiceIds) {
      const invRes = await client.query(
        `SELECT invoice_id, vendor_id, amount_total, status FROM invoice WHERE invoice_id = $1 AND company_id = $2`,
        [invId, params.companyId],
      );
      if (invRes.rows.length === 0) throw new AppError(404, 'NOT_FOUND', `Invoice ${invId} not found`);
      if (invRes.rows[0].status !== 'APPROVED_FOR_PAYMENT') {
        throw new AppError(400, 'INVALID_STATUS', `Invoice ${invId} status is ${invRes.rows[0].status}, not APPROVED_FOR_PAYMENT`);
      }
    }

    // Check for blocked vendors
    const vendorCheck = await client.query(
      `SELECT DISTINCT v.vendor_id, v.legal_name, v.status
       FROM invoice i JOIN vendor v ON v.vendor_id = i.vendor_id
       WHERE i.invoice_id = ANY($1) AND v.status = 'BLOCKED'`,
      [params.invoiceIds],
    );
    if (vendorCheck.rows.length > 0) {
      throw new AppError(400, 'BLOCKED_VENDOR', `Blocked vendors: ${vendorCheck.rows.map((r: any) => r.legal_name).join(', ')}`);
    }

    const batchNumber = await generateNumber('PAY', 'payment_batch', 'batch_number', params.companyId, client);

    const batchRes = await client.query(
      `INSERT INTO payment_batch (company_id, batch_number, status, payment_method, currency, created_by)
       VALUES ($1, $2, 'DRAFT', $3, $4, $5)
       RETURNING *`,
      [params.companyId, batchNumber, params.paymentMethod, params.currency, params.userId],
    );
    const batch = batchRes.rows[0];

    // Group invoices by vendor
    const invoicesByVendor: Record<string, { invoiceId: string; amount: number }[]> = {};
    for (const invId of params.invoiceIds) {
      const invRes = await client.query(
        `SELECT vendor_id, amount_total FROM invoice WHERE invoice_id = $1`,
        [invId],
      );
      const inv = invRes.rows[0];
      if (!invoicesByVendor[inv.vendor_id]) invoicesByVendor[inv.vendor_id] = [];
      invoicesByVendor[inv.vendor_id].push({ invoiceId: invId, amount: parseFloat(inv.amount_total) });
    }

    // Create one payment per vendor, with allocations
    for (const [vendorId, invoices] of Object.entries(invoicesByVendor)) {
      const totalAmount = invoices.reduce((sum, inv) => sum + inv.amount, 0);

      const payRes = await client.query(
        `INSERT INTO payment (company_id, payment_batch_id, vendor_id, amount, currency, status)
         VALUES ($1, $2, $3, $4, $5, 'QUEUED')
         RETURNING payment_id`,
        [params.companyId, batch.payment_batch_id, vendorId, totalAmount, params.currency],
      );
      const paymentId = payRes.rows[0].payment_id;

      for (const inv of invoices) {
        await client.query(
          `INSERT INTO payment_allocation (payment_id, invoice_id, allocated_amount)
           VALUES ($1, $2, $3)`,
          [paymentId, inv.invoiceId, inv.amount],
        );
      }
    }

    await logAuditEvent({
      companyId: params.companyId,
      actorUserId: params.userId,
      actorType: 'USER',
      actionCode: 'PAYMENT_BATCH_CREATED',
      entityType: 'PAYMENT_BATCH',
      entityId: batch.payment_batch_id,
      payload: { batchNumber, invoiceCount: params.invoiceIds.length, paymentMethod: params.paymentMethod },
      client,
    });

    await client.query('COMMIT');
    return batch;
  } catch (err) {
    await client.query('ROLLBACK');
    throw err;
  } finally {
    client.release();
  }
}

export async function approveBatch(companyId: string, userId: string, batchId: string) {
  const client = await pool.connect();
  try {
    await client.query('BEGIN');

    const batchRes = await client.query(
      `SELECT * FROM payment_batch WHERE payment_batch_id = $1 AND company_id = $2`,
      [batchId, companyId],
    );
    if (batchRes.rows.length === 0) throw new AppError(404, 'NOT_FOUND', 'Payment batch not found');
    const batch = batchRes.rows[0];

    if (batch.status !== 'DRAFT' && batch.status !== 'PENDING_APPROVAL') {
      throw new AppError(400, 'INVALID_STATUS', `Cannot approve batch in status ${batch.status}`);
    }

    await client.query(
      `UPDATE payment_batch SET status = 'APPROVED', approved_at = NOW() WHERE payment_batch_id = $1`,
      [batchId],
    );

    await logAuditEvent({
      companyId,
      actorUserId: userId,
      actorType: 'USER',
      actionCode: 'PAYMENT_BATCH_APPROVED',
      entityType: 'PAYMENT_BATCH',
      entityId: batchId,
      payload: { batchNumber: batch.batch_number },
      client,
    });

    await client.query('COMMIT');
    return { batchId, status: 'APPROVED' };
  } catch (err) {
    await client.query('ROLLBACK');
    throw err;
  } finally {
    client.release();
  }
}

export async function executeBatch(companyId: string, userId: string, batchId: string) {
  const client = await pool.connect();
  try {
    await client.query('BEGIN');

    const batchRes = await client.query(
      `SELECT * FROM payment_batch WHERE payment_batch_id = $1 AND company_id = $2`,
      [batchId, companyId],
    );
    if (batchRes.rows.length === 0) throw new AppError(404, 'NOT_FOUND', 'Payment batch not found');
    const batch = batchRes.rows[0];

    if (batch.status !== 'APPROVED') {
      throw new AppError(400, 'INVALID_STATUS', `Cannot execute batch in status ${batch.status}`);
    }

    // Move to PROCESSING
    await client.query(
      `UPDATE payment_batch SET status = 'PROCESSING' WHERE payment_batch_id = $1`,
      [batchId],
    );

    // Process each payment
    const paymentsRes = await client.query(
      `SELECT payment_id FROM payment WHERE payment_batch_id = $1`,
      [batchId],
    );

    for (const pay of paymentsRes.rows) {
      await client.query(
        `UPDATE payment SET status = 'PROCESSED', processed_at = NOW() WHERE payment_id = $1`,
        [pay.payment_id],
      );

      // Update invoices to PAID
      const allocRes = await client.query(
        `SELECT invoice_id FROM payment_allocation WHERE payment_id = $1`,
        [pay.payment_id],
      );
      for (const alloc of allocRes.rows) {
        await client.query(
          `UPDATE invoice SET status = 'PAID' WHERE invoice_id = $1`,
          [alloc.invoice_id],
        );
      }
    }

    // Complete the batch
    await client.query(
      `UPDATE payment_batch SET status = 'COMPLETED' WHERE payment_batch_id = $1`,
      [batchId],
    );

    await logAuditEvent({
      companyId,
      actorUserId: userId,
      actorType: 'USER',
      actionCode: 'PAYMENT_BATCH_EXECUTED',
      entityType: 'PAYMENT_BATCH',
      entityId: batchId,
      payload: { batchNumber: batch.batch_number, paymentCount: paymentsRes.rows.length },
      client,
    });

    await client.query('COMMIT');
    return { batchId, status: 'COMPLETED', paymentsProcessed: paymentsRes.rows.length };
  } catch (err) {
    await client.query('ROLLBACK');
    throw err;
  } finally {
    client.release();
  }
}
