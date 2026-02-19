import { redshiftQuery, RedshiftResult } from '../db/redshift';

export async function getSpendByCategory(companyId: string): Promise<RedshiftResult> {
  return redshiftQuery(`
    SELECT
      sc.category_code,
      sc.category_name,
      SUM(il.line_total) AS total_spend,
      COUNT(DISTINCT i.invoice_id) AS invoice_count
    FROM invoice_line il
    JOIN invoice i ON i.invoice_id = il.invoice_id
    JOIN purchase_order_line pol ON pol.po_line_id = il.po_line_id
    JOIN spend_category sc ON sc.category_id = pol.category_id
    WHERE i.company_id = '${companyId}'
    GROUP BY sc.category_code, sc.category_name
    ORDER BY total_spend DESC
  `);
}

export async function getVendorPerformance(companyId: string): Promise<RedshiftResult> {
  return redshiftQuery(`
    SELECT
      v.vendor_code,
      v.legal_name,
      v.status AS vendor_status,
      v.risk_score,
      COUNT(DISTINCT po.po_id) AS po_count,
      COALESCE(SUM(po.total_amount), 0) AS total_po_value,
      COUNT(DISTINCT i.invoice_id) AS invoice_count,
      COUNT(DISTINCT CASE WHEN i.status = 'PAID' THEN i.invoice_id END) AS paid_count,
      COUNT(DISTINCT CASE WHEN i.status = 'EXCEPTION' THEN i.invoice_id END) AS exception_count
    FROM vendor v
    LEFT JOIN purchase_order po ON po.vendor_id = v.vendor_id AND po.company_id = v.company_id
    LEFT JOIN invoice i ON i.vendor_id = v.vendor_id AND i.company_id = v.company_id
    WHERE v.company_id = '${companyId}'
    GROUP BY v.vendor_code, v.legal_name, v.status, v.risk_score
    ORDER BY total_po_value DESC
  `);
}

export async function getPOStatusSummary(companyId: string): Promise<RedshiftResult> {
  return redshiftQuery(`
    SELECT
      status,
      COUNT(*) AS po_count,
      COALESCE(SUM(total_amount), 0) AS total_value
    FROM purchase_order
    WHERE company_id = '${companyId}'
    GROUP BY status
    ORDER BY po_count DESC
  `);
}

export async function getInvoiceAging(companyId: string): Promise<RedshiftResult> {
  return redshiftQuery(`
    SELECT
      CASE
        WHEN CURRENT_DATE - due_date <= 30 THEN '0-30'
        WHEN CURRENT_DATE - due_date <= 60 THEN '31-60'
        WHEN CURRENT_DATE - due_date <= 90 THEN '61-90'
        ELSE '90+'
      END AS aging_bucket,
      COUNT(*) AS invoice_count,
      SUM(amount_total) AS total_amount
    FROM invoice
    WHERE company_id = '${companyId}'
      AND status NOT IN ('PAID', 'VOID')
      AND due_date IS NOT NULL
    GROUP BY aging_bucket
    ORDER BY aging_bucket
  `);
}

export async function getBudgetUtilization(companyId: string): Promise<RedshiftResult> {
  return redshiftQuery(`
    SELECT
      b.budget_name,
      b.fiscal_year,
      cc.center_code,
      cc.center_name,
      sc.category_code,
      sc.category_name,
      bl.allocated_amount,
      bl.committed_amount,
      bl.consumed_amount,
      bl.allocated_amount - bl.committed_amount - bl.consumed_amount AS available_amount,
      CASE
        WHEN bl.allocated_amount > 0
        THEN ROUND((bl.committed_amount + bl.consumed_amount) / bl.allocated_amount * 100, 2)
        ELSE 0
      END AS utilization_pct
    FROM budget_line bl
    JOIN budget b ON b.budget_id = bl.budget_id
    JOIN cost_center cc ON cc.cost_center_id = bl.cost_center_id
    JOIN spend_category sc ON sc.category_id = bl.category_id
    WHERE b.company_id = '${companyId}'
      AND b.status = 'ACTIVE'
    ORDER BY utilization_pct DESC
  `);
}

export async function getMonthlySpendTrend(companyId: string): Promise<RedshiftResult> {
  return redshiftQuery(`
    SELECT
      TO_CHAR(DATE_TRUNC('month', i.invoice_date), 'YYYY-MM') AS month,
      COUNT(*) AS invoice_count,
      SUM(i.amount_total) AS total_spend
    FROM invoice i
    WHERE i.company_id = '${companyId}'
      AND i.invoice_date >= DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '12 months'
    GROUP BY DATE_TRUNC('month', i.invoice_date)
    ORDER BY month
  `);
}
