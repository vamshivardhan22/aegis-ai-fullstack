# Deployment

Aegis AI can run locally with Python, as a full Docker Compose stack, or as a Kubernetes deployment. Local Python is best for quick development and verification. Docker Compose is best for realistic integration because it includes PostgreSQL, Redis, MinIO, MLflow, Ollama, Prometheus, Grafana, Qdrant, Traefik, and the API. Kubernetes is best for production because it gives rolling deployment, probes, resource limits, horizontal autoscaling, secret management, ingress, and persistent volumes.

## Local Development

Create a virtual environment, install dependencies, and run verification:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python scripts/verify_m5.py
```

SQLite and local storage are used by default. This mode is intentionally self-contained. It exercises API routers, authentication, agent behavior, lineage, RAG fallback, PII detection, retention policies, and test assets without requiring external services.

## Docker Compose

Start the full stack:

```bash
cp .env.example .env
docker compose up --build
```

The API listens on port 8000. Traefik listens on ports 80 and 443. PostgreSQL is on 5432, Redis on 6379, MinIO on 9000/9001, MLflow on 5000, Ollama on 11434, Prometheus on 9090, Grafana on 3000, and Qdrant on 6333. The API container runs Alembic migrations at startup and then starts Uvicorn.

Useful checks:

```bash
curl http://localhost:8000/health
docker compose logs -f aegis-api
docker compose ps
```

## Kubernetes

The `k8s/` directory contains a base kustomization. Apply it with:

```bash
kubectl apply -k k8s/
kubectl -n aegis-ai get pods
```

Before production use, replace the secret template:

```bash
kubectl create secret generic aegis-secrets \
  --from-env-file=.env \
  -n aegis-ai \
  --dry-run=client -o yaml | kubectl apply -f -
```

The API deployment runs three replicas with CPU and memory requests and limits. Liveness and readiness probes target `/health`. The HPA scales from three to ten replicas at 70 percent CPU. PostgreSQL and MinIO use StatefulSets with persistent volume claims. Redis uses a Deployment. The ingress manifest uses the placeholder host `aegis.example.com` and expects a TLS secret named `aegis-tls`.

## Environment Variables

Important variables include `AEGIS_DB_URL`, `AEGIS_SECRET_KEY`, `AEGIS_STORAGE_BACKEND`, `AEGIS_MINIO_ENDPOINT`, MinIO credentials, `AEGIS_REDIS_URL`, `AEGIS_MLFLOW_TRACKING_URI`, `AEGIS_OLLAMA_URL`, `AEGIS_QDRANT_URL`, `AEGIS_LLM_MODEL`, `AEGIS_EMBEDDING_MODEL`, and token expiry settings. Secrets should never be placed in ConfigMaps. Use Kubernetes Secrets, GitHub Actions Secrets, or a managed secret store.

## Backup and Restore

Back up PostgreSQL with `pg_dump` or a managed database snapshot. Back up MinIO buckets with object replication or scheduled `mc mirror` jobs. Audit logs and lineage are part of the database and should be retained according to the seven-year audit policy. For restore, recover the database first, restore object storage second, then start the API and run health checks.

## Troubleshooting

If `/health` is degraded, inspect the `checks` object to identify database or storage failure. If chat answers are sparse, verify Ollama and Qdrant availability; the app falls back gracefully, but production quality improves when embeddings and vector search are online. If authentication fails after deployment, confirm `AEGIS_SECRET_KEY` is identical across API replicas. If migrations fail, run `alembic current` and `alembic upgrade head` inside the API image.

For performance issues, start with database connection pool pressure, storage latency, and LLM timeout behavior. Agent endpoints can be CPU or I/O heavy, so use the Kubernetes HPA and separate worker deployments when throughput grows. For security incidents, rotate `AEGIS_SECRET_KEY`, deactivate affected users through `/admin/users/{id}`, review `/admin/audit-logs`, and preserve database and object storage snapshots before remediation. For disaster recovery drills, restore into a staging namespace first, run `/health`, run `scripts/verify_m5.py`, and only then promote traffic.
