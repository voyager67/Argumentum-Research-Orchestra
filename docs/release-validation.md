# Release validation record — 1.0.0

This record distinguishes local checks that were actually executed from integration checks that are configured but have not been observed against live services. Passing unit tests and static checks are not equivalent to an institutional production deployment or validated scientific output.

## Local checks performed for this source package

| Check | Result | Scope and interpretation |
|---|---|---|
| Python test suite | **136 passed, 10 skipped** | Unit/API/security/workflow tests. Ten skips are opt-in live service and optional framework package tests, listed below. |
| Python bytecode compilation | Passed | `src`, `tests`, scripts, and Alembic modules compile. |
| Offline CLI workflow | Passed | Deterministic demo completed the native 13-stage workflow and emitted the research artifact bundle. |
| Demo integrity audit | Correctly blocked | Fictional demo source IDs are not accepted as scholarly citations. This is expected behavior. |
| Retrieval benchmark CLI | Passed | Metric calculations were checked using a small synthetic researcher-labelled JSONL example; this is not a scientific-quality benchmark. |
| Alembic migrations | Passed against SQLite | Fresh schema reaches `0004_research_projects`, including tenant credential and project/job association migrations. This does not establish live PostgreSQL behavior. |
| Tenant/RBAC and projects | Passed | Workspace lifecycle, roles, credential lifecycle, project CRUD/archive, run association, tenant-scoped access, inactive tenant checks. |
| Upload security | Passed | Bearer validation before multipart parsing, raw-body and per-file limits, safe filename/path handling, bounded model context. |
| Recovery/retry | Passed with test doubles | Planned queue IDs, compare-and-set retry reservations, ambiguous publish handling, worker heartbeats, and reconciliation. Not a live Redis outage/restart test. |
| Sandbox unit tests | Passed | Command construction, approval checks, and fail-closed behavior. No untrusted experiment code was run in this build environment. |
| Compose YAML syntax | Passed | YAML parsing performed for deployment files. It does not prove Docker Compose validity or successful container startup. |
| UI JavaScript syntax | Passed | Shipped inline application script extracted and checked with Node.js `--check`. |
| UI / project administration contract | Passed | Browser application source and API endpoint contracts tested; visual preview uses clearly labelled synthetic data. |
| README / release visuals | Passed | Local README links checked; SVG diagrams parsed; PNG, GIF, and MP4 assets included. The workflow animation is conceptual, not a live recording. |
| Deployment preflight | Unit tests passed | Safe reporting, secret/token redaction, bounded external checks, and status handling exercised with test doubles. No live probes are claimed. |
| Wheel build / isolated install | Passed | Wheel rebuilt from the latest source, installed to an isolated target, and version, CLI entry point, and packaged UI checked. |
| Release archive integrity | Passed | ZIP integrity and source-file inclusion checks performed; cache, `.env`, generated run outputs, and nested build metadata excluded. |
| Ruff lint | **Not executed locally** | Ruff 0.17.5 is pinned in the dev extra, pre-commit configuration, and CI. The environment could not resolve package-index DNS, so no local Ruff result is claimed. |

## Pipeline harness verification

The source implements four full-pipeline harnesses. The common workflow contract is exercised locally using framework-compatible test doubles. The native pipeline was also run end to end in demo mode.

| Harness | Local contract test | Actual optional framework integration |
|---|---|---|
| Native | Passed | Passed; native is included in the core package |
| LangGraph | Passed using a StateGraph-compatible test double | Skipped locally because `langgraph` is not installed |
| CrewAI Flow | Passed using a Flow/listener-compatible test double | Skipped locally because `crewai` is not installed |
| Microsoft Agent Framework | Passed using a WorkflowBuilder/executor-compatible test double | Skipped locally because `agent_framework` is not installed |

CI includes separate jobs which install each optional extra and execute both the individual-agent and full-pipeline test modules. Those results are not yet observed until the repository is pushed and the workflow completes. Framework-native stage checkpoint persistence is not connected to PostgreSQL job recovery; an RQ retry can restart at the first research stage.

## Ten skipped tests

- One live model endpoint test: requires `ARGUMENTUM_LIVE_MODEL_TESTS=1` and a reachable configured endpoint.
- One live GROBID test: requires `ARGUMENTUM_LIVE_GROBID_TESTS=1` and a reachable GROBID service.
- One live scholarly API test: requires `ARGUMENTUM_LIVE_SCHOLARLY_TESTS=1` and external network access.
- One live PostgreSQL/Redis/RQ test: requires `ARGUMENTUM_LIVE_INTEGRATION=1` and disposable service instances.
- Three individual-agent framework tests: optional dependencies are not installed locally.
- Three full-pipeline framework tests: optional dependencies are not installed locally.

## Remote pull-request checks reviewed — 17–18 November 2026

These checks ran on Dependabot branches, not on the current `main` commit. They are diagnostic evidence, not a passing release build.

