import { pool, query } from './pool';

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
    const itHwCatId = catRes.rows.find((r: any) => r.category_code === 'IT_HW')?.category_id;

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
    await client.query(`
      INSERT INTO budget (company_id, budget_name, fiscal_year, period_type, version_no, status, currency, valid_from, valid_to)
      VALUES ($1, 'FY2026 Annual Budget', 2026, 'ANNUAL', 1, 'ACTIVE', 'USD', '2026-01-01', '2026-12-31')
      ON CONFLICT (company_id, fiscal_year, period_type, version_no) DO UPDATE SET status = EXCLUDED.status
    `, [companyId]);

    await client.query('COMMIT');
    console.log('Demo data seeded successfully.');
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
