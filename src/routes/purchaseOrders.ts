import { Router, Request, Response } from 'express';
import { requireFields, requireUuid } from '../middleware/validate';
import * as purchaseOrderService from '../services/purchaseOrderService';

const router = Router();

// POST /api/purchase-orders
router.post(
  '/',
  requireFields(['vendorId', 'currency', 'lines']),
  async (req: Request, res: Response, next) => {
    try {
      const result = await purchaseOrderService.createPO({
        companyId: req.user!.companyId,
        userId: req.user!.userId,
        vendorId: req.body.vendorId,
        requisitionId: req.body.requisitionId,
        currency: req.body.currency,
        expectedDeliveryDate: req.body.expectedDeliveryDate,
        paymentTermsDays: req.body.paymentTermsDays,
        lines: req.body.lines,
      });
      res.status(201).json(result);
    } catch (err) {
      next(err);
    }
  },
);

// POST /api/purchase-orders/:id/issue
router.post('/:id/issue', requireUuid('id'), async (req: Request, res: Response, next) => {
  try {
    const result = await purchaseOrderService.issuePO(req.user!.companyId, req.user!.userId, req.params.id);
    res.json(result);
  } catch (err) {
    next(err);
  }
});

export default router;
