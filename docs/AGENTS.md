# Agents

Aegis AI agents are asynchronous components that receive a JSON-compatible context and return a JSON-compatible result. All agents inherit from `BaseAgent`, which provides artifact storage and decision logging. The shared audit behavior is important: autonomous systems must explain what they did, why they did it, and how confident they were. Agent results can be returned through the API, composed by the orchestrator, or checked by verification scripts.

## Compatibility Stages

The ingestion, schema, cleaning, features, and ML compatibility agents provide stable production smoke stages. They mark the stage complete, log an audit decision, and return the relevant context keys and artifact identifiers. These stages are intentionally lightweight so load tests, E2E tests, and pipeline orchestration can exercise complete flows while deeper domain implementations are developed incrementally.

## ExplainAgent

The explainability agent loads a model artifact and sample CSV, calculates SHAP values when SHAP is installed and compatible, ranks the top features by mean absolute contribution, and asks the LLM for a business-readable explanation. If SHAP fails, it falls back to statistical feature variance so the pipeline still returns a useful explanation instead of crashing. Output includes the explanation artifact path, top features, SHAP shape, summary, and fallback indicator.

## DeployAgent

The deployment agent generates a FastAPI inference service for a trained model. It writes `main.py`, `Dockerfile`, and `requirements.txt` artifacts. The generated service loads model and encoder files, validates input with Pydantic, exposes `/health`, and exposes `/predict`. It supports classification confidence through `predict_proba` when available. The generated code is parsed for syntax before storage.

## MonitorAgent

The monitoring agent probes deployment health and prediction endpoints with httpx. It records latency and status-code metrics, creates alerts for health failures, prediction errors, and threshold breaches, and publishes Prometheus-compatible metrics. It catches unreachable endpoints and returns a controlled unhealthy result.

## DriftAgent

The drift agent compares baseline and current CSV batches. It calculates Population Stability Index from scratch for numerical columns and KL-style divergence for categorical columns. It summarizes affected features, severity, and recommendations, optionally using the LLM for a report. Reports are stored as JSON artifacts.

## TransformAgent

The transformation agent reads source CSV data, asks the LLM for pandas code, validates the code against dangerous constructs, executes it in a restricted namespace, stores the transformed CSV, creates a dataset record, and records lineage. If code generation or execution fails, it returns a safe failure without leaking tracebacks.

## RAGKnowledgeAgent

The RAG agent ingests platform knowledge and answers questions. In ingest mode it embeds content, stores it in Qdrant when available, and persists the document in PostgreSQL. In query mode it embeds the question, searches vector results, loads document text, and prompts the LLM for an answer. If Qdrant or Ollama is unavailable, deterministic local fallbacks preserve development and verification behavior.

## PIIDetectionAgent

The PII agent scans CSV samples with layered detection: column-name heuristics, regexes, spaCy when available, and LLM fallback when needed. It flags email, phone, SSN, credit card, IP address, date of birth, names, and addresses. It recommends masking strategies and stores a report without logging raw PII values. High-confidence PII creates an alert.

## Failure Modes

Storage failures become safe agent errors or failure dictionaries. LLM failures use deterministic fallbacks. Qdrant failures fall back to an in-memory vector store. Unsafe transformation code is rejected before execution. Monitoring endpoint failures create alerts. Human approval gates pause high-risk orchestration states. These behaviors are tested by verification and chaos drill files.
