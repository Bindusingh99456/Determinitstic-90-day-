import express from 'express';
import path from 'path';
import { createServer as createViteServer } from 'vite';
import { evaluateDecision } from './server/engine/decisionEngine.js';
import { PurchaseRequest, FinancialEvent } from './server/engine/types.js';
import { globalGeminiService } from './server/ai/geminiService.js';

const decisionHistory: Map<string, any> = new Map();
let requestCounter = 1;

async function startServer() {
  const app = express();
  const PORT = 3000;

  app.use(express.json());

  // CORS headers
  app.use((req, res, next) => {
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS, PUT, DELETE');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');
    if (req.method === 'OPTIONS') {
      return res.sendStatus(200);
    }
    next();
  });

  // Health check endpoint
  app.get(['/health', '/api/health'], (req, res) => {
    res.json({
      status: 'ok',
      service: 'Deterministic 90-Day Financial Decision Engine',
      timestamp: new Date().toISOString(),
    });
  });

  // GET /api/ai/usage - AI Optimization & Token Telemetry Endpoint
  app.get('/api/ai/usage', (req, res) => {
    res.json(globalGeminiService.getUsageSummary());
  });

  // POST /api/decision
  app.post('/api/decision', (req, res) => {
    try {
      const { product, item_name, amount, full_price, desired_date, offer_expires_at, request_id } = req.body || {};

      const prodName = product || item_name || 'Requested Product';
      const price = amount !== undefined ? Number(amount) : (full_price !== undefined ? Number(full_price) : 0);
      const targetDate = desired_date || offer_expires_at || '2026-09-30';

      if (isNaN(price) || price < 0) {
        return res.status(400).json({
          error: {
            code: 'INVALID_REQUEST',
            message: 'Purchase amount must be a non-negative number.',
          },
        });
      }

      const reqId = request_id || `R${String(requestCounter++).padStart(3, '0')}`;

      const internalReq: PurchaseRequest = {
        request_id: reqId,
        user_id: 'U1',
        item_name: prodName,
        full_price: price,
        desired_date: targetDate,
      };

      // Execute deterministic decision engine
      const decision = evaluateDecision(
        internalReq,
        50000.0,
        [],
        undefined,
        '2026-09-12',
        1000.0
      );

      decisionHistory.set(reqId, decision);

      return res.json(decision);
    } catch (error) {
      console.error('Error evaluating decision:', error);
      return res.status(500).json({
        error: {
          code: 'DECISION_UNAVAILABLE',
          message: 'We could not safely evaluate this request.',
        },
      });
    }
  });

  // GET /api/requests
  app.get('/api/requests', (req, res) => {
    const list = Array.from(decisionHistory.values());
    res.json(list);
  });

  // GET /api/requests/:request_id
  app.get('/api/requests/:request_id', (req, res) => {
    const reqId = req.params.request_id;
    const decision = decisionHistory.get(reqId);
    if (!decision) {
      return res.status(404).json({
        error: {
          code: 'NOT_FOUND',
          message: `Request decision for ID '${reqId}' not found.`,
        },
      });
    }
    res.json(decision);
  });

  // Vite middleware setup
  if (process.env.NODE_ENV !== 'production') {
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: 'spa',
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(process.cwd(), 'dist');
    app.use(express.static(distPath));
    app.get('*', (req, res) => {
      res.sendFile(path.join(distPath, 'index.html'));
    });
  }

  app.listen(PORT, '0.0.0.0', () => {
    console.log(`Server running on http://0.0.0.0:${PORT}`);
  });
}

startServer();