| Pull request | Proposed change | Observed checks | Recommendation |
|---|---|---|---|
| [#3 — Python 3.15](https://github.com/voyager67/Argumentum-Research-engine/pull/3) | Changes both Docker bases from Python 3.12-slim to 3.15-slim. | Python 3.11–3.13 test jobs, optional framework jobs, live Postgres/Redis/RQ integration, Compose configuration, and both image builds passed. The Compose smoke test failed while API/worker/reconciler mounted and initialized the shared data volume concurrently (`/data/runs` already existed). The CI Python test matrix did not test Python 3.15 itself. | Defer; not required for 1.0.0. Re-test Python 3.15 explicitly before adopting it. |
| [#5 — RQ 3.x](https://github.com/voyager67/Argumentum-Research-engine/pull/5) | Widens RQ from `<3` to `<4`, allowing RQ 3.x. | No workflow run was returned for this PR branch during the audit. RQ 3 includes breaking API changes. | Do not merge until RQ 3 compatibility tests pass; keep the existing `<3` bound for 1.0.0. |
| [#6 — redis-py 8.x](https://github.com/voyager67/Argumentum-Research-engine/pull/6) | Widens redis-py from `<7` to `<9`, allowing redis-py 8.x. | The live Postgres/Redis/RQ integration job passed with redis-py 8.1.0 and Redis server 7.2.17. Python test jobs and the Compose smoke test failed because the PR head's stale `api.py` lacked the `dataclass` import; current `main` contains that import. | Rebase onto current `main` and run the full suite before considering it. It is not necessary for 1.0.0. |

The #3 and #6 smoke-test logs also exposed a service-startup race: background services could mount the shared application volume before the API completed initial database migration and volume setup. Compose now makes the worker and reconciler wait for the API health check. A fresh Actions run on current `main` is still required to verify this fix.

## GitHub Actions — current main passed (18 November 2026)

[Run #40](https://github.com/voyager67/Argumentum-Research-engine/actions/runs/44250409213) completed successfully on commit `5bf38a44a74ca8eb23e7f51b6dfaff1a07313360`. All nine jobs passed: Python 3.11/3.12/3.13 tests with Ruff and UI JavaScript validation; LangGraph, CrewAI and Microsoft Agent Framework integration; live PostgreSQL/Redis/RQ integration; self-hosted Compose validation and Docker image builds; and the Docker Compose smoke test.

The smoke test built and started the API, database, Redis, worker and reconciler, then submitted an offline research run and verified its resulting artifacts. This confirms the Compose startup-ordering change on that commit.

The GitHub Actions workflow is configured to run:

1. Python tests and Ruff lint across Python 3.11, 3.12, and 3.13.
2. JavaScript syntax validation using Node.js 22.
3. Separate live optional-framework installations and full-pipeline executions.
4. PostgreSQL and Redis service-container integration tests.
5. Docker Compose configuration validation and Docker image builds.
6. Docker Compose smoke test that submits and polls an offline research run.

This run is a successful CI result for the commit linked above. Any subsequent source change should be assessed using its own workflow run.

## Not verified / not covered by CI

The successful CI run verifies the repository's automated software checks on GitHub-hosted runners and disposable services. It is not a production deployment or a security certification. The following remain outside the verified scope:

- Actual Ollama/vLLM inference, model structured-output compatibility, GPU memory, throughput, or model quality.
- Actual GROBID extraction or current OpenAlex, Crossref, Semantic Scholar, Europe PMC, and arXiv connectivity/rate-limit behavior.
- Broker outage recovery, scheduler timing, duplicate delivery under restart, worker crash recovery, multi-replica behavior, and framework-specific durable node checkpoint/restart integration with PostgreSQL/RQ.
- OIDC/SAML SSO, MFA, SCIM, PostgreSQL row-level security, tenant quotas, external identity-provider integration, or formal security certification.
- Sandbox security certification or execution of untrusted user code under real production Docker/Linux host constraints.
- User-labelled retrieval/scientific-quality benchmark results, expert assessment of claim support, human peer review, or measured improvements in scientific accuracy.

## Required operator validation before institutional production use

1. Run the prepared GitHub Actions workflow and retain successful test, lint, service integration, and Docker smoke-test logs.
2. Run the Compose stack on the intended Linux host, including model serving and optional document-extraction profiles.
3. Test `bwrap` namespace creation and the no-network sandbox boundary with benign test cases before enabling experiment execution; conduct an independent threat review.
4. Test the actual model endpoint with representative prompt sizes and structured outputs; measure memory and throughput on the selected hardware.
5. Test GROBID and each scholarly provider with institution-approved egress, quotas, and sample papers/PDFs.
6. Back up and restore PostgreSQL and the artifact/input volume together; validate retention and deletion behavior.
7. Place remote access behind TLS, restrict egress/ingress, manage secrets with an approved secret store, and review tenant access controls with the institution's security team.
8. Evaluate retrieval on a researcher-labelled corpus with pre-registered relevance criteria. Have domain experts review claim support, synthesis balance, methodological critique, and hallucination risk.

## Product boundaries

The source includes the native 13-stage research orchestrator, three optional full-pipeline framework harnesses (LangGraph, CrewAI Flow, Microsoft Agent Framework), per-agent invocation adapters, a tenant-scoped researcher workspace, API-token RBAC, self-hosted API/worker/reconciler, optional human-approved experiment runner, scholarly metadata adapters, optional GROBID extraction, and retrieval-metric tooling. Full-pipeline framework execution is implemented but optional framework packages were not run locally. No empirical scientific-quality benchmark or production deployment certification is claimed.
