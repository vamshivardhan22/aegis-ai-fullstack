# Aegis DataOps implementation status

This file distinguishes code changes present on the upgrade branch from work that has been verified. **No production-readiness claim is made until CI, integration, security, and recovery tests pass.**

## Implemented in this branch

- Replaced arbitrary Python execution in `TransformAgent` with an allow-listed declarative transformation engine.
- Added project/dataset authorization helpers and applied them to dataset reads/writes, agent artifact access, lineage traversal/recording, chat facts, approval listing/actions, and pipeline access.
- Added bounded CSV upload, schema/type profiling, row/column/null/duplicate metrics, source checksum, safe dataset names, and a 10 MiB upload limit.
- Added a LangGraph CSV workflow with database-persisted stage checkpoints, schema/required-column validation, configurable quality threshold, sensitive-column detection/masking, validated transformations, staged artifact checksums, approval gating, derived dataset publication, audit events, and lineage.
- Added explicit approval/rejection state checks and prevented unsupported approval-time modifications from silently changing data.
- Switched `LLMClient` to configured LangChain OpenAI/Anthropic/Google integrations and OpenAI embeddings with a fixed 768-dimensional Qdrant vector.
- Made Qdrant and embedding failures fail closed in production instead of silently switching to ephemeral vectors.
- Added production configuration validation for default secrets, database, storage, provider credentials, and CORS.
- Fixed local storage path containment checks and added a PostgreSQL sync driver for Alembic.
- Added a baseline Alembic schema bootstrap migration.
- Connected pipeline, upload, and approval screens to API state instead of fabricated demo records.
- Added unit and end-to-end tests for transformation safety, CSV profile/masking, production configuration, project isolation, and pipeline approval/publication.

## Phase gates

| Phase | Current state | Remaining release blockers |
| --- | --- | --- |
| 0. Reproducible foundation | Partial | Run CI from a clean checkout; verify migrations on empty and existing PostgreSQL databases; validate Compose startup. |
| 1. Security and tenancy | Partial | Audit every route and storage/agent entry point; add broader IDOR/role-escalation tests; verify CORS, secrets, upload and path boundaries in deployment. |
| 2. Real data engine | First CSV vertical slice implemented | Add row-level reject reports, configurable duplicate-key policies, schema drift contracts, larger-file memory benchmarks, and more data-format adapters. |
| 3. Governance | Partial | Expand PII categories and validate against labeled data; define organization policy, retention, tokenization and masking rules; test that all publish paths enforce policy. |
| 4. Orchestration/recovery | Partial | Checkpoints persist in the pipeline record and approved publication can resume. Add a worker queue, cancellation, bounded retries, concurrency/idempotency tests, and automatic recovery after process restart. |
| 5. UI integration | Partial | Pipeline, upload, and approval flows are API-backed. Replace/verify remaining dashboard, agent, monitoring, and chat demo surfaces; persist chat history if promised. |
| 6. Release evidence | Not verified | Run Ruff, MyPy, unit tests, E2E/security tests, frontend build, migration tests, Docker build, and load/fault tests; record actual results. |

## First workflow acceptance contract

1. Upload a UTF-8 CSV within 10 MiB. The API stores a Bronze artifact and returns schema/profile/checksum metadata.
2. Start a pipeline. It validates required columns and a configurable quality threshold.
3. Detect likely PII, mask those fields, apply only allow-listed transformation operations, and store a staged artifact plus checksum.
4. If PII is detected or `require_approval` is enabled, persist `approval_required` and do not create the published output dataset yet.
5. An authorized approver approves or rejects. Approval verifies the staged checksum before creating a derived dataset and lineage edge; rejection leaves the output unpublished.
6. Pipeline status, checkpoint, audit record, and output metadata remain in the database.

## Verification note

The changes have been committed to `agies-v2-upgrade` and submitted in PR #1. The repository was edited through GitHub tools; this environment could not clone the repository or execute its test suite. Therefore tests listed above are **added, not confirmed passing**. Do not merge or deploy until GitHub Actions results are green and unresolved phase blockers are reviewed.
