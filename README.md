# Buy or Wait? — Production Financial Decision Engine

Production-grade financial decision intelligence and 90-day cashflow simulation platform built for the HackerRank Orchestrate Challenge.

---

## Architecture Overview

The system uses a hybrid architecture that cleanly separates AI perception from deterministic financial calculations:

1. **Multimodal Evidence Processing (Gemini API)**: Uses Google GenAI (`gemini-3.8-flash`) strictly to extract structured facts (`ExtractedFact`) from untrusted text messages and receipt images. Includes pre-filtering, response caching, prompt compression, and structured JSON schema enforcement.
2. **Deterministic 90-Day Forecast Engine**: Simulates daily cash balances across a 90-day horizon ($t = 0 \dots 90$). Enforces minimum safety buffers, recurring income/expenses, FX currency conversions, event deduplication/cancellations, and BNPL installment schedules.
3. **Dynamic Safe Amount Evaluator**: Calculates the exact maximum upfront liquid payment safe today using a binary search cashflow simulation to guarantee zero safety buffer violations.
4. **Spending Optimizer**: Evaluates non-essential spending reductions (e.g. `stop:EVT_SUB`) to make deferred purchases viable.

---

## Key Features & Compliance

- **Exact Output Compliance**: Directly generates `output.csv` with all 8 required competition columns:
  - `request_id`
  - `amount_safe_to_pay`
  - `affordability_status`
  - `recommended_payment_method`
  - `payment_plan`
  - `earliest_date_for_full_payment`
  - `spending_changes_needed`
  - `decision_explanation`
- **Stitch Frontend Compatibility**: API responses include both primary competition keys and Stitch UI fields (`decision`, `safe_amount`, `payment_method`, `earliest_date`, `spending_changes`, `explanation`, `financial_factors`, `forecast_summary`).
- **Security & Privacy**: Zero hardcoded secrets or API keys. Fully compliant with security sandboxing rules.

---

## Getting Started

### Prerequisites

- Node.js (v18+)
- Python (3.10+)

### Installation & Server Execution

```bash
# Install dependencies
npm install

# Build & launch production application server
npm run build
npm start
```

The server binds to `0.0.0.0:3000`.

---

## API Endpoints

- `GET /api/health` — Service health check and engine metadata.
- `POST /api/decision` — Evaluates purchase request affordability and returns full decision payload.
- `GET /api/requests` — Lists all evaluated purchase request decisions.
- `GET /api/requests/:request_id` — Retrieves decision details for a specific request ID.
- `GET /api/ai/usage` — Returns AI token consumption, call counts, and estimated cost metrics.

---

## Environment Variables

Defined in `.env.example`:

- `GEMINI_API_KEY`: API key for Gemini AI evidence extraction (automatically injected by AI Studio).
- `APP_URL`: Production hosting URL.
- `NODE_ENV`: Runtime environment (`development` or `production`).

---

## Evaluation & Test Suite Execution

Run the deterministic audit and test suite across edge cases (missing amounts, currency conversion, cancellations, recurring events, payment options, debt priority):

```bash
npx tsx server/engine/testAudit.ts
```

Run output CSV generator and compliance validator:

```bash
npx tsx server/engine/generateOutput.ts
```

---

## File Structure

```
├── evaluation/
│   └── usage_report.md        # AI model usage, token consumption, and cost breakdown
├── server/
│   ├── ai/
│   │   └── geminiService.ts    # Multimodal Gemini client & token usage tracker
│   └── engine/
│       ├── types.ts            # Domain entity definitions & extended Stitch schemas
│       ├── forecast.ts         # 90-Day daily balance forecast engine & event normalizer
│       ├── amountSafe.ts       # Binary search safe amount calculator
│       ├── spendingOptimizer.ts # Non-essential cutback analyzer
│       ├── explanation.ts      # Deterministic explanation generator
│       ├── decisionEngine.ts   # Core decision orchestrator
│       ├── generateOutput.ts   # Competition CSV generator & strict validator
│       └── testAudit.ts        # Comprehensive audit & regression test runner
├── backend/                    # Python FastAPI backend implementation
├── output.csv                  # Competition output file
├── server.ts                   # Express server entry point with REST endpoints
└── README.md                   # System documentation
```
