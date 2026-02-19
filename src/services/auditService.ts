import crypto from 'crypto';
import { PoolClient } from 'pg';
import { query } from '../db/pool';

interface AuditParams {
  companyId: string;
  actorUserId?: string;
  actorType: 'USER' | 'SYSTEM' | 'VENDOR';
  actionCode: string;
  entityType: string;
  entityId: string;
  payload?: Record<string, any>;
  client?: PoolClient;
}

export async function logAuditEvent(params: AuditParams): Promise<void> {
  const payloadJson = params.payload ? JSON.stringify(params.payload) : null;
  const payloadHash = payloadJson
    ? crypto.createHash('sha256').update(payloadJson).digest('hex')
    : null;

  const sql = `
    INSERT INTO audit_event (company_id, actor_user_id, actor_type, action_code, entity_type, entity_id, payload, payload_hash)
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
  `;
  const values = [
    params.companyId,
    params.actorUserId || null,
    params.actorType,
    params.actionCode,
    params.entityType,
    params.entityId,
    payloadJson,
    payloadHash,
  ];

  if (params.client) {
    await params.client.query(sql, values);
  } else {
    await query(sql, values);
  }
}
