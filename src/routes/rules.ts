import { Router, Request, Response } from 'express';
import { requireFields } from '../middleware/validate';
import { evaluateRules } from '../rules/engine';

const router = Router();

// POST /api/rules/evaluate
router.post('/evaluate', requireFields(['scope', 'context']), async (req: Request, res: Response, next) => {
  try {
    const result = await evaluateRules(req.user!.companyId, req.body.scope, req.body.context);
    res.json(result);
  } catch (err) {
    next(err);
  }
});

export default router;
