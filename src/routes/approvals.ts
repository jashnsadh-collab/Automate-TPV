import { Router, Request, Response } from 'express';
import { requireFields, requireUuid } from '../middleware/validate';
import * as approvalService from '../services/approvalService';

const router = Router();

// GET /api/approvals/tasks
router.get('/tasks', async (req: Request, res: Response, next) => {
  try {
    const tasks = await approvalService.listTasks(req.user!.companyId, {
      assigneeUserId: req.query.assigneeUserId as string,
      status: req.query.status as string,
    });
    res.json({ tasks });
  } catch (err) {
    next(err);
  }
});

// POST /api/approvals/tasks/:id/decision
router.post(
  '/tasks/:id/decision',
  requireUuid('id'),
  requireFields(['decision']),
  async (req: Request, res: Response, next) => {
    try {
      const result = await approvalService.decideTask(
        req.user!.companyId,
        req.user!.userId,
        req.params.id,
        req.body.decision,
        req.body.reason,
      );
      res.json(result);
    } catch (err) {
      next(err);
    }
  },
);

export default router;
