import { Router, Request, Response } from 'express';
import { requireFields } from '../middleware/validate';
import * as receiptService from '../services/receiptService';

const router = Router();

// POST /api/receipts
router.post(
  '/',
  requireFields(['poId', 'receiptType', 'lines']),
  async (req: Request, res: Response, next) => {
    try {
      const result = await receiptService.createReceipt({
        companyId: req.user!.companyId,
        userId: req.user!.userId,
        poId: req.body.poId,
        receiptType: req.body.receiptType,
        lines: req.body.lines,
      });
      res.status(201).json(result);
    } catch (err) {
      next(err);
    }
  },
);

export default router;
