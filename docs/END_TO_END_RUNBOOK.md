# Aegis DataOps End-to-End Runbook

## Purpose

This runbook documents the currently implemented CSV-first governed data path. It is a bounded vertical slice, not a claim that every connector, agent, deployment adapter, or compliance control is production complete.

## Implemented workflow

1. **Ingest:** create a dataset with CSV content or upload a CSV. The API stores the Bronze artifact and records schema, row/column counts, null counts, duplicate-row count, and SHA-256.
2. **Authorize:** dataset and artifact access is checked against the dataset's project. Cross-project lineage edges are rejected.
3. **Profile and validate:** the pipeline checks CSV parsing, duplicate headers, column count, configured required columns, and a configurable quality-score threshold.
4. **Govern:** deterministic PII heuristics inspect column names and sampled values. Detected fields are masked before a candidate output is written to staging. PII or explicit approval policy pauses the pipeline.
5. **Transform:** the workflow accepts only a declarative, allow-listed transformation plan. It does not execute Python supplied by a model.
6. **Approve or reject:** an authorized project user reviews the checkpoint. Approval resumes publication; rejection marks the run failed and does not publish the candidate.
7. **Publish:** staged bytes are verified against their expected size and checksum, copied to a project-scoped Silver artifact, and represented by a derived dataset.
8. **Audit and lineage:** stage checkpoints, approval decisions, publication status, source/output metadata, and a lineage edge are recorded.

## Start locally

1. Use Python 3.11 and install the dependencies:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. Set a unique development secret and the desired local storage path in your environment. Do not use development defaults for production.

   ```bash
   export AEGIS_ENV=development
   export AEGIS_SECRET_KEY='replace-with-a-long-random-development-secret'
   export AEGIS_DB_URL='sqlite+aiosqlite:///./aegis.db'
   export AEGIS_STORAGE_BACKEND=local
   export AEGIS_LOCAL_STORAGE_PATH=./data
   ```

3. Start the API:

   ```bash
   uvicorn src.api.main:app --reload
   ```

4. Open `/docs` on the local API host and register/log in to obtain a bearer token.

## API walkthrough

Use a bearer token with the `DATA_ENGINEER` or `ADMIN` role for write operations.

### Create a CSV dataset

```http
POST /datasets/
Authorization: Bearer <token>
Content-Type: application/json
```

```json
{
  "name": "orders-demo",
  "source_type": "csv",
  "content": "order_id,customer_email,amount\n1001,person@example.com,25.00\n1002,another@example.com,40.00"
}
```

Save the returned dataset `id`.

### Start the governed pipeline

```http
POST /pipelines/
Authorization: Bearer <token>
Content-Type: application/json
```

```json
{
  "dataset_id": "<dataset-id>",
  "name": "Orders governed run",
  "config": {
    "required_columns": ["order_id", "amount"],
    "minimum_quality_score": 0.6,
    "require_approval": false,
    "transformation_plan": {
      "operations": [
        {"op": "cast", "columns": {"amount": "float"}}
      ]
    }
  }
}
```

The example contains an email column, so PII detection should cause the pipeline to pause for human approval after masking the candidate output.

### Review and approve

- List pending approvals: `GET /approvals/pending`
- Inspect a checkpoint: `GET /approvals/{pipeline_id}`
- Approve a validated candidate: `POST /approvals/{pipeline_id}/approve`
- Reject a candidate: `POST /approvals/{pipeline_id}/reject`

Approval body:

```json
{
  "decision": "approve",
  "rationale": "Reviewed PII masking and quality report."
}
```

### Verify the result

- Inspect run state: `GET /pipelines/{pipeline_id}`
- Inspect output metadata: `GET /datasets/{output_dataset_id}`
- Inspect lineage: `GET /lineage/datasets/{source_dataset_id}`

Confirm the run is `COMPLETED`, the output is in the project's Silver layer, the lineage edge exists, the source checksum is present in the checkpoint, and any detected PII is masked in the output.

## Supported transformation operations

The transformation engine uses explicit, deterministic operations such as column selection, column removal, renaming, null filling, filtering, grouping/aggregation, and type casting. Unsupported operations, unknown columns, duplicate output names, malformed plans, and plans exceeding the step limit are rejected.

LLMs may propose a plan or explain results; they are not trusted to execute code or bypass policy gates.

## Production readiness gates still required

- Run the full CI suite and fix every failure; this repository change has not been independently runtime-verified from this session.
- Use PostgreSQL migrations for production; do not rely on SQLite table creation at application startup.
- Configure durable shared object storage and verify backup/restore and object retention.
- Configure Qdrant and the embedding provider; verify embedding dimension/model compatibility and tenant isolation.
- Set real CORS origins, a unique secret, production database/storage credentials, TLS, and rate limits appropriate to deployment.
- Add worker-backed asynchronous execution and distributed locks for large or concurrent pipelines; the current API execution path can hold a request open.
- Add stronger PII classification tests on representative domain data. Heuristics can miss sensitive fields or overclassify business fields.
- Add idempotency and crash-recovery tests around storage writes and database commits, including cleanup of abandoned staging objects.
- Verify project membership/role policy before supporting multi-user shared projects; the current access helper primarily models project ownership/admin access.
- Test data sizes and concurrency against a defined service-level objective. The 50 MiB and 500-column limits are protective bounds, not benchmark claims.
- Complete security review, dependency scanning, secrets management, observability, alerting, and a real staging deployment before claiming production readiness.
