import { Router, Request, Response } from 'express';
import { requireFields, requireUuid } from '../middleware/validate';
import * as requisitionService from '../services/requisitionService';

const router = Router();

// POST /api/requisitions
router.post(
  '/',
  requireFields(['costCenterId', 'currency', 'lines']),
  async (req: Request, res: Response, next) => {
    try {
      const result = await requisitionService.createRequisition({
        companyId: req.user!.companyId,
        userId: req.user!.userId,
        costCenterId: req.body.costCenterId,
        currency: req.body.currency,
        neededByDate: req.body.neededByDate,
        justification: req.body.justification,
        lines: req.body.lines,
      });
      res.status(201).json(result);
    } catch (err) {
      next(err);
    }
  },
);

// POST /api/requisitions/:id/submit
router.post('/:id/submit', requireUuid('id'), async (req: Request, res: Response, next) => {
  try {
    const result = await requisitionService.submitRequisition(req.user!.companyId, req.user!.userId, req.params.id);
    res.json(result);
  } catch (err) {
    next(err);
  }
});

export default router;
