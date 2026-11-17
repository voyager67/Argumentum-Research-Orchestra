# Self-hosting Argumentum

This guide deploys the Argumentum API, researcher UI, background worker, tenant-aware credentials, PostgreSQL, Redis/RQ, and periodic queue reconciler on infrastructure you control. The optional model, GROBID, and experiment services are separate deployment profiles.

## Services

| Service | Purpose | Persistent data |
|---|---|---|
| `api` | FastAPI, tenant authentication/RBAC, REST API, `/ui`, OpenAPI | Research artifacts and private inputs volume |
| `worker` | RQ worker for research pipelines and delayed retries | Research artifacts and private inputs volume |
| `reconciler` | Repairs uncertain Redis publications and stale worker states | Read-only application data volume |
| `postgres` | Tenant, credential, run, and durable status records | `postgres_data` |
| `redis` | RQ queue and retry scheduling | `redis_data` (AOF enabled) |
| `ollama` profile | Optional local model inference | `ollama_models` |
| `vllm` profile | Optional NVIDIA model inference | `vllm_models` |
| `documents` profile | Optional GROBID PDF-to-TEI extraction | Image-managed model data |
| `sandbox` profile | Optional human-approved Python experiment runner | Private experiment queue/results in application data volume |

The API, worker, database, and Redis use a private Compose network. PostgreSQL, Redis, model servers, and GROBID are not published to the host by default. Only the API is bound to `127.0.0.1` unless you intentionally change it. Keep the application data volume private; it contains uploaded research material, run outputs, credentials metadata, and experiment queue records.

## Prerequisites

- Docker Engine and the Docker Compose v2 plugin.
- Linux host recommended for the optional bubblewrap experiment sandbox.
- Disk space for database/queue volumes, research artifacts, model weights and images.
- RAM/VRAM depends heavily on the selected model. The API/worker stack itself is much smaller than the local model.
- For GPU inference: a supported NVIDIA driver and NVIDIA Container Toolkit configured for Docker.

## 1. Generate local secrets

From the repository root:

```bash
python scripts/init-selfhost.py
```

This creates `.env` with distinct random PostgreSQL, Redis, default-workspace owner, platform-admin, and vLLM secrets. It creates the file with restrictive permissions where supported and refuses to overwrite an existing `.env`. Review the model settings and keep `.env` private. Never commit it or paste the tokens into issues or chat.

## 2. Start the core stack

Start PostgreSQL, Redis, API, worker, and reconciler without starting any model server:

```bash
docker compose up --build -d postgres redis api worker reconciler
```

The API applies committed Alembic migrations at startup. Wait for readiness:

```bash
docker compose ps
curl --fail http://127.0.0.1:8080/health/live
curl --fail http://127.0.0.1:8080/health/ready
```

Run the installed deployment preflight from the host. It checks health and, when the workspace bootstrap token is loaded, verifies authentication. It does not print secret values:

```bash
set -a
. ./.env
set +a
argumentum-preflight --api-url http://127.0.0.1:8080 --docker
```

The host-side preflight above checks the published API and Docker Compose status. For internal database, broker, model, and scholarly-service checks, run the preflight inside the worker container: that container can resolve private Compose service names such as `postgres`, `redis`, `ollama`, and `grobid` and has the server/provider configuration loaded.

```bash
# Core database + Redis + model + scholarly catalogue checks.
docker compose exec worker argumentum-preflight --api-url http://api:8080 --infrastructure --model --scholarly

# Add this only when the documents/GROBID profile is enabled and ARGUMENTUM_GROBID_URL is configured.
docker compose exec worker argumentum-preflight --api-url http://api:8080 --grobid
```

The infrastructure probes use a real `SELECT 1` against PostgreSQL and `PING` against Redis. The model probe sends a minimal JSON-mode request, the GROBID probe checks `/api/isalive`, and the scholarly probe makes a bounded search request to OpenAlex, Crossref, Semantic Scholar, Europe PMC, and arXiv. These are live checks: they consume provider quota and depend on service health. A successful health probe is not a scientific-quality evaluation.

