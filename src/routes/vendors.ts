import { Router, Request, Response } from 'express';
import { requireFields } from '../middleware/validate';
import { requireUuid } from '../middleware/validate';
import * as vendorService from '../services/vendorService';

const router = Router();

// POST /api/vendors
router.post('/', requireFields(['legalName']), async (req: Request, res: Response, next) => {
  try {
    const result = await vendorService.createVendor({
      companyId: req.user!.companyId,
      userId: req.user!.userId,
      legalName: req.body.legalName,
      displayName: req.body.displayName,
      taxId: req.body.taxId,
      paymentTermsDays: req.body.paymentTermsDays,
      preferredCurrency: req.body.preferredCurrency,
    });
    res.status(201).json(result);
  } catch (err) {
    next(err);
  }
});

// POST /api/vendors/:id/submit
router.post('/:id/submit', requireUuid('id'), async (req: Request, res: Response, next) => {
  try {
    const result = await vendorService.submitOnboarding(req.user!.companyId, req.user!.userId, req.params.id);
    res.json(result);
  } catch (err) {
    next(err);
  }
});

// POST /api/vendors/:id/documents
router.post(
  '/:id/documents',
  requireUuid('id'),
  requireFields(['documentType', 'documentRef']),
  async (req: Request, res: Response, next) => {
    try {
      const result = await vendorService.addDocument(
        req.user!.companyId,
        req.user!.userId,
        req.params.id,
        req.body.documentType,
        req.body.documentRef,
        req.body.issueDate,
        req.body.expiryDate,
      );
      res.status(201).json(result);
    } catch (err) {
      next(err);
    }
  },
);

export default router;
