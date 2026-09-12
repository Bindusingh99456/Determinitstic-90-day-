# Buy or Wait? — Production Backend Engine

Lead Backend Architecture for the HackerRank Orchestrate September 2026 Challenge.

## System Overview

The **Buy or Wait?** backend is a hybrid decision architecture:
1. **Unstructured AI Evidence Extraction (Gemini)**: Reads multimodal inputs (chat messages, image receipts, lease agreements, paystubs) to extract structured financial facts with confidence metrics.
2. **Deterministic 90-Day Simulation Engine**: Simulates daily cash balances over a 90-day horizon ($t = 1 \dots 90$), strictly enforcing liquidity safety buffers, debt-to-income (DTI) ceilings, and zero overdraft policies.

---

## Directory Structure

```
backend/
├── app/
│   ├── main.py                   # FastAPI Application Entrypoint
│   ├── config.py                 # Pydantic Settings & Environment Variables
│   ├── models/                   # Pydantic Schemas & Domain Entities
│   │   ├── financial.py          # Account Balances & Transaction Models
│   │   ├── requests.py           # Purchase Requests & Payment Option Models
│   │   ├── decision.py           # Evaluation & Recommendation Models
│   │   └── evidence.py           # Multimodal AI Fact Extraction Models
│   ├── routes/                   # FastAPI API Endpoints
│   │   ├── health.py             # Health check & status
│   │   ├── requests.py           # Purchase request management
│   │   └── decision.py           # Primary evaluation & dynamic simulation
│   ├── services/                 # Business & Orchestration Layer
│   │   ├── data_service.py       # Dataset ingestion & caching
│   │   ├── financial_state_service.py # Consolidated user financial profile
│   │   └── evidence_service.py   # Multi-source fact merger & conflict resolution
│   ├── engine/                   # Core Deterministic Engines
│   │   ├── forecast_engine.py    # 90-Day daily balance projection simulator
│   │   ├── affordability_engine.py # Safety buffer & DTI constraint verification
│   │   ├── payment_engine.py     # Payment plan & interest compounding math
│   │   ├── spending_optimizer.py # Cutback commitment analyzer
│   │   └── decision_engine.py    # Main decision tree orchestrator
│   ├── ai/                       # Multimodal Gemini Integration
│   │   ├── gemini_service.py     # SDK Client & Structured Outputs
│   │   ├── message_analyzer.py   # Chat text intent parser
│   │   └── image_analyzer.py     # OCR & image receipt analyzer
│   ├── data/                     # CSV Data Loader & Normalizer
│   │   └── loader.py             # Reusable forensic data loader
│   ├── validation/               # Output Compliance & Schema Auditing
│   │   └── output_validator.py   # Zero-hallucination verification
│   └── utils/                    # Helper Utilities
│       ├── logger.py             # Structured logging setup
│       └── date_helpers.py       # Calendar, payday shift, & date utilities
├── dataset/                      # Competition dataset location
├── evaluation/                   # Batch competition benchmark runner
│   └── evaluate.py               # Batch processor for output.csv generation
└── tests/                        # Unit & Integration Tests
```

---

## Running the Server

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

---

## Competition Dataset Batch Execution

```bash
python evaluation/evaluate.py --dataset-dir dataset/ --output output.csv
```
