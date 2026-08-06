# API

Aegis AI exposes a FastAPI control plane. Interactive OpenAPI documentation is available at `/docs`, and Redoc is available at `/redoc` when the application is running. The API is JSON-first, with multipart upload support for dataset files. Most endpoints are protected by OAuth2 bearer authentication. `/health` remains unauthenticated so Docker, Kubernetes, load balancers, and uptime monitors can check the service without credentials.

## Authentication

Register a user:

```bash
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"SecurePass123","role":"admin"}'
```

Log in:

```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin@example.com&password=SecurePass123"
```

Use the returned token:

```bash
curl http://localhost:8000/auth/me \
  -H "Authorization: Bearer TOKEN"
```

Unauthorized responses use `{"detail":"...","code":"UNAUTHORIZED"}`. Forbidden responses use `{"detail":"...","code":"FORBIDDEN"}`. Tokens expire according to `AEGIS_ACCESS_TOKEN_EXPIRE_MINUTES`, and `/auth/refresh` issues a new token when the current token is still valid.

## Dataset Endpoints

`POST /datasets/` creates dataset metadata and can store CSV content. It requires the admin or data engineer role. Example:

```json
{
  "name": "orders",
  "source_type": "csv",
  "content": "id,email,amount\n1,a@example.com,10\n"
}
```

The response includes dataset ID, project ID, name, and bronze path. `POST /datasets/upload` accepts multipart files for larger CSV data. `GET /datasets/{dataset_id}` returns metadata for authenticated users.

## Agent Endpoints

`GET /agents/` lists available agents. `GET /agents/{agent_type}/status` returns availability. `POST /agents/{agent_type}/execute` runs an agent and requires admin or data engineer privileges. Supported agent types include ingestion, schema, cleaning, features, ml, explain, deploy, monitor, drift, transform, rag-related direct use through chat, and pii. Example PII scan:

```json
{
  "dataset_id": "dataset-id",
  "data_sample_path": "bronze/project/orders.csv"
}
```

The PII response includes whether PII was detected, the number of flagged columns, a report path, and masking recommendations. Agent decisions are written to audit logs.

## Approval and Chat

`GET /approvals/pending` lists paused pipelines. `POST /approvals/{pipeline_id}/approve` resumes a checkpointed pipeline with rationale. `POST /approvals/{pipeline_id}/reject` fails or reroutes it. Approval writes a human decision audit log and ingests the decision into the knowledge base.

`POST /chat/ask` accepts `{"question":"...","project_id":"optional"}`. The chat router first answers direct factual questions from the database, such as dataset quality, then falls back to the RAG knowledge agent. The response contains answer, sources, and confidence. `GET /chat/history` returns recent interactions.

## Admin, Lineage, and Health

Admin endpoints require the admin role. `/admin/users` lists users, `/admin/users/{id}/role` changes role, `/admin/users/{id}` deactivates users, and `/admin/audit-logs` filters audit records.

Lineage endpoints require authentication. `/lineage/datasets/{dataset_id}` returns upstream and downstream recursive graph data. `/lineage/pipelines/{pipeline_id}` returns lineage for the pipeline dataset. `/lineage/impact/{dataset_id}` returns downstream datasets, models, and deployments affected by a change. `/lineage/record` creates lineage edges and requires admin or data engineer.

`GET /health` returns service health and dependency checks. The health shape is stable: status, version, and checks. It is suitable for Kubernetes liveness and readiness probes.

## Client Behavior

Production clients should use idempotent names or external request identifiers when repeatedly creating datasets from automation. Dataset upload responses include stable IDs that should be stored by the caller and reused for downstream agent, lineage, and chat requests. Agent execution responses are intentionally plain JSON, so workflow systems can inspect result keys without parsing logs. Long-running production agents can later be moved behind queues while keeping the same request and response contracts.

For browser or CLI applications, the recommended flow is: register or provision a user, log in, cache the bearer token until expiry, refresh before long workflows, upload data, execute the relevant agent, then query lineage or chat for human-readable interpretation. Administrative clients should page audit logs and export them to the organization’s security information and event management system. Monitoring clients should prefer `/health` for availability and Prometheus scraping for time-series behavior.
