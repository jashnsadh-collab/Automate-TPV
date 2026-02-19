import { Router, Request, Response } from 'express';
import { requireUuid } from '../middleware/validate';
import * as budgetService from '../services/budgetService';

const router = Router();

// GET /api/budgets/:lineId/availability
router.get('/:lineId/availability', requireUuid('lineId'), async (req: Request, res: Response, next) => {
  try {
    const amount = parseFloat(req.query.amount as string) || 0;
    const result = await budgetService.checkAvailability(req.params.lineId, amount);
    res.json(result);
  } catch (err) {
    next(err);
  }
});

export default router;