The browser research interface is available at `http://127.0.0.1:8080/ui`. API docs are available at `/docs` when `ARGUMENTUM_DOCS_ENABLED=true`.

## 3. Configure inference

### Ollama

Start the Ollama profile:

```bash
docker compose --profile ollama up --build -d
```

Pull the model into the persistent Ollama volume:

```bash
docker compose --profile ollama exec ollama ollama pull qwen2.5:14b
```

The `.env` sample uses:

```dotenv
ARGUMENTUM_LLM_BASE_URL=http://ollama:11434/v1
ARGUMENTUM_LLM_API_KEY=
ARGUMENTUM_LLM_MODEL=qwen2.5:14b
```

Restart the API and worker after changing `.env`:

```bash
docker compose up -d --force-recreate api worker
```

### vLLM

vLLM requires a supported NVIDIA GPU/runtime and model weights compatible with available memory. Set these values in `.env`:

```dotenv
ARGUMENTUM_LLM_BASE_URL=http://vllm:8000/v1
ARGUMENTUM_LLM_API_KEY=THE_SAME_VALUE_AS_VLLM_API_KEY
ARGUMENTUM_LLM_MODEL=Qwen/Qwen2.5-14B-Instruct
VLLM_MODEL=Qwen/Qwen2.5-14B-Instruct
VLLM_API_KEY=THE_SAME_VALUE_AS_ARGUMENTUM_LLM_API_KEY
```

Use a strong random value for both key settings, then start:

```bash
docker compose -f compose.yaml -f compose.vllm.yaml --profile vllm up --build -d
```

### Host-managed OpenAI-compatible servers

A host-managed llama.cpp server, SGLang service, or approved hosted provider can be configured using `ARGUMENTUM_LLM_BASE_URL`, `ARGUMENTUM_LLM_API_KEY`, and `ARGUMENTUM_LLM_MODEL`. From inside a container, `localhost` refers to that container. Use a reachable private hostname or `host.docker.internal` where supported. Do not publish an unauthenticated model endpoint to an untrusted network.

Argumentum sends `/chat/completions` requests using JSON response formatting. OpenAI-compatible does not mean feature-identical. Test the chosen provider/model against representative Argumentum prompts before using it for real research.

### Choose an agent invocation harness

The default is `ARGUMENTUM_AGENT_HARNESS=native`. Optional values `langgraph`, `crewai`, and `microsoft-agent-framework` wrap individual specialist-agent invocations. Set the desired extra in `ARGUMENTUM_EXTRAS` before building the image, e.g. `server,all-documents,langgraph`. The complete research stage order remains Argumentum's native sequential pipeline; see [Agent execution harnesses](harnesses.md).

## 4. Workspaces and researcher accounts

The initializer creates two different operator secrets:

- `ARGUMENTUM_ADMIN_TOKEN`: platform administrator for creating/listing/enabling/disabling workspaces and maintenance operations.
- `ARGUMENTUM_API_TOKEN`: owner credential for the pre-created `default` workspace. It is useful for a single operator and initial administration of that workspace.

Do not hand either operator token to every researcher. Create one workspace per research group or institution, then issue individual credentials. See [Workspaces, identities, and role permissions](tenancy.md).

