"""Research workflow orchestration with explicit stage records and deterministic exports."""

from __future__ import annotations

import json
import os
import platform
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from ._version import __version__
from .agents import AGENTS
from .audit import audit_manuscript
from .config import Settings
from .harnesses import invoke_agent
from .io_utils import MAX_CSV_PREVIEW_FILES, read_materials, summarize_csv_documents
from .models import AgentResult, Paper, ResearchRequest
from .providers import ModelProvider
from .render import render_bibtex, render_evidence_ledger, render_latex, render_manuscript, render_peer_review
from .sources import DEMO_PAPERS, search_literature
from .workflows import PipelineStage, execute_pipeline


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def _write_json(path: Path, payload: Any) -> None:
    _atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n")


def _bounded(value: Any, max_chars: int = 10_000) -> Any:
    """Bound raw input context before it reaches any model request."""
    if isinstance(value, str):
        return value[:max_chars]
    return value


MAX_AGENT_CONTEXT_CHARS = 40_000
MAX_AGENT_CONTEXT_DOCUMENTS = 40
MAX_AGENT_DOCUMENT_CHARS = 6_000


def _source_context(papers: list[Paper]) -> list[dict[str, Any]]:
    return [
        {
            "source_id": paper.source_id,
            "title": paper.title,
            "authors": paper.authors,
            "year": paper.year,
            "venue": paper.venue,
            "doi": paper.doi,
            "url": paper.url,
            "abstract": _bounded(paper.abstract or "Abstract unavailable.", 500),
            "catalog": paper.catalog,
            "citation_count": paper.citation_count,
            "is_demo_fixture": paper.is_demo,
        }
        for paper in papers
    ]


def _agent_context_documents(documents: list[Any]) -> list[dict[str, Any]]:
    """Select bounded excerpts for model context while retaining hashes for every input."""
    context: list[dict[str, Any]] = []
    remaining = MAX_AGENT_CONTEXT_CHARS
    truncated = False
    for document in documents:
        if len(context) >= MAX_AGENT_CONTEXT_DOCUMENTS:
            truncated = True
            break
        if document.path.lower().endswith(".csv"):
            text = "[CSV content is omitted here; a bounded tabular preview is supplied only to the Data & Figure Analyst.]"
            was_truncated = False
        else:
            allowed = max(0, min(MAX_AGENT_DOCUMENT_CHARS, remaining))
            source_text = str(document.text)
            text = source_text[:allowed]
            was_truncated = len(text) < len(source_text)
            truncated = truncated or was_truncated
            remaining -= len(text)
        context.append(
            {
                "path": document.path,
                "sha256": document.sha256,
                "text": text,
                "context_truncated": was_truncated,
            }
        )
    if len(context) < len(documents):
        truncated = True
    if truncated and context:
        context[0]["context_limit_notice"] = (
            "Some researcher materials were excluded or excerpted to stay within the configured model-context budget. "
            "All ingested files remain represented in the run manifest by path, size, and SHA-256."
        )
    return context


def _valid_queries(value: Any, fallback: list[str]) -> list[str]:
    result: list[str] = []
    if isinstance(value, list):
        for item in value:
            query = str(item).strip() if item is not None else ""
            if query and query.lower() not in {existing.lower() for existing in result}:
                result.append(query[:240])
    for query in fallback:
        query = str(query).strip()
        if query and query.lower() not in {existing.lower() for existing in result}:
            result.append(query[:240])
    return result[:6]


