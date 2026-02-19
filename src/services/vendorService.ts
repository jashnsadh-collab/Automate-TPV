import { pool } from '../db/pool';
import { generateNumber } from './numberingService';
import { logAuditEvent } from './auditService';
import { evaluateRules } from '../rules/engine';
import { startWorkflow, completeWorkflow } from './workflowService';
import { AppError } from '../middleware/errorHandler';

interface CreateVendorParams {
  companyId: string;
  userId: string;
  legalName: string;
  displayName?: string;
  taxId?: string;
  paymentTermsDays?: number;
  preferredCurrency?: string;
}

export async function createVendor(params: CreateVendorParams) {
  const client = await pool.connect();
  try {
    await client.query('BEGIN');

    const vendorCode = await generateNumber('VEN', 'vendor', 'vendor_code', params.companyId, client);

    const result = await client.query(
      `INSERT INTO vendor (company_id, vendor_code, legal_name, display_name, tax_id, payment_terms_days, preferred_currency, status, risk_score)
       VALUES ($1, $2, $3, $4, $5, $6, $7, 'REGISTERED', 0)
       RETURNING *`,
      [
        params.companyId,
        vendorCode,
        params.legalName,
        params.displayName || params.legalName,
        params.taxId || null,
        params.paymentTermsDays || 30,
        params.preferredCurrency || null,
      ],
    );

    await logAuditEvent({
      companyId: params.companyId,
      actorUserId: params.userId,
      actorType: 'USER',
      actionCode: 'VENDOR_CREATED',
      entityType: 'VENDOR',
      entityId: result.rows[0].vendor_id,
      payload: { vendorCode, legalName: params.legalName },
      client,
    });

    await client.query('COMMIT');
    return result.rows[0];
  } catch (err) {
    await client.query('ROLLBACK');
    throw err;
  } finally {
    client.release();
  }
}