Create a workspace (the response contains the new owner's one-time token):

```bash
export ARGUMENTUM_ADMIN_TOKEN="$(sed -n 's/^ARGUMENTUM_ADMIN_TOKEN=//p' .env)"
curl --fail-with-body http://127.0.0.1:8080/api/v1/admin/tenants \
  -H "Authorization: Bearer ${ARGUMENTUM_ADMIN_TOKEN}" \
  -H 'Content-Type: application/json' \
  -d '{"name":"Neuroscience Lab","slug":"neuroscience-lab"}'
```

Issue a researcher token using that workspace's owner token:

```bash
export WORKSPACE_OWNER_TOKEN="<owner_token_from_creation_response>"
curl --fail-with-body http://127.0.0.1:8080/api/v1/tenant/credentials \
  -H "Authorization: Bearer ${WORKSPACE_OWNER_TOKEN}" \
  -H 'Content-Type: application/json' \
  -d '{"name":"Dr. Example — research account","role":"researcher"}'
```

The individual token is returned once. A workspace owner/admin can list credentials and revoke credentials through `/api/v1/tenant/credentials`. The UI at `/ui` accepts a workspace token, displays that workspace's runs, and allows researchers to submit runs and download result artifacts.

Roles are `owner`, `admin`, `researcher`, and `viewer`. Owners can issue admins; admins cannot issue admins or revoke owner/admin credentials. Researchers can submit runs and read artifacts. Viewers can only read. A platform administrator does not automatically belong to a workspace and cannot submit a research run until it uses a workspace credential.

This is API-token-based RBAC, not a complete identity platform. There is no password login, OIDC/SAML/SSO, MFA, SCIM, or PostgreSQL row-level security. Tenant isolation is enforced at the API layer. Use an external identity-aware gateway if institutional policy requires SSO or stronger authentication.

## 5. Submit a run

For a fast service smoke test that does not call an LLM or scholarly API, use `demo_mode`:

```bash
export WORKSPACE_TOKEN="<workspace_owner_or_researcher_token>"
curl --fail-with-body http://127.0.0.1:8080/api/v1/runs \
  -H "Authorization: Bearer ${WORKSPACE_TOKEN}" \
  -H 'Content-Type: application/json' \
  -d '{"topic":"Service smoke test","question":"Can the self-hosted queue complete a traceable demo workflow?","demo_mode":true}'
```

The response includes `run_id`. Poll the run:

```bash
curl --fail http://127.0.0.1:8080/api/v1/runs/RUN_ID \
  -H "Authorization: Bearer ${WORKSPACE_TOKEN}"
```

Researcher-supplied materials can be submitted through the authenticated multipart endpoint:

```bash
curl --fail-with-body http://127.0.0.1:8080/api/v1/runs/with-materials \
  -H "Authorization: Bearer ${WORKSPACE_TOKEN}" \
  -F 'request_json={"topic":"Protocol-aware review","question":"How should the supplied protocol inform the evidence synthesis?","source_limit":30}' \
  -F 'files=@./protocol.md;type=text/markdown' \
  -F 'files=@./study-data.csv;type=text/csv' \
  -F 'files=@./article.pdf;type=application/pdf'
```

Uploads accept `.md`, `.markdown`, `.txt`, `.csv`, `.json`, `.bib`, `.tex`, `.pdf`, and `.docx`. Limits are 100 files, 25 MiB per file, 100 MiB total, plus an outer ASGI request-body cap. The bearer token is checked before multipart parsing. Filenames cannot contain directory separators, and duplicates are rejected. Inputs are stored in the private application volume and passed to workers using the run ID, not a client-controlled path. Inputs can be removed after completion with `DELETE /api/v1/runs/RUN_ID/materials`; generated artifacts remain available.

List artifacts and fetch one:

```bash
curl --fail http://127.0.0.1:8080/api/v1/runs/RUN_ID/artifacts \
  -H "Authorization: Bearer ${WORKSPACE_TOKEN}"
curl --fail http://127.0.0.1:8080/api/v1/runs/RUN_ID/artifacts/RUN_SUMMARY.md \
  -H "Authorization: Bearer ${WORKSPACE_TOKEN}"
```

Only an explicit allowlist of generated artifact names is downloadable. Run records and artifact access are scoped to the current workspace.

## 6. Optional GROBID extraction

GROBID enriches researcher-supplied PDF extraction with TEI structure. Start it with the overlay and profile:

```bash
docker compose -f compose.yaml -f compose.grobid.yaml \
  --profile documents up --build -d
```

The overlay points the worker at `http://grobid:8070`. GROBID is optional; when it is not reachable, Argumentum records an error-type warning and falls back to local `pypdf` extraction if the PDF extra is installed. Extracted references must still be checked against the original PDF.

## 7. Optional human-approved experiment runner

The sandbox profile is not required for manuscript generation. It enables a separate no-network worker for short researcher-submitted Python snippets:

```bash
docker compose --profile sandbox up --build -d sandbox_runner
```

Only workspace owners/admins can submit an experiment and the request requires `human_approved: true`. Each snippet is limited to 32 KiB and 1–30 seconds, and each tenant can have at most five queued/running items. The worker uses bubblewrap namespaces, a separate no-network container, a minimal filesystem view, and CPU/memory/process/output limits. It fails closed if the host cannot create the isolation namespaces. It does not execute model-generated code automatically, mount research files into the snippet, or allow package installation. Read [Human-approved experiment execution](experiments.md) before enabling it; validate isolation on the actual Linux/Docker host.

## 8. Scale workers

Each RQ worker processes one job at a time. Scale only after measuring model capacity:

```bash
docker compose up -d --scale worker=2
```

More workers can increase queue throughput but can overload a local model server or exhaust GPU memory. Start with one. Use the periodic reconciler to recover uncertain queue publications and stale worker leases. Maintenance reconciliation is restricted to the platform-admin credential.

## 9. Backups and upgrades

Back up PostgreSQL and the `argumentum_data` volume together. Quiesce workers before taking a consistent filesystem-level snapshot of artifacts/inputs. Keep backups encrypted and test restore procedures. Redis is a queue and is configured with append-only persistence, but PostgreSQL run records and the artifact/input volume are the durable application records.

```bash
docker compose exec -T postgres pg_dump -U argumentum argumentum > argumentum-db.sql
```

For upgrades, read the changelog, back up first, build images, and let the API apply the committed Alembic migrations before workers resume:

```bash
docker compose build --pull
docker compose up -d
```

Do not use `docker compose down -v` unless you intend to delete every named volume. Pin image tags/digests and dependency versions according to your institution's update policy.

## 10. Remote access and hardening

The example binds the API to loopback. For remote access, see [Reverse proxy guidance](reverse-proxy.md).

1. Keep PostgreSQL, Redis, model servers and GROBID private; never publish their ports directly.
2. Terminate TLS at an actively maintained reverse proxy or identity-aware gateway.
3. Restrict inbound traffic with firewall rules or a VPN. Do not bind `0.0.0.0` without TLS and network controls.
4. Protect the platform-admin token separately from workspace tokens.
5. Disable OpenAPI docs if not needed (`ARGUMENTUM_DOCS_ENABLED=false`).
6. Use an approved secret manager for managed deployments; `.env` is a single-host convenience, not a secret-management platform.
7. Review model-provider data retention and institutional approval before sending research context to hosted endpoints.
8. Encrypt backups and storage at rest; apply retention/deletion policy to original uploads and generated outputs.
9. Review container images/dependencies and validate the experiment sandbox on the target host before enabling it.

## 11. Troubleshooting

- `503 Could not confirm queue publication`: inspect Redis/API logs and run status before resubmitting; use platform-admin reconciliation after Redis recovers.
- Runs stay queued: inspect `docker compose logs worker`; confirm Redis is healthy and the worker listens to the `argumentum` queue.
- Model connection errors: check the model URL from inside the worker container, model name, model server logs and API-key settings.
- Out-of-memory errors: use a smaller/quantized model, reduce worker replicas, or add GPU memory.
- API returns `401`: verify the active token. Workspace token revocation/tenant deactivation takes effect through database-backed auth.
- API returns `403`: check workspace role and tenant activation; platform-admin tokens cannot submit workspace research runs.
- Experiment status becomes `blocked`: inspect the sandbox runner logs and host user-namespace/bubblewrap support; do not bypass fail-closed checks.
- Migration errors: back up first, inspect Alembic output, and do not delete volumes or schema state to force startup.