def _normalise_section_output(output: dict[str, Any], fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    result = dict(output)
    if not isinstance(result.get("sections"), list) or not result["sections"]:
        if fallback:
            result["sections"] = fallback.get("sections", [])
        else:
            result["sections"] = []
    normalised = []
    for section in result["sections"]:
        if isinstance(section, dict):
            heading = str(section.get("heading", "")).strip()
            content = str(section.get("content", "")).strip()
            if heading or content:
                normalised.append({"heading": heading or "Untitled section", "content": content})
    result["sections"] = normalised
    result["title"] = str(
        result.get("title") or (fallback or {}).get("title") or "Untitled research manuscript"
    ).strip()
    result["abstract"] = str(result.get("abstract") or (fallback or {}).get("abstract") or "").strip()
    result["keywords"] = result.get("keywords") if isinstance(result.get("keywords"), list) else []
    return result


class ResearchPipeline:
    def __init__(self, provider: ModelProvider, settings: Settings | None = None, demo_mode: bool = False):
        self.provider = provider
        self.settings = settings or Settings.from_env()
        self.demo_mode = demo_mode
        self.agent_results: list[AgentResult] = []

    def _agent(self, agent_id: str, context: dict[str, Any]) -> dict[str, Any]:
        spec = next(agent for agent in AGENTS if agent.agent_id == agent_id)
        started = time.monotonic()
        started_at = utc_now()
        try:
            output = invoke_agent(self.settings.agent_harness, self.provider, agent_id, context)
            finished_at = utc_now()
            self.agent_results.append(
                AgentResult(
                    spec.agent_id,
                    spec.name,
                    "completed",
                    output,
                    started_at,
                    finished_at,
                    round(time.monotonic() - started, 3),
                )
            )
            return output
        except Exception as exc:
            finished_at = utc_now()
            self.agent_results.append(
                AgentResult(
                    spec.agent_id,
                    spec.name,
                    "failed",
                    {},
                    started_at,
                    finished_at,
                    round(time.monotonic() - started, 3),
                    error=type(exc).__name__,
                )
            )
            raise

    def run(self, request: ResearchRequest, output_dir: str | Path, input_dir: str | Path | None = None) -> Path:
        self.agent_results = []
        output = Path(output_dir).expanduser().resolve()
        if output.exists() and not output.is_dir():
            raise NotADirectoryError(f"Output path exists and is not a directory: {output}")
        if output.exists() and any(output.iterdir()):
            raise FileExistsError(f"Output directory is not empty; refusing to overwrite: {output}")
        output.mkdir(parents=True, exist_ok=True)
        started_at = utc_now()
        usage_start = len(getattr(self.provider, "usage", []))
        state: dict[str, Any] = {
            "request": request,
            "output": output,
            "input_dir": input_dir,
            "started_at": started_at,
            "usage_start": usage_start,
            "warnings": [],
            "documents": [],
            "input_hashes": [],
            "papers": [],
            "queries": [],
            "selected_ids": [],
            "curated_papers": [],
            "curated_catalogue": [],
            "integrity": {},
        }

        def prepare_materials(payload: dict[str, Any]) -> None:
            documents, input_warnings = read_materials(
                payload["input_dir"], self.settings.grobid_url, self.settings.grobid_timeout_seconds
            )
            payload["documents"] = documents
            payload["warnings"].extend(input_warnings)
            docs_for_model = _agent_context_documents(documents)
            payload["docs_for_model"] = docs_for_model
            if len(docs_for_model) < len(documents) or any(item.get("context_truncated") for item in docs_for_model):
                payload["warnings"].append(
                    "Researcher materials were recorded in full in the input manifest, but only bounded excerpts were sent to model stages."
                )
            csv_documents = [document for document in documents if document.path.lower().endswith(".csv")]
            payload["csv_summaries"] = summarize_csv_documents(documents)
            if len(payload["csv_summaries"]) < len(csv_documents):
                payload["warnings"].append(
                    f"CSV previews were capped at {MAX_CSV_PREVIEW_FILES} files; all supplied CSVs remain represented by input hashes."
                )
            payload["input_hashes"] = [
                {"path": doc.path, "sha256": doc.sha256, "size_bytes": doc.size_bytes} for doc in documents
            ]

        def research_director(payload: dict[str, Any]) -> None:
            director = self._agent(
                "research_director",
                {
                    "request": request.__dict__,
                    "researcher_materials": payload["docs_for_model"],
                    "instructions": "Frame the project before any literature screening. Preserve the researcher question; identify what is unknown.",
                },
            )
            payload["director"] = director
            queries = _valid_queries(director.get("search_queries"), [request.topic, request.research_question])
            if request.search_queries:
                queries = _valid_queries(queries, list(request.search_queries))
            payload["queries"] = queries

        def discover_literature(payload: dict[str, Any]) -> None:
            if self.demo_mode:
                papers = [Paper(**paper.to_dict()) for paper in DEMO_PAPERS[: request.source_limit]]
                payload["warnings"].append(
                    "DEMO MODE: all literature records are fictional fixtures; no external scholarly search was performed."
                )
            else:
                search_outcome = search_literature(payload["queries"], self.settings, request.source_limit)
                papers = search_outcome.papers
                payload["warnings"].extend(search_outcome.warnings)
                if not papers:
                    payload["warnings"].append(
                        "No scholarly records were retrieved. The workflow will not invent references; manuscript claims must remain explicitly limited."
                    )
            payload["papers"] = papers
            payload["source_catalogue"] = _source_context(papers)

        def literature_screening(payload: dict[str, Any]) -> None:
            director = payload["director"]
            scout = self._agent(
                "literature_scout",
                {
                    "research_question": director.get("research_question", request.research_question),
                    "scope": director.get("scope", []),
                    "source_catalogue": payload["source_catalogue"],
                },
            )
            allowed = {paper.source_id for paper in payload["papers"]}
            selected = scout.get("selected_source_ids")
            selected_ids = (
                [str(item) for item in selected if str(item) in allowed] if isinstance(selected, list) else []
            )
            payload["scout"] = scout
            payload["selected_ids"] = selected_ids
            if not selected_ids and payload["papers"]:
                payload["warnings"].append(
                    "Literature Scout returned no valid selected source IDs; no discovered record will be treated as screened or citable."
                )
            payload["curated_catalogue"] = [
                source for source in payload["source_catalogue"] if source["source_id"] in selected_ids
            ]
            payload["curated_papers"] = [paper for paper in payload["papers"] if paper.source_id in selected_ids]

        def evidence_analysis(payload: dict[str, Any]) -> None:
            director = payload["director"]
            payload["evidence"] = self._agent(
                "evidence_analyst",
                {
                    "research_question": director.get("research_question", request.research_question),
                    "source_catalogue": payload["curated_catalogue"],
                    "researcher_materials": payload["docs_for_model"],
                    "limits": "Source records may contain abstracts or metadata only; label evidence accordingly.",
                },
            )

        def methodology_review(payload: dict[str, Any]) -> None:
            payload["methodology"] = self._agent(
                "methodologist",
                {
                    "request": request.__dict__,
                    "research_charter": payload["director"],
                    "researcher_materials": payload["docs_for_model"],
                    "evidence_summary": payload["evidence"],
                },
            )

        def synthesis(payload: dict[str, Any]) -> None:
            payload["synthesis"] = self._agent(
                "synthesis_architect",
                {
                    "research_question": payload["director"].get("research_question", request.research_question),
                    "source_catalogue": payload["curated_catalogue"],
                    "evidence_ledger": payload["evidence"],
                    "researcher_materials": payload["docs_for_model"],
                },
            )

        def data_and_figures(payload: dict[str, Any]) -> None:
            payload["figures"] = self._agent(
                "figure_analyst",
                {
                    "csv_previews": payload["csv_summaries"],
                    "researcher_materials": payload["docs_for_model"],
                    "evidence_ledger": payload["evidence"],
                    "instructions": "Do not perform statistical tests. Recommend figures or tables only when supplied columns justify them.",
                },
            )

        def compose_manuscript(payload: dict[str, Any]) -> None:
            draft = self._agent(
                "manuscript_composer",
                {
                    "request": request.__dict__,
                    "research_charter": payload["director"],
                    "source_catalogue": payload["curated_catalogue"],
                    "evidence_ledger": payload["evidence"],
                    "methodology_review": payload["methodology"],
                    "synthesis_map": payload["synthesis"],
                    "figure_and_data_review": payload["figures"],
                    "researcher_materials": payload["docs_for_model"],
                },
            )
            payload["initial_draft"] = _normalise_section_output(draft)
            payload["initial_markdown"] = render_manuscript(payload["initial_draft"], payload["curated_papers"])

        def adversarial_review(payload: dict[str, Any]) -> None:
            payload["review"] = self._agent(
                "adversarial_reviewer",
                {
                    "manuscript": payload["initial_markdown"][:30_000],
                    "research_question": request.research_question,
                    "source_catalogue": payload["curated_catalogue"],
                    "methodology_review": payload["methodology"],
                    "evidence_ledger": payload["evidence"],
                    "synthesis_map": payload["synthesis"],
                },
            )

        def revise_manuscript(payload: dict[str, Any]) -> None:
            revised = self._agent(
                "revision_editor",
                {
                    "manuscript_structure": payload["initial_draft"],
                    "peer_review": payload["review"],
                    "source_ids_available": payload["selected_ids"],
                    "evidence_ledger": payload["evidence"],
                    "instructions": "Revise only supported claims. If a reviewer requests evidence that is absent, preserve it as a limitation or open question.",
                },
            )
            payload["revised"] = _normalise_section_output(revised, fallback=payload["initial_draft"])
            payload["manuscript"] = render_manuscript(payload["revised"], payload["curated_papers"])

        def research_integrity(payload: dict[str, Any]) -> None:
            integrity = self._agent(
                "integrity_auditor",
                {
                    "manuscript": payload["manuscript"][:35_000],
                    "source_catalogue": payload["curated_catalogue"],
                    "evidence_ledger": payload["evidence"],
                    "methodology_review": payload["methodology"],
                    "review": payload["review"],
                    "demo_mode": self.demo_mode,
                },
            )
            deterministic_audit = audit_manuscript(
                payload["manuscript"], payload["curated_papers"], payload["evidence"], self.demo_mode
            )
            llm_issues = integrity.get("issues") if isinstance(integrity.get("issues"), list) else []
            deterministic_audit["model_review"] = {
                "issues": llm_issues,
                "ai_disclosure": integrity.get(
                    "ai_disclosure",
                    "AI assistance was used; disclosure and attribution rules must be checked by the authors.",
                ),
                "submission_readiness": integrity.get("submission_readiness", "not_assessable"),
                "notes": integrity.get("notes", []),
            }
            payload["integrity"] = integrity
            payload["deterministic_audit"] = deterministic_audit

        def export_research_artifacts(payload: dict[str, Any]) -> None:
            papers = payload["papers"]
            curated_papers = payload["curated_papers"]
            evidence = payload["evidence"]
            revised = payload["revised"]
            integrity = payload["integrity"]
            deterministic_audit = payload["deterministic_audit"]
            _write_json(output / "research_charter.json", payload["director"])
            _write_json(output / "literature_scout.json", payload["scout"])
            _write_json(
                output / "sources.json", {"count": len(papers), "sources": [paper.to_dict() for paper in papers]}
            )
            _write_json(output / "evidence_ledger.json", evidence)
            _atomic_write(output / "evidence_ledger.md", render_evidence_ledger(evidence))
            _write_json(output / "methodology_review.json", payload["methodology"])
            _write_json(output / "synthesis_map.json", payload["synthesis"])
            _write_json(output / "figure_and_data_review.json", payload["figures"])
            _atomic_write(output / "manuscript.md", payload["manuscript"])
            _atomic_write(output / "manuscript.tex", render_latex(revised, curated_papers))
            _atomic_write(output / "references.bib", render_bibtex(curated_papers))
            _atomic_write(output / "peer_review.md", render_peer_review(payload["review"]))
            _write_json(output / "integrity_report.json", deterministic_audit)
            disclosure = (
                integrity.get("ai_disclosure")
                or "This manuscript was prepared with AI assistance and requires human verification."
            )
            _atomic_write(output / "AI_USE_DISCLOSURE.txt", str(disclosure).strip() + "\n")

            usage = getattr(self.provider, "usage", [])[payload["usage_start"] :]
            endpoint = urlsplit(self.settings.base_url)
            run_manifest = {
                "project": "Argumentum Research Engine",
                "version": __version__,
                "pipeline_harness": self.settings.pipeline_harness,
                "status": "completed_with_warnings"
                if payload["warnings"] or deterministic_audit["issues"]
                else "completed",
                "started_at": payload["started_at"],
                "finished_at": utc_now(),
                "python_version": platform.python_version(),
                "platform": platform.platform(),
                "request": request.__dict__,
                "input_files": payload["input_hashes"],
                "queries": payload["queries"],
                "source_count": len(papers),
                "source_ids": [paper.source_id for paper in papers],
                "selected_source_count": len(curated_papers),
                "selected_source_ids": payload["selected_ids"],
                "source_catalogues": sorted({paper.catalog for paper in papers}),
                "agent_runs": [result.to_dict() for result in self.agent_results],
                "model_provider": {
                    "adapter": type(self.provider).__name__,
                    "model": None if self.demo_mode else self.settings.model,
                    "endpoint_host": None if self.demo_mode else endpoint.hostname,
                    "temperature": None if self.demo_mode else 0.2,
                },
                "provider_usage": usage,
                "demo_mode": self.demo_mode,
                "warnings": payload["warnings"],
                "automated_audit_status": deterministic_audit["status"],
                "limitations": [
                    "LLM outputs are suggestions and were not independently validated by domain experts.",
                    "Search providers may return incomplete metadata and abstracts; retrieved records are not proof of full-text review.",
                    "Automated citation checks validate identifier resolution, not claim-to-source entailment.",
                    "This workflow does not certify originality, ethics approval, authorship eligibility, or publication readiness.",
                ],
            }
            _write_json(output / "run_manifest.json", run_manifest)
            _atomic_write(
                output / "RUN_SUMMARY.md",
                self._summary(
                    request, papers, len(curated_papers), payload["warnings"], deterministic_audit, self.demo_mode
                ),
            )

        stages = [
            PipelineStage("prepare-materials", prepare_materials),
            PipelineStage("research-director", research_director),
            PipelineStage("literature-discovery", discover_literature),
            PipelineStage("literature-screening", literature_screening),
            PipelineStage("evidence-analysis", evidence_analysis),
            PipelineStage("methodology-review", methodology_review),
            PipelineStage("research-synthesis", synthesis),
            PipelineStage("data-and-figures", data_and_figures),
            PipelineStage("manuscript-composition", compose_manuscript),
            PipelineStage("adversarial-review", adversarial_review),
            PipelineStage("manuscript-revision", revise_manuscript),
            PipelineStage("research-integrity", research_integrity),
            PipelineStage("artifact-export", export_research_artifacts),
        ]

        try:
            execute_pipeline(self.settings.pipeline_harness, stages, state)
            return output
        except Exception as exc:
            failure_manifest = {
                "project": "Argumentum Research Engine",
                "version": __version__,
                "pipeline_harness": self.settings.pipeline_harness,
                "status": "failed",
                "started_at": started_at,
                "finished_at": utc_now(),
                "request": request.__dict__,
                "agent_runs": [result.to_dict() for result in self.agent_results],
                "warnings": state["warnings"],
                "error_type": type(exc).__name__,
                "error": "Details intentionally omitted from artifacts; inspect restricted operator logs.",
            }
            _write_json(output / "run_manifest.json", failure_manifest)
            _atomic_write(
                output / "RUN_FAILED.txt",
                f"The workflow stopped before completion.\nError type: {type(exc).__name__}. Details are not stored in the research artifacts.\n",
            )
            raise

    @staticmethod
    def _summary(
        request: ResearchRequest,
        papers: list[Paper],
        selected_source_count: int,
        warnings: list[str],
        audit: dict[str, Any],
        demo_mode: bool,
    ) -> str:
        lines = [
            "# Argumentum Run Summary",
            "",
            f"**Topic:** {request.topic}",
            f"**Research question:** {request.research_question}",
            f"**Sources discovered:** {len(papers)}",
            f"**Sources selected for citation:** {selected_source_count}",
            f"**Automated integrity status:** {audit['status']}",
            f"**Demo mode:** {'Yes — fictional sources only' if demo_mode else 'No'}",
            "",
            "## Important interpretation",
            "",
            "This is an AI-assisted working draft. It is not peer reviewed, not publication-ready, and not a substitute for reading source papers or applying domain-specific research methods.",
            "",
            "## Outputs",
            "",
            "- `manuscript.md` — revised Markdown manuscript draft",
            "- `manuscript.tex` — generic article-class LaTeX draft (adapt to target venue)",
            "- `references.bib` and `sources.json` — retrieved source metadata",
            "- `evidence_ledger.md` / `.json` — claim-to-source map",
            "- `methodology_review.json` — methodological critique",
            "- `synthesis_map.json` — themes, contradictions, gaps",
            "- `figure_and_data_review.json` — data and figure suggestions",
            "- `peer_review.md` — automated adversarial critique",
            "- `integrity_report.json` — deterministic checks and model audit",
            "- `run_manifest.json` — configuration-safe provenance record",
            "",
            "## Warnings",
            "",
        ]
        lines.extend([f"- {warning}" for warning in warnings] or ["- No pipeline warnings were recorded."])
        lines.extend(
            [
                "",
                "## Required before academic use",
                "",
                "Read every cited source; verify each claim against the full text; correct all methodological details; complete ethics, data, authorship, and disclosure statements; and obtain qualified human review.",
            ]
        )
        return "\n".join(lines) + "\n"
