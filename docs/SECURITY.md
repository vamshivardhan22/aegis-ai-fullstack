# Security

Aegis AI uses layered security. The first layer is authentication: users register with an email and password, passwords are hashed with bcrypt through passlib, and login returns a signed JWT. The second layer is authorization: FastAPI dependencies resolve the current user and enforce role-based access control. The third layer is auditability: important actions write audit log records with user ID, action, resource type, resource ID, before and after JSON, rationale, confidence, and timestamp. The fourth layer is governance: PII scanning, lineage impact analysis, and retention policies help teams operate responsibly.

## Authentication Architecture

The security core lives in `src/core/security.py`. `get_password_hash` and `verify_password` wrap bcrypt. `create_access_token` signs JWTs using `AEGIS_SECRET_KEY`; `decode_access_token` validates token expiry and subject. `oauth2_scheme` uses OAuth2 password bearer conventions, so Swagger and standard clients can obtain and send tokens cleanly. `get_current_user` decodes the token, loads the user by email, checks active status, and returns the SQLAlchemy user model. Inactive users cannot authenticate.

## RBAC Matrix

| Capability | Admin | Data Engineer | Analyst | Viewer |
| --- | --- | --- | --- | --- |
| Health check | yes | yes | yes | yes |
| Register/login/me | yes | yes | yes | yes |
| List agents | yes | yes | yes | yes |
| Execute agents | yes | yes | no | no |
| Approve or reject pipelines | yes | yes | no | no |
| Chat ask/history | yes | yes | yes | yes |
| Dataset upload | yes | yes | no | no |
| Lineage read | yes | yes | yes | yes |
| Lineage record | yes | yes | no | no |
| Admin user management | yes | no | no | no |
| Audit log browsing | yes | no | no | no |

Authorization failures return `403` with code `FORBIDDEN`. Missing or invalid tokens return `401` with code `UNAUTHORIZED`. Rate limiting returns `429` with code `RATE_LIMITED`.

## PII Handling

The PII detection agent is designed to avoid accidental disclosure. It reads data samples from storage, but logs only column names, confidence scores, counts, and strategy decisions. Reports include masked samples rather than raw values. Detection combines heuristics, regexes, spaCy entity recognition when available, and LLM fallback. Recommended masking strategies include hash, mask last four, redact, and tokenize. High-confidence findings create alerts so a compliance or data engineering team can respond before downstream use.

## Audit Logging

Audit logs are not optional for security-sensitive actions. Registration, login, agent execution, human approval, user management, dataset creation, and retention enforcement all write records. Audit logs preserve context without requiring the original artifact to remain active. Retention policy for audit logs defaults to seven years. Admin users can filter audit logs by resource type, user, and date range.

## Compliance Notes

The retention policy performs soft deletion, not hard deletion. It marks datasets as deleted, records archival metadata, writes audit logs, and creates alerts. This is reversible from metadata and backup, which is important during investigations. The GDPR erasure helper records erasure requests and is structured for future anonymization across related records. CCPA-style access and deletion workflows can be layered on the same audit and retention primitives.

## Operational Guidance

Use strong `AEGIS_SECRET_KEY` values in every deployed environment and keep them consistent across API replicas. Store secrets in GitHub Actions Secrets, Kubernetes Secrets, or a managed secret platform. Do not commit real passwords, access keys, private certificates, or production database URLs. Rotate tokens by reducing expiry, rotating the signing key, and requiring users to log in again. Use TLS at the ingress or Traefik layer for all production traffic.
