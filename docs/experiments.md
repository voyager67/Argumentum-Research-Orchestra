# Human-approved experiment execution

The optional experiment runner is a constrained execution facility for **researcher-supplied Python snippets**. It is not an autonomous experiment designer, general notebook server, package installer, or unrestricted code-execution API. Model-generated code is not automatically submitted or executed.

## Required opt-in

Start the separate sandbox worker only when your deployment policy permits it:

```bash
docker compose --profile sandbox up --build -d sandbox_runner
```

The API accepts experiment submissions only from workspace `owner` or `admin` credentials. The request schema requires `human_approved: true`, a short purpose, a code snippet of at most 32 KiB, and a wall-clock timeout from 1–30 seconds. Each tenant is limited to five queued/running experiment items. The approval flag is a recorded confirmation from the authenticated operator; it is not a digital-signature or institutional ethics approval.

Example:

```bash
curl --fail-with-body http://127.0.0.1:8080/api/v1/experiments \
  -H "Authorization: Bearer ${WORKSPACE_OWNER_TOKEN}" \
  -H 'Content-Type: application/json' \
  -d '{"purpose":"Check a small deterministic transformation","code":"print(sum([1, 2, 3]))","timeout_seconds":5,"human_approved":true}'
```

Use the returned `experiment_id` with `GET /api/v1/experiments/{experiment_id}` to inspect status and bounded output. Experiment results are tenant-scoped.

## Isolation model

The runner is a separate Compose service with `network_mode: none`, a read-only container root, dropped Linux capabilities, `no-new-privileges`, container-level memory/CPU/PID constraints, and a single service replica. Each snippet is launched through bubblewrap (`bwrap`) using unshared namespaces and a minimal filesystem view. The untrusted interpreter does not mount the application data volume, queue files, database credentials, Redis URL, or model API keys. It receives a fresh temporary work directory, standard Python without site packages, no network, and process resource limits. Output is truncated before it is returned.

Isolation fails closed if bubblewrap is unavailable or user namespaces cannot be created. Do not disable that check or replace the command with plain `python`. The host kernel and container runtime remain part of the security boundary; validate the namespace behavior on the target Linux host. This is defense-in-depth, not a formal sandbox certification or a substitute for a dedicated hardened execution service in a high-risk multi-user deployment.

## Inputs and limitations

- The runner is intended for short deterministic computations on data embedded in the snippet.
- It has no access to uploaded research files, local datasets, model servers, web services, package registries, credentials, or arbitrary mounted volumes.
- It does not install dependencies, provide notebooks, or persist arbitrary experiment files as research artifacts.
- A human must inspect the code and its provenance before approving execution. Do not submit malware, destructive code, personal data, or code whose effects you have not reviewed.
- No empirical scientific validity is implied by successful execution. Results still need independent validation, statistical review, and reproducibility analysis.
