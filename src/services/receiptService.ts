import { pool } from '../db/pool';
import { generateNumber } from './numberingService';
import { logAuditEvent } from './auditService';
import { AppError } from '../middleware/errorHandler';

interface ReceiptLineInput {
  poLineId: string;
  quantityReceived: number;
  acceptedQty: number;
  rejectedQty?: number;
}

interface CreateReceiptParams {
  companyId: string;
  userId: string;
  poId: string;
  receiptType: 'GOODS' | 'SERVICE' | 'RETURN';
  lines: ReceiptLineInput[];
}

export async function createReceipt(params: CreateReceiptParams) {
  const client = await pool.connect();
  try {
    await client.query('BEGIN');

    // Validate PO
    const poRes = await client.query(
      `SELECT * FROM purchase_order WHERE po_id = $1 AND company_id = $2`,
      [params.poId, params.companyId],
    );
    if (poRes.rows.length === 0) throw new AppError(404, 'NOT_FOUND', 'Purchase order not found');
    const po = poRes.rows[0];

    if (!['ISSUED', 'PARTIALLY_RECEIVED'].includes(po.status)) {
      throw new AppError(400, 'INVALID_STATUS', `Cannot create receipt for PO in status ${po.status}`);
    }

    const receiptNumber = await generateNumber('RCV', 'receipt', 'receipt_number', params.companyId, client);

    const rcptRes = await client.query(
      `INSERT INTO receipt (company_id, receipt_number, po_id, receipt_type, status, received_by, received_at)
       VALUES ($1, $2, $3, $4, 'POSTED', $5, NOW())
       RETURNING *`,
      [params.companyId, receiptNumber, params.poId, params.receiptType, params.userId],
    );
    const receipt = rcptRes.rows[0];

    for (const line of params.lines) {
      await client.query(
        `INSERT INTO receipt_line (receipt_id, po_line_id, quantity_received, accepted_qty, rejected_qty)
         VALUES ($1, $2, $3, $4, $5)`,
        [receipt.receipt_id, line.poLineId, line.quantityReceived, line.acceptedQty, line.rejectedQty || 0],
      );

      // Update PO line received quantity
      await client.query(
        `UPDATE purchase_order_line SET quantity_received = quantity_received + $1 WHERE po_line_id = $2`,
        [line.acceptedQty, line.poLineId],
      );

      // Inventory: if item is inventory-tracked, update balance
      const polRes = await client.query(
        `SELECT pol.item_id FROM purchase_order_line pol WHERE pol.po_line_id = $1`,
        [line.poLineId],
      );
      const itemId = polRes.rows[0]?.item_id;
      if (itemId) {
        const itemRes = await client.query(
          `SELECT is_inventory_item FROM item WHERE item_id = $1`,
          [itemId],
        );
        if (itemRes.rows[0]?.is_inventory_item) {
          // Get first location for company (or create a default)
          const locRes = await client.query(
            `SELECT location_id FROM inventory_location WHERE company_id = $1 AND is_active = TRUE LIMIT 1`,
            [params.companyId],
          );
          if (locRes.rows.length > 0) {
            const locationId = locRes.rows[0].location_id;

            await client.query(
              `INSERT INTO inventory_txn (company_id, item_id, location_id, txn_type, reference_type, reference_id, quantity)
               VALUES ($1, $2, $3, 'RECEIPT', 'RECEIPT', $4, $5)`,
              [params.companyId, itemId, locationId, receipt.receipt_id, line.acceptedQty],
            );

            await client.query(
              `INSERT INTO inventory_balance (company_id, item_id, location_id, qty_on_hand)
               VALUES ($1, $2, $3, $4)
               ON CONFLICT (company_id, item_id, location_id)
               DO UPDATE SET qty_on_hand = inventory_balance.qty_on_hand + $4, updated_at = NOW()`,
              [params.companyId, itemId, locationId, line.acceptedQty],
            );
          }
        }
      }
    }

    // Check if all PO lines are fully received
    const statusRes = await client.query(
      `SELECT
         CASE WHEN BOOL_AND(quantity_received >= quantity_ordered) THEN 'RECEIVED'
              ELSE 'PARTIALLY_RECEIVED'
         END AS new_status
       FROM purchase_order_line WHERE po_id = $1`,
      [params.poId],
    );
    const newPoStatus = statusRes.rows[0]?.new_status || 'PARTIALLY_RECEIVED';
    await client.query(`UPDATE purchase_order SET status = $1 WHERE po_id = $2`, [newPoStatus, params.poId]);

    await logAuditEvent({
      companyId: params.companyId,
      actorUserId: params.userId,
      actorType: 'USER',
      actionCode: 'RECEIPT_CREATED',
      entityType: 'RECEIPT',
      entityId: receipt.receipt_id,
      payload: { receiptNumber, poId: params.poId, poStatus: newPoStatus },
      client,
    });

    await client.query('COMMIT');
    return { ...receipt, poStatus: newPoStatus };
  } catch (err) {
    await client.query('ROLLBACK');
    throw err;
  } finally {
    client.release();
  }
}
