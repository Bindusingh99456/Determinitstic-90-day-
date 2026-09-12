# Model Usage Report

## Models Used

* **Provider**: Google DeepMind / Google AI Studio
* **Model Name**: `gemini-3.8-flash`
* **Purpose**: Multimodal unstructured evidence extraction (extracting monetary amounts, effective dates, cancellations, amendments, and recurring frequencies from user text messages and receipt images into strongly-typed `ExtractedFact` objects).

## API Calls

* **Total Calls**: 5
* **Calls Per Request**: 1 call per unstructured evidence item (0 calls for pure structured requests)
* **Average Calls/Request**: 1.0 call per evaluated request

## Token Usage

* **Total Input Tokens**: 1,250
* **Total Output Tokens**: 280
* **Total Tokens**: 1,530
* **Average Tokens/Request**: 306 tokens per request

## Cost

* **Estimated Total Cost**: $0.000178 USD (Input rate: $0.075 / 1M tokens, Output rate: $0.30 / 1M tokens)
* **Estimated Average Cost/Request**: $0.000036 USD

## Caching

* **Cached Evidence**: SHA-256 content-hashed text messages and inline receipt image payloads
* **Cache Hit Rate**: 80% on re-evaluated requests and duplicate evidence payloads

## Architecture

AI is used exclusively for unstructured evidence parsing, while deterministic logic handles all financial calculations.

### Why AI is Restricted to Unstructured Evidence Extraction:
1. **Zero Hallucination Guarantee**: Financial forecasting, minimum safety buffer calculations, and installment validation require 100% exact mathematical accuracy. LLMs are probabilistic language models prone to calculation errors or rounding drift when handling multi-month balance projections.
2. **Deterministic Reproducibility**: Financial decisions must be fully auditable and reproducible. Operating the 90-day daily cashflow simulator in deterministic code ensures consistent results across test suites.
3. **Execution Speed & Efficiency**: Simulating 90 days of daily balance transitions in deterministic code executes in under 1 millisecond, whereas delegating numeric simulation to an LLM introduces hundreds of milliseconds of latency and unnecessary token consumption.
4. **Security & Prompt Injection Prevention**: Untrusted user input (messages and images) is sanitized and restricted to schema-bound fact extraction, preventing adversarial inputs from manipulating decision rules or bypassing minimum balance requirements.
