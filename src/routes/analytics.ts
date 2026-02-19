import { Router, Request, Response } from 'express';
import { redshiftQuery } from '../db/redshift';
import {
  getSpendByCategory,
  getVendorPerformance,
  getPOStatusSummary,
  getInvoiceAging,
  getBudgetUtilization,
  getMonthlySpendTrend,
} from '../services/analyticsService';
import type { RedshiftResult } from '../db/redshift';

const router = Router();

type AnalyticsFn = (companyId: string) => Promise<RedshiftResult>;

function analyticsHandler(queryFn: AnalyticsFn) {
  return async (req: Request, res: Response) => {
    const companyId = req.query.companyId as string | undefined;

    if (!companyId) {
      return res.status(400).json({
        success: false,
        error: 'companyId query parameter is required',
      });
    }

    try {
      const result = await queryFn(companyId);
      return res.json({
        success: true,
        data: result.rows,
        meta: {
          columns: result.columns,
          totalRows: result.totalRows,
        },
      });
    } catch (err: any) {
      if (err.message?.includes('timed out')) {
        return res.status(504).json({ success: false, error: 'Query timed out' });
      }
      if (
        err.name === 'CredentialsProviderError' ||
        err.message?.includes('Could not load credentials')
      ) {
        return res.status(503).json({
          success: false,
          error: 'AWS credentials not configured',
        });
      }
      console.error('Analytics query error:', err);
      return res.status(500).json({ success: false, error: 'Internal server error' });
    }
  };
}

router.get('/spend-by-category', analyticsHandler(getSpendByCategory));
router.get('/vendor-performance', analyticsHandler(getVendorPerformance));
router.get('/po-status', analyticsHandler(getPOStatusSummary));
router.get('/invoice-aging', analyticsHandler(getInvoiceAging));
router.get('/budget-utilization', analyticsHandler(getBudgetUtilization));
router.get('/monthly-spend-trend', analyticsHandler(getMonthlySpendTrend));

router.get('/health', async (_req: Request, res: Response) => {
  try {
    await redshiftQuery('SELECT 1');
    return res.json({ success: true, message: 'Redshift connection healthy' });
  } catch (err: any) {
    console.error('Redshift health check failed:', err);
    return res.status(503).json({
      success: false,
      error: 'Redshift connection failed',
      detail: err.message,
    });
  }
});

export default router;
