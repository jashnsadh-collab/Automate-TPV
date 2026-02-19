import { Router, Request, Response } from 'express';
import { requireFields, requireUuid } from '../middleware/validate';
import * as paymentService from '../services/paymentService';

const router = Router();

// POST /api/payments/batches
router.post(
  '/batches',
  requireFields(['invoiceIds', 'paymentMethod', 'currency']),
  async (req: Request, res: Response, next) => {
    try {
      const result = await paymentService.createBatch({
        companyId: req.user!.companyId,
        userId: req.user!.userId,
        invoiceIds: req.body.invoiceIds,
        paymentMethod: req.body.paymentMethod,
        currency: req.body.currency,
      });
      res.status(201).json(result);
    } catch (err) {
      next(err);
    }
  },
);

// POST /api/payments/batches/:id/approve
router.post('/batches/:id/approve', requireUuid('id'), async (req: Request, res: Response, next) => {
  try {
    const result = await paymentService.approveBatch(req.user!.companyId, req.user!.userId, req.params.id);
    res.json(result);
  } catch (err) {
    next(err);
  }
});

// POST /api/payments/batches/:id/execute
router.post('/batches/:id/execute', requireUuid('id'), async (req: Request, res: Response, next) => {
  try {
    const result = await paymentService.executeBatch(req.user!.companyId, req.user!.userId, req.params.id);
    res.json(result);
  } catch (err) {
    next(err);
  }
});

export default router;
