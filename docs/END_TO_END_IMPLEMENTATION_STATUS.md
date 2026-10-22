# End-to-end implementation status

## Implemented in this branch

- Replaced the synthetic compatibility-agent response with real bounded CSV ingestion metadata, schema profiling, quality scoring, deterministic cleaning, allow-listed feature transformations, and baseline model evaluation.
- Cleaning and feature operations persist derived dataset metadata and a source-to-output lineage edge.
- Baseline ML training stores a serialized model artifact and creates a model registry record with evaluation metrics and training metadata.
- Standalone cleaning, feature engineering, transformation, and model-training routes fail closed when likely PII is present; those inputs must use the governed pipeline's masking and approval path.
- The governed CSV pipeline validates source size/schema/quality, hashes the source, masks likely PII, executes only declarative allow-listed transformations, stages output, pauses for approval when needed, verifies the staged output hash, promotes to a stable Silver key, and records lineage/audit metadata.
- Added row-level locking to reduce duplicate concurrent pipeline runs and concurrent approval decisions.
- Domain exceptions now map to their intended HTTP status codes in the agent API.
- E2E tests now assert PII masking, approval/publish behavior, real stage outputs, feature lineage, and baseline model registry persistence.

## Current workflow and boundaries

The supported end-to-end production slice is a CSV-to-Silver workflow. It is not yet a general-purpose autonomous data platform. The direct ML endpoint currently trains a baseline Random Forest model for tabular data; it is not an automated model-selection or production deployment system.

## Release gates still required

1. Run the full GitHub Actions checks and fix every failure; code changes from this branch have not been executed in this chat environment.
2. Verify PostgreSQL migrations on an empty database and on a copy of an existing database; do not rely on SQLite table creation for production schema changes.
3. Add a durable worker/queue and a reconciler for runs left in RUNNING after process termination. Row locks reduce duplicate starts but do not replace a job queue or recovery worker.
4. Add concurrency, retry, crash-recovery, large-file, malformed-CSV, schema-drift, and cross-project authorization tests.
5. Verify the deployed Supabase/MinIO storage lifecycle, private access controls, backups, retention, and artifact cleanup. Local storage is for development only.
6. Validate PII detection against representative labeled data and document false-positive/false-negative limits. Name and regex heuristics are not a compliance certification.
7. Persist chat history and scope vector retrieval by tenant/project at query time; the current chat history is process-local and the vector search performs visibility checks after retrieval.
8. Add deployment health checks, metrics, alerting, secrets rotation, dependency scanning, backup/restore drills, and a real staging deployment before production claims.
9. Review model-evaluation design for class imbalance, temporal leakage, feature leakage, fairness, and domain-specific acceptance criteria before using predictions for decisions.

## Verification commands

Run these in the repository's supported Python environment:

```bash
python -m ruff check src tests
python -m mypy src --no-error-summary
python scripts/verify_m5.py
python -m pytest tests/e2e -q
```

The code must not be called production-ready until these checks pass in CI and the operational release gates above have evidence.
