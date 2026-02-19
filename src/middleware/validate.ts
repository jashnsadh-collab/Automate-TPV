import { Request, Response, NextFunction } from 'express';

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function requireFields(fields: string[]) {
  return (req: Request, res: Response, next: NextFunction): void => {
    const missing = fields.filter((f) => req.body[f] === undefined || req.body[f] === null);
    if (missing.length > 0) {
      res.status(400).json({
        error: { code: 'MISSING_FIELDS', message: `Missing required fields: ${missing.join(', ')}` },
      });
      return;
    }
    next();
  };
}

export function requireUuid(param: string) {
  return (req: Request, res: Response, next: NextFunction): void => {
    const value = req.params[param];
    if (!value || !UUID_RE.test(value)) {
      res.status(400).json({
        error: { code: 'INVALID_UUID', message: `Parameter '${param}' must be a valid UUID` },
      });
      return;
    }
    next();
  };
}
