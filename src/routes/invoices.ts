import { Router, Request, Response } from 'express';
import { requireFields, requireUuid } from '../middleware/validate';
import * as invoiceService from '../services/invoiceService';

const router = Router();

// POST /api/invoices
router.post(
  '/',
  requireFields(['vendorId', 'invoiceNumber', 'invoiceDate', 'currency', 'amountSubtotal', 'amountTotal', 'lines']),
  async (req: Request, res: Response, next) => {
    try {
      const result = await invoiceService.createInvoice({
        companyId: req.user!.companyId,
        userId: req.user!.userId,
        vendorId: req.body.vendorId,
        poId: req.body.poId,
        invoiceNumber: req.body.invoiceNumber,
        invoiceDate: req.body.invoiceDate,
        dueDate: req.body.dueDate,
        currency: req.body.currency,
        amountSubtotal: req.body.amountSubtotal,
        amountTax: req.body.amountTax,
        amountTotal: req.body.amountTotal,
        sourceChannel: req.body.sourceChannel,
        lines: req.body.lines,
      });
      res.status(201).json(result);
    } catch (err) {
      next(err);
    }
  },
);

// POST /api/invoices/:id/match
router.post('/:id/match', requireUuid('id'), async (req: Request, res: Response, next) => {
  try {
    const result = await invoiceService.runMatch(req.user!.companyId, req.user!.userId, req.params.id);
    res.json(result);
  } catch (err) {
    next(err);
  }
});

export default router;
