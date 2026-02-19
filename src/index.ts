import express from 'express';
import cors from 'cors';
import dotenv from 'dotenv';
import analyticsRouter from './routes/analytics';
import vendorsRouter from './routes/vendors';
import requisitionsRouter from './routes/requisitions';
import purchaseOrdersRouter from './routes/purchaseOrders';
import receiptsRouter from './routes/receipts';
import invoicesRouter from './routes/invoices';
import paymentsRouter from './routes/payments';
import approvalsRouter from './routes/approvals';
import budgetsRouter from './routes/budgets';
import rulesRouter from './routes/rules';
import { authenticate } from './middleware/auth';
import { errorHandler } from './middleware/errorHandler';

dotenv.config();

const app = express();
const PORT = process.env.PORT || 4000;

app.use(cors({ origin: process.env.FRONTEND_URL || '*' }));
app.use(express.json());

// Public routes
app.use('/api/analytics', analyticsRouter);

app.get('/health', (_req, res) => {
  res.json({ status: 'ok', uptime: process.uptime() });
});

// Authenticated routes
app.use('/api/vendors', authenticate, vendorsRouter);
app.use('/api/requisitions', authenticate, requisitionsRouter);
app.use('/api/purchase-orders', authenticate, purchaseOrdersRouter);
app.use('/api/receipts', authenticate, receiptsRouter);
app.use('/api/invoices', authenticate, invoicesRouter);
app.use('/api/payments', authenticate, paymentsRouter);
app.use('/api/approvals', authenticate, approvalsRouter);
app.use('/api/budgets', authenticate, budgetsRouter);
app.use('/api/rules', authenticate, rulesRouter);

// Error handler (must be last)
app.use(errorHandler);

app.listen(PORT, () => {
  console.log(`Server running on port ${PORT}`);
});
