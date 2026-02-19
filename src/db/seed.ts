import { pool } from './pool';

async function seed() {
  const client = await pool.connect();
  try {
    await client.query('BEGIN');

    // Company
    const companyRes = await client.query(`
      INSERT INTO company (company_code, company_name, timezone, base_currency)
      VALUES ('ACME', 'Acme Corporation', 'America/New_York', 'USD')
      ON CONFLICT (company_code) DO UPDATE SET company_name = EXCLUDED.company_name
      RETURNING company_id
    `);
    const companyId = companyRes.rows[0].company_id;

    // Org unit
    const ouRes = await client.query(`
      INSERT INTO org_unit (company_id, unit_code, unit_name)
      VALUES ($1, 'HQ', 'Headquarters')
      ON CONFLICT (company_id, unit_code) DO UPDATE SET unit_name = EXCLUDED.unit_name
      RETURNING org_unit_id
    `, [companyId]);
    const orgUnitId = ouRes.rows[0].org_unit_id;

    // Cost center
    const ccRes = await client.query(`
      INSERT INTO cost_center (company_id, org_unit_id, center_code, center_name)
      VALUES ($1, $2, 'IT-001', 'Information Technology')
      ON CONFLICT (company_id, center_code) DO UPDATE SET center_name = EXCLUDED.center_name
      RETURNING cost_center_id
    `, [companyId, orgUnitId]);
    const costCenterId = ccRes.rows[0].cost_center_id;

    // Spend categories
    const catRes = await client.query(`
      INSERT INTO spend_category (company_id, category_code, category_name, risk_level)
      VALUES
        ($1, 'IT_HW', 'IT Hardware', 'HIGH'),
        ($1, 'IT_SW', 'IT Software', 'MEDIUM'),
        ($1, 'OFFICE', 'Office Supplies', 'LOW'),
        ($1, 'CONSULT', 'Consulting Services', 'HIGH')
      ON CONFLICT (company_id, category_code) DO UPDATE SET category_name = EXCLUDED.category_name
      RETURNING category_id, category_code
    `, [companyId]);
    const categories: Record<string, string> = {};
    for (const row of catRes.rows) {
      categories[row.category_code] = row.category_id;
    }

    // Users
    const users = [
      { code: 'U001', name: 'Alice Johnson', email: 'alice@acme.com', role: 'REQUESTER' },
      { code: 'U002', name: 'Bob Smith', email: 'bob@acme.com', role: 'FINANCE_CONTROLLER' },
      { code: 'U003', name: 'Carol White', email: 'carol@acme.com', role: 'PROCUREMENT_HEAD' },
      { code: 'U004', name: 'Dave Brown', email: 'dave@acme.com', role: 'COST_CENTER_MANAGER' },
      { code: 'U005', name: 'Eve Davis', email: 'eve@acme.com', role: 'AP_MANAGER' },
    ];
    for (const u of users) {
      await client.query(`
        INSERT INTO app_user (company_id, org_unit_id, cost_center_id, employee_no, full_name, email, role_code)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT (company_id, email) DO NOTHING
      `, [companyId, orgUnitId, costCenterId, u.code, u.name, u.email, u.role]);
    }

    // Vendors
    const vendors = [
      { code: 'VEN-001', name: 'TechSupplies Inc.', taxId: 'TX-123456', status: 'ACTIVE', risk: 85 },
      { code: 'VEN-002', name: 'Office World Ltd.', taxId: 'TX-789012', status: 'APPROVED', risk: 75 },
      { code: 'VEN-003', name: 'CloudSoft Corp.', taxId: 'TX-345678', status: 'UNDER_REVIEW', risk: 65 },
      { code: 'VEN-004', name: 'Risky Supplies Co.', taxId: 'TX-999999', status: 'BLOCKED', risk: 40 },
    ];
    for (const v of vendors) {
      await client.query(`
        INSERT INTO vendor (company_id, vendor_code, legal_name, tax_id, status, risk_score, payment_terms_days)
        VALUES ($1, $2, $3, $4, $5, $6, 30)
        ON CONFLICT (company_id, vendor_code) DO UPDATE SET status = EXCLUDED.status, risk_score = EXCLUDED.risk_score
      `, [companyId, v.code, v.name, v.taxId, v.status, v.risk]);
    }

    // Budget
    const budgetRes = await client.query(`
      INSERT INTO budget (company_id, budget_name, fiscal_year, period_type, version_no, status, currency, valid_from, valid_to)
      VALUES ($1, 'FY2026 Annual Budget', 2026, 'ANNUAL', 1, 'ACTIVE', 'USD', '2026-01-01', '2026-12-31')
      ON CONFLICT (company_id, fiscal_year, period_type, version_no) DO UPDATE SET status = EXCLUDED.status
      RETURNING budget_id
    `, [companyId]);
    const budgetId = budgetRes.rows[0].budget_id;

    // Budget lines — one per category for the IT cost center
    const budgetLines = [
      { categoryCode: 'IT_HW', allocated: 500000 },
      { categoryCode: 'IT_SW', allocated: 300000 },
      { categoryCode: 'OFFICE', allocated: 100000 },
      { categoryCode: 'CONSULT', allocated: 200000 },
    ];
    for (const bl of budgetLines) {
      const catId = categories[bl.categoryCode];
      if (!catId) continue;
      await client.query(`
        INSERT INTO budget_line (budget_id, cost_center_id, category_id, allocated_amount)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (budget_id, cost_center_id, category_id, project_code)
        DO UPDATE SET allocated_amount = EXCLUDED.allocated_amount
      `, [budgetId, costCenterId, catId, bl.allocated]);
    }

    // Policy rules — from workflow_rules_template_v1.yaml
    const policyRules = [
      {
        ruleCode: 'VENDOR_AUTO_APPROVE_LOW_RISK',
        scope: 'VENDOR',
        priority: 10,
        expression: { whenAll: ['riskScore >= 80', 'countMissingDocuments == 0', 'sanctionsHit == false', 'bankAccountVerified == true'] },
        outcome: { action: 'AUTO_APPROVE', finalStatus: 'APPROVED' },
      },
      {
        ruleCode: 'VENDOR_MANUAL_REVIEW_MEDIUM_RISK',
        scope: 'VENDOR',
        priority: 20,
        expression: { whenAll: ['riskScore >= 60', 'riskScore < 80'] },
        outcome: { action: 'ROUTE_APPROVAL', routeToRoles: ['COMPLIANCE_OFFICER', 'PROCUREMENT_HEAD'] },
      },
      {
        ruleCode: 'VENDOR_AUTO_REJECT_HIGH_RISK',
        scope: 'VENDOR',
        priority: 30,
        expression: { whenAny: ['riskScore < 60', 'sanctionsHit == true'] },
        outcome: { action: 'AUTO_REJECT', rejectReasonCode: 'RISK_POLICY_FAILED' },
      },
      {
        ruleCode: 'PO_AUTO_APPROVE_LOW_VALUE',
        scope: 'REQUISITION',
        priority: 10,
        expression: { whenAll: ['totalAmount <= 2000', 'budgetAvailable == true', "vendorStatus in ['APPROVED','ACTIVE']", 'vendorRiskScore >= 80'] },
        outcome: { action: 'AUTO_APPROVE' },
      },
      {
        ruleCode: 'PO_REJECT_NO_BUDGET',
        scope: 'REQUISITION',
        priority: 20,
        expression: { whenAll: ['budgetAvailable == false', "budgetControlMode == 'HARD_STOP'"] },
        outcome: { action: 'AUTO_REJECT', rejectReasonCode: 'BUDGET_EXCEEDED' },
      },
      {
        ruleCode: 'INVOICE_AUTO_POST',
        scope: 'INVOICE',
        priority: 10,
        expression: { whenAll: ['duplicateInvoiceFound == false', 'matchPassed == true', 'priceVariancePercent <= priceTolerancePercent', 'qtyVariancePercent <= quantityTolerancePercent'] },
        outcome: { action: 'AUTO_APPROVE_FOR_PAYMENT' },
      },
      {
        ruleCode: 'INVOICE_EXCEPTION_QUEUE',
        scope: 'INVOICE',
        priority: 20,
        expression: { whenAny: ['matchPassed == false', 'priceVariancePercent > priceTolerancePercent', 'qtyVariancePercent > quantityTolerancePercent'] },
        outcome: { action: 'ROUTE_EXCEPTION', routeToRoles: ['AP_MANAGER', 'BUYER'] },
      },
      {
        ruleCode: 'INVOICE_REJECT_DUPLICATE',
        scope: 'INVOICE',
        priority: 30,
        expression: { whenAll: ['duplicateInvoiceFound == true'] },
        outcome: { action: 'AUTO_REJECT', rejectReasonCode: 'DUPLICATE_INVOICE' },
      },
    ];

    for (const rule of policyRules) {
      await client.query(`
        INSERT INTO policy_rule (company_id, rule_code, scope, priority, is_active, expression_json, outcome_json)
        VALUES ($1, $2, $3, $4, TRUE, $5, $6)
        ON CONFLICT (company_id, rule_code) DO UPDATE SET
          expression_json = EXCLUDED.expression_json,
          outcome_json = EXCLUDED.outcome_json,
          priority = EXCLUDED.priority
      `, [companyId, rule.ruleCode, rule.scope, rule.priority, JSON.stringify(rule.expression), JSON.stringify(rule.outcome)]);
    }

    await client.query('COMMIT');
    console.log('Demo data seeded successfully (with budget lines + policy rules).');
  } catch (err) {
    await client.query('ROLLBACK');
    console.error('Seed error:', err);
    process.exit(1);
  } finally {
    client.release();
    await pool.end();
  }
}

seed();
