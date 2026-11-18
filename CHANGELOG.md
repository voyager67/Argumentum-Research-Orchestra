# Changelog

## 1.0.0 — Single final baseline release

ARGUMENTUM Research Engine is delivered as one complete source baseline. The release is intended as a stable research-software foundation; it does not imply that institutional production deployment, scientific quality, or every optional backend has been independently certified.

### Research workflow

- Ten specialist agents grouped into five capability packs covering design, literature/evidence, methods/data, scholarly writing/review, and integrity/reproducibility.
- Thirteen explicit full-pipeline stages with a shared state contract.
- Four selectable **full-pipeline** execution backends: Native, LangGraph `StateGraph`, CrewAI Flow, and Microsoft Agent Framework workflow graph.
- Retained optional per-agent invocation adapters; they are distinct from the whole-pipeline harness selection.
- OpenAlex, Crossref, Semantic Scholar, Europe PMC, and arXiv read-only discovery adapters with normalization, deduplication, and provider-level warnings.
- Optional GROBID TEI extraction for researcher-supplied PDFs, with bounded responses and local extraction fallback.
- Source shortlist screening, evidence ledger, methodology critique, synthesis map, data/figure review, manuscript drafting, adversarial review, revision, and deterministic citation-ID audit.
- Markdown and generic LaTeX manuscript exports, BibTeX, run manifest, AI-use disclosure, and provenance hashes.

### Researcher workspace and service infrastructure

- Responsive browser workspace for projects, project-associated run submissions, run history/filtering, retries, artifact retrieval, team credentials, and platform tenant administration.
- Authenticated FastAPI service with PostgreSQL, Redis/RQ, worker, periodic reconciler, and persistent data/artifact volumes.
- Workspace/tenant credentials, owner/admin/researcher/viewer RBAC, token hashing, credential revocation, and tenant-scoped projects, jobs, and artifact access.
- Optional Ollama, vLLM/NVIDIA, GROBID, and human-approved experiment-runner deployment profiles.
- Bounded multipart uploads, safe artifact allowlists, upload-auth middleware, and researcher-input deletion after completion.
- Queue recovery with pre-reserved RQ job IDs, compare-and-set retry reservations, worker heartbeats, and periodic reconciliation.
- Optional owner/admin-approved Python experiment queue with a separate bubblewrap/container execution boundary; fails closed if required isolation is not available.
- Operator preflight command for API health, workspace authentication, PostgreSQL, Redis, model JSON-mode inference, GROBID, scholarly APIs, and Docker Compose.

### Evaluation, quality, and documentation

- Retrieval benchmark utility for researcher-labelled JSONL gold sets: Precision@k, Recall@k, MRR@k, nDCG@k, and Hit Rate@k.
- Ruff configuration, pinned development dependency, local lint target, pre-commit hooks, and CI lint workflow.
- Browser UI JavaScript syntax check, optional framework integration jobs, PostgreSQL/Redis/RQ integration job, Compose configuration/build checks, and Docker Compose offline smoke-test job.
- Original architecture illustration, a clearly labelled synthetic workspace preview, and a 13-stage research-lifecycle diagram.
- Apache-2.0 licensing, contribution/security policies, citation metadata, researcher-focused README, and release validation record.

No empirical scientific-quality benchmark, human peer review, production deployment certification, or measured accuracy improvement is claimed. See `docs/release-validation.md` for the exact local verification scope, skipped integrations, and operator-side checks.
