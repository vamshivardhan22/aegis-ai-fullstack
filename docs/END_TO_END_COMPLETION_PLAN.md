# Aegis DataOps — End-to-End Completion Plan

## Outcome
Deliver one verifiable, governed data workflow before expanding the platform: CSV orders → validation/profile → PII policy and masking → deterministic transformation → quality gate → approval when required → publish versioned output → lineage/audit → recoverable run status.

This preserves the React + FastAPI product and zero-license-cost intent. Third-party free tiers do not guarantee uptime, capacity, or permanent free pricing.

## Confirmed direction
- Product: Aegis DataOps, an AI-governed autonomous data engineering platform.
- UI: React/Vite; API/control plane: FastAPI.
- Workflow orchestration: LangGraph; LLM integration: LangChain provider adapters.
- Metadata: SQLAlchemy/PostgreSQL; Supabase PostgreSQL is the preferred hosted option. Use storage adapters/Supabase Storage for artifacts where appropriate.
- Keep Qdrant, Redis, and MLflow only where they have real end-to-end value. Optional integrations must fail visibly rather than pretending to be durable.
- Governance: RBAC, project isolation, PII handling, approvals, lineage, audit, retries, and monitoring.
- Work in the existing repository on a feature branch/PR; do not replace it with an unrelated chatbot.

## Architecture boundary
**LLM = planner/explainer, not executor or authority.** The LLM may propose a constrained JSON plan. The application validates schema, permissions, policy, and data contract; deterministic code executes allow-listed operations. Never execute LLM-generated Python, SQL, or shell directly.

A run should move through explicit states: queued → validating → awaiting_approval (if required) → running → quality_check → published, with failed, rejected, and cancelled terminal states. Every transition must be authorized, persisted, idempotent, and auditable.

## Phased implementation and exit gates

### Phase 0 — Reproducible baseline (P0)
- Pin supported Python/Node versions and dependencies; provide .env.example with safe placeholders only.
- Verify local Docker Compose boot, migrations, health/readiness, frontend build, lint/type checks, and tests from a clean checkout.
- Document commands and environment requirements.
- **Exit:** a new developer can start from README; CI actually runs tests rather than only validating manifests.

### Phase 1 — Security and tenancy (P0)
- Enforce user → project → dataset/pipeline/artifact authorization in every read/write route; deny by default.
- Add tests for cross-user and cross-project IDOR attempts.
- Fail startup in production for missing/default JWT secrets, debug mode, insecure CORS, or ephemeral persistence.
- Replace unsafe generated-code execution with declarative allow-listed operations (implementation started in this change set).
- Apply upload size/type limits, path normalization, rate limits, safe errors, and secret redaction.
- **Exit:** negative authorization tests pass; no agent can bypass project scoping.

### Phase 2 — Real data engine (P0)
- Implement CSV ingestion first, with bounded size, encoding/error handling, stable dataset/run IDs, source checksums, and immutable Bronze artifacts.
- Profile schema, inferred types, null rates, duplicate keys, row counts, and freshness.
- Validate explicit contracts before transformation; capture rejected-row reasons separately.
- Execute deterministic Silver transformations through a validated plan; enforce quality assertions before publication.
- Publish only verified artifacts; store row counts, schema, checksum, and artifact version.
- **Exit:** real inputs produce inspectable outputs and a machine-readable run report; invalid inputs cannot be marked successful.

### Phase 3 — Governance and approval (P0)
- PII detection must cover the full dataset or documented deterministic sampling, and report coverage/confidence.
- Mask/tokenize configured sensitive fields in output, not just recommend a strategy. Fail closed when policy requires masking and masking fails.
- Evaluate policy before execution and again before publish.
- Persist approval request, approver, decision, reason, timestamps, and exact run/artifact version approved.
- **Exit:** approval/rejection/resume works after API process restart; no unapproved high-risk output can publish.

### Phase 4 — Durable orchestration and observability (P1)
- Use LangGraph state/checkpointing for the canonical workflow; persist run state and step results in PostgreSQL.
- Add bounded retries with exponential backoff only for retryable failures; idempotency keys; timeouts; cancellation; failed-run inspection.
- Redis may support queues/locks but must not be the only source of truth. Qdrant is for retrieval, not canonical audit/metadata. MLflow is for experiments, not workflow state.
- Emit structured logs and metrics for step duration, records read/written/rejected, retries, failures, and approvals.
- **Exit:** worker restart does not duplicate publication or lose approval/audit state.

### Phase 5 — API/UI contract (P1)
- UI displays real persisted run state, step progress, validation errors, approval actions, output artifacts, lineage, and audit history.
- Replace placeholder/compatibility success paths with actual work or clearly label them as not implemented; never report a smoke stub as a completed data operation.
- Scope chat history to user/project and persist it if history is part of the product promise. Database answers must be authorization-filtered and grounded in returned records.
- **Exit:** UI status agrees with persisted backend state; users can trace a run from input to output.

### Phase 6 — Release evidence (P0 before production claims)
- Unit tests: transformations, schema/contracts, masking, policy decisions, state transitions.
- Integration tests: Postgres migrations, storage adapter, LLM timeout/invalid response, checkpoint recovery, approval resume.
- Security tests: cross-project reads, role escalation, malicious plan, oversized upload, unsafe path, secret leakage.
- Data tests: duplicates, null-heavy columns, invalid numeric/date values, empty files, encoding issues, schema drift, very wide files, PII outside initial rows.
- Resilience/load tests: concurrent users/runs, database/storage outage, worker restart, repeated request idempotency.
- Publish measured limits: tested file size, concurrency, latency, memory, and recovery. Do not advertise accuracy percentages until measured on a labeled representative test set.
- **Exit:** release-blocking tests pass in CI and results are reproducible.

## Recommended order of work
1. Remove arbitrary code execution and test safe transformation plans.
2. Close authorization gaps across datasets, pipelines, lineage, storage, and chat.
3. Implement one real CSV workflow with validation, PII masking, quality gates, and versioned output.
4. Wire that workflow through one durable LangGraph state machine and persisted approvals.
5. Connect UI to real run state and artifact/lineage views.
6. Add outage/restart/security/load testing; only then broaden agent coverage.

## Acceptance scenario
Use an e-commerce orders CSV with order_id, customer_email, category, amount, and created_at.

1. Upload creates an immutable Bronze artifact and scoped dataset record.
2. Profile reports schema, nulls, duplicates, row count, and checksum.
3. Policy flags email as PII and requires masking before publication.
4. An allow-listed plan casts amount, rejects invalid amounts, removes duplicate order IDs according to explicit policy, and aggregates only when requested.
5. A quality gate blocks publication if required columns are missing or rejection thresholds are exceeded.
6. A high-risk run pauses for an authorized human; rejection blocks publish, and approval is persisted against the exact run version.
7. Published output has masked PII, schema, checksum, row counts, run ID, lineage edge, and audit events.
8. Restart during approval/execution resumes without duplicate publication.
9. A different project user cannot fetch input, output, lineage, or logs by guessing IDs.

## Explicit unresolved decisions
- Maximum upload size and supported formats beyond CSV.
- Dataset-level row/column quality thresholds and duplicate-key policy.
- PII policy by field type, masking method, reversibility, and retention period.
- Approval matrix by role, operation, and data sensitivity.
- Hosting limits and where background workers run within the zero-license-cost budget.
- Whether chat history is a required persisted feature.
- Required SLOs and benchmark dataset for accuracy/performance claims.

These decisions should remain configurable and block production release until owners decide them.
