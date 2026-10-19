# AGIES AI — Governed DataOps Platform

AGIES AI is a full-stack reference project for managing data and AI workflows with clear access controls, approval checkpoints, dataset lineage, PII detection, audit records, and operational monitoring. It pairs a FastAPI backend with a React dashboard.

## What it does

- **Agent orchestration:** Runs registered data and AI workflow agents through API endpoints.
- **Authentication and RBAC:** Uses JWT-based authentication and role-based permissions for Admin, Data Engineer, Analyst, and Viewer roles.
- **Human approval:** Supports approval and rejection for workflows that require review.
- **PII detection:** Scans dataset samples for potentially sensitive information and can create alerts.
- **Data lineage:** Records relationships between source and transformed datasets.
- **Operational chat:** Provides database-aware answers and retrieval-assisted knowledge responses.
- **Monitoring and audit logs:** Exposes workflow status, alerts, and records of important actions.
- **Web dashboard:** Includes views for pipelines, agents, approvals, datasets, chat, lineage, monitoring, and administration.

Some workflow stages use lightweight compatibility agents for demonstration and smoke-flow coverage. The deeper implementations include transformation, PII detection, explanation, deployment, monitoring, drift checks, and retrieval-assisted knowledge.

## Technology stack

- **Backend:** Python 3.11, FastAPI, SQLAlchemy
- **Frontend:** React, Vite, Tailwind CSS
- **Storage and services:** SQLite for local development; PostgreSQL, Redis, MinIO, Qdrant, MLflow, and Ollama are represented in the Compose configuration
- **Testing and quality:** pytest, Ruff, mypy, frontend build checks, and GitHub Actions
- **Deployment assets:** Docker, Docker Compose, and Kubernetes manifests

## Repository structure

```text
src/                  FastAPI API, agents, services, models, policies
aegis-frontend/       React dashboard
tests/                Automated tests
scripts/              Development and verification scripts
.github/workflows/    CI/CD workflows
docker-compose.yml    Local multi-service environment
Dockerfile            Backend container
k8s/                  Kubernetes manifests
```

## Run locally

Requirements: Git, Docker, and Docker Compose.

```bash
git clone https://github.com/vamshivardhan22/aegis-ai-fullstack.git
cd aegis-ai-fullstack
cp .env.example .env
```

Before using the configuration outside a local environment, replace placeholder secrets in `.env`. Start the Compose environment:

```bash
docker compose up --build
```

The backend API is exposed on port `8000`. Open [http://localhost:8000/docs](http://localhost:8000/docs) to explore the FastAPI endpoints. The frontend can also be run separately from `aegis-frontend/` using its npm scripts.

The full Compose stack includes databases, storage, cache, model tracking, vector search, and local LLM services. First startup may take time while images and model data are downloaded.

## Verification

For backend checks, use the commands configured by the project:

```bash
python -m ruff check src --no-cache
python -m mypy src --no-error-summary
python -m pytest tests/e2e -q
```

For the frontend:

```bash
cd aegis-frontend
pnpm install --frozen-lockfile
pnpm run build
```

Run verification from the appropriate environment and confirm the results before treating a build or test suite as passing.

## Security and limitations

- Use a unique `AEGIS_SECRET_KEY` in any shared or deployed environment.
- Do not commit real credentials, local databases, or generated data.
- Configure CORS origins and ingress TLS for the intended deployment.
- Review access policies, backups, retention, and monitoring before handling real data.
- This repository is a reference implementation, not a formal compliance certification or a turnkey production deployment.
- Some agents are compatibility stages, so not every workflow stage has a full domain-specific implementation.

## Skills demonstrated

Python, FastAPI, React, REST API design, agent orchestration, data engineering, role-based access control (RBAC), human-in-the-loop approvals, PII detection, data lineage, audit logging, retrieval-augmented generation (RAG), Docker, automated testing, and CI/CD.