export async function submitOnboarding(companyId: string, userId: string, vendorId: string) {
  const client = await pool.connect();
  try {
    await client.query('BEGIN');

    const vendorRes = await client.query(
      `SELECT * FROM vendor WHERE vendor_id = $1 AND company_id = $2`,
      [vendorId, companyId],
    );
    if (vendorRes.rows.length === 0) throw new AppError(404, 'NOT_FOUND', 'Vendor not found');
    const vendor = vendorRes.rows[0];

    if (vendor.status !== 'REGISTERED') {
      throw new AppError(400, 'INVALID_STATUS', `Cannot submit vendor in status ${vendor.status}`);
    }

    // Gather context for rules evaluation
    const docsRes = await client.query(
      `SELECT document_type, status FROM vendor_document WHERE vendor_id = $1`,
      [vendorId],
    );
    const requiredDocs = ['TAX_CERTIFICATE', 'BUSINESS_REGISTRATION', 'BANK_LETTER', 'INSURANCE_CERTIFICATE'];
    const validDocs = docsRes.rows.filter((d: any) => d.status === 'VALID').map((d: any) => d.document_type);
    const missingDocs = requiredDocs.filter((d) => !validDocs.includes(d));

    const bankRes = await client.query(
      `SELECT is_verified FROM vendor_bank_account WHERE vendor_id = $1 AND is_active = TRUE AND is_verified = TRUE LIMIT 1`,
      [vendorId],
    );

    const riskRes = await client.query(
      `SELECT score, sanctions_hit FROM vendor_risk_assessment WHERE vendor_id = $1 ORDER BY assessed_at DESC LIMIT 1`,
      [vendorId],
    );

    const riskScore = riskRes.rows.length > 0 ? parseFloat(riskRes.rows[0].score) : parseFloat(vendor.risk_score);
    const sanctionsHit = riskRes.rows.length > 0 ? riskRes.rows[0].sanctions_hit : false;
    const bankAccountVerified = bankRes.rows.length > 0;

    const context = {
      riskScore,
      countMissingDocuments: missingDocs.length,
      sanctionsHit,
      bankAccountVerified,
      taxIdVerified: !!vendor.tax_id,
    };

    // Update to UNDER_REVIEW
    await client.query(
      `UPDATE vendor SET status = 'UNDER_REVIEW', onboarding_submitted_at = NOW(), updated_at = NOW() WHERE vendor_id = $1`,
      [vendorId],
    );

    // Evaluate vendor rules
    const ruleResult = await evaluateRules(companyId, 'VENDOR', context);

    let finalStatus = 'UNDER_REVIEW';
    if (ruleResult.matched && ruleResult.finalOutcome) {
      const outcome = ruleResult.finalOutcome;
      if (outcome.action === 'AUTO_APPROVE') {
        finalStatus = outcome.finalStatus || 'APPROVED';
        await client.query(
          `UPDATE vendor SET status = $1, approved_at = NOW(), updated_at = NOW() WHERE vendor_id = $2`,
          [finalStatus, vendorId],
        );
      } else if (outcome.action === 'AUTO_REJECT') {
        finalStatus = 'REJECTED';
        await client.query(
          `UPDATE vendor SET status = 'REJECTED', rejected_reason = $1, updated_at = NOW() WHERE vendor_id = $2`,
          [outcome.rejectReasonCode || 'POLICY_FAILED', vendorId],
        );
      } else if (outcome.action === 'ROUTE_APPROVAL') {
        const roles = outcome.routeToRoles || ['PROCUREMENT_HEAD'];
        await startWorkflow({
          companyId,
          entityType: 'VENDOR',
          entityId: vendorId,
          workflowType: 'VENDOR_ONBOARDING',
          assigneeRoles: roles,
          client,
        });
      }
    } else {
      // No rule matched — route for manual approval
      await startWorkflow({
        companyId,
        entityType: 'VENDOR',
        entityId: vendorId,
        workflowType: 'VENDOR_ONBOARDING',
        assigneeRoles: ['PROCUREMENT_HEAD'],
        client,
      });
    }

    await logAuditEvent({
      companyId,
      actorUserId: userId,
      actorType: 'USER',
      actionCode: 'VENDOR_ONBOARDING_SUBMITTED',
      entityType: 'VENDOR',
      entityId: vendorId,
      payload: { context, ruleResult: ruleResult.finalOutcome, finalStatus },
      client,
    });

    await client.query('COMMIT');

    return { vendorId, status: finalStatus, ruleOutcome: ruleResult.finalOutcome, context };
  } catch (err) {
    await client.query('ROLLBACK');
    throw err;
  } finally {
    client.release();
  }
}

export async function addDocument(
  companyId: string,
  userId: string,
  vendorId: string,
  documentType: string,
  documentRef: string,
  issueDate?: string,
  expiryDate?: string,
) {
  const client = await pool.connect();
  try {
    await client.query('BEGIN');

    // Verify vendor belongs to company
    const vendorRes = await client.query(
      `SELECT vendor_id FROM vendor WHERE vendor_id = $1 AND company_id = $2`,
      [vendorId, companyId],
    );
    if (vendorRes.rows.length === 0) throw new AppError(404, 'NOT_FOUND', 'Vendor not found');

    const result = await client.query(
      `INSERT INTO vendor_document (vendor_id, document_type, document_ref, issue_date, expiry_date, status)
       VALUES ($1, $2, $3, $4, $5, 'VALID')
       ON CONFLICT (vendor_id, document_type, document_ref) DO UPDATE SET status = 'VALID', uploaded_at = NOW()
       RETURNING *`,
      [vendorId, documentType, documentRef, issueDate || null, expiryDate || null],
    );

    await logAuditEvent({
      companyId,
      actorUserId: userId,
      actorType: 'USER',
      actionCode: 'VENDOR_DOCUMENT_ADDED',
      entityType: 'VENDOR',
      entityId: vendorId,
      payload: { documentType, documentRef },
      client,
    });

    await client.query('COMMIT');
    return result.rows[0];
  } catch (err) {
    await client.query('ROLLBACK');
    throw err;
  } finally {
    client.release();
  }
}
