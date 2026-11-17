"""Command-line interface for Argumentum."""

from __future__ import annotations

import argparse
import ipaddress
import json
import sys
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlparse

from . import __version__
from .agents import AGENTS, CAPABILITY_PACKS
from .audit import audit_run_directory
from .config import Settings
from .evaluation import evaluate_retrieval_jsonl
from .models import ResearchRequest
from .pipeline import ResearchPipeline
from .providers import DemoProvider, OpenAICompatibleProvider
from .workflows import available_pipeline_harnesses


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="argumentum", description="Evidence-traceable multi-agent research workflow")
    parser.add_argument("--version", action="version", version=f"Argumentum {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="Run the complete research workflow")
    run.add_argument("--topic", required=True, help="Research topic")
    run.add_argument("--question", required=True, help="Primary research question")
    run.add_argument("--discipline", default="Interdisciplinary")
    run.add_argument("--study-type", default="auto", help="Examples: empirical, review, theoretical, design science, auto")
    run.add_argument("--audience", default="graduate researchers")
    run.add_argument("--source-limit", type=int, default=24)
    run.add_argument("--input-dir", type=Path, help="Directory of research notes, PDFs, CSVs, or other supported materials")
    run.add_argument("--output-dir", type=Path, default=Path("argumentum-output"))
    run.add_argument("--query", action="append", default=[], help="Additional literature query; may be repeated")
    run.add_argument("--demo", action="store_true", help="Run offline with clearly fictional fixture sources")
    run.add_argument("--harness", choices=available_pipeline_harnesses(), help="Full-workflow orchestration backend")

    doctor = subparsers.add_parser("doctor", help="Check configuration without sending requests")
    doctor.add_argument("--json", action="store_true", help="Print machine-readable diagnostics")

    subparsers.add_parser("agents", help="List the specialist agents and capability packs")
    audit = subparsers.add_parser("audit", help="Re-run deterministic integrity checks on an existing run")
    audit.add_argument("--run-dir", type=Path, required=True, help="Existing Argumentum run directory")

    subparsers.add_parser("audit-help", help="Explain deterministic integrity checks")
    benchmark = subparsers.add_parser("benchmark-retrieval", help="Evaluate retrieval against a researcher-labelled JSONL gold set")
    benchmark.add_argument("--input", type=Path, required=True, help="JSONL with query_id, retrieved_ids and relevant_ids")
    benchmark.add_argument("--k", type=int, default=5, help="Cutoff for ranking metrics (1-100)")
    benchmark.add_argument("--output", type=Path, help="Optional JSON output path; stdout is used by default")
    return parser


def _is_loopback_endpoint(base_url: str) -> bool:
    hostname = (urlparse(base_url).hostname or "").lower()
    if hostname == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _is_local_compatible_endpoint(base_url: str) -> bool:
    hostname = (urlparse(base_url).hostname or "").lower()
    if hostname in {"ollama", "vllm", "host.docker.internal"}:
        return True
    try:
        address = ipaddress.ip_address(hostname)
        return address.is_loopback or address.is_private or address.is_link_local
    except ValueError:
        return _is_loopback_endpoint(base_url)


def _doctor(settings: Settings) -> dict[str, object]:
    local_endpoint = _is_local_compatible_endpoint(settings.base_url)
    if settings.api_key:
        llm_mode = "configured_api_key"
    elif local_endpoint:
        llm_mode = "local_compatible_keyless"
    else:
        llm_mode = "missing_credentials"
    return {
        "version": __version__,
        "python": sys.version.split()[0],
        "llm_base_url": settings.base_url,
        "llm_model": settings.model,
        "llm_api_key_configured": bool(settings.api_key),
        "openalex_api_key_configured": bool(settings.openalex_api_key),
        "mailto_configured": bool(settings.mailto),
        "llm_mode": llm_mode,
        "pipeline_harness": settings.pipeline_harness,
        "available_pipeline_harnesses": list(available_pipeline_harnesses()),
        "notes": [
            "Use --demo for a fully offline run. Its records are fictional and must not be cited.",
            "Ollama and other OpenAI-compatible servers can be used by setting ARGUMENTUM_LLM_BASE_URL and ARGUMENTUM_LLM_MODEL.",
            "A hosted LLM endpoint receives the research context included in prompts. Review the provider's privacy and retention terms before sending sensitive material.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings.from_env()

    if args.command == "doctor":
        result = _doctor(settings)
        print(json.dumps(result, indent=2) if args.json else "\n".join(f"{key}: {value}" for key, value in result.items()))
        return 0

    if args.command == "agents":
        print("SPECIALIST AGENTS")
        for agent in AGENTS:
            print(f"- {agent.name} [{agent.agent_id}] — {agent.purpose}")
        print("\nCAPABILITY PACKS")
        for pack in CAPABILITY_PACKS:
            print(f"- {pack.name} — {pack.purpose}")
        return 0

    if args.command == "audit":
        try:
            report = audit_run_directory(args.run_dir)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report["status"] == "CHECKS_PASSED" else 1
        except Exception as exc:
            print(f"Argumentum audit error: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 2

    if args.command == "benchmark-retrieval":
        try:
            report = evaluate_retrieval_jsonl(args.input, args.k)
            rendered = json.dumps(report, ensure_ascii=False, indent=2)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(rendered + "\n", encoding="utf-8")
                print(f"Retrieval benchmark written to {args.output}")
            else:
                print(rendered)
            return 0
        except Exception as exc:
            print(f"Argumentum benchmark error: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 2

    if args.command == "audit-help":
        print("Argumentum deterministically checks citation-ID resolution, presence of retrieved sources, demo-fixture use, DOI metadata availability, and evidence-ledger source IDs. These checks do not prove that a citation supports a claim, nor certify originality, ethics, or publication readiness.")
        return 0

    if args.command == "run":
        try:
            if args.harness:
                settings = replace(settings, pipeline_harness=args.harness)
            request = ResearchRequest(
                topic=args.topic,
                research_question=args.question,
                discipline=args.discipline,
                study_type=args.study_type,
                audience=args.audience,
                source_limit=args.source_limit,
                search_queries=tuple(args.query),
            )
            if args.demo:
                provider = DemoProvider()
            else:
                if not settings.api_key and not _is_local_compatible_endpoint(settings.base_url):
                    raise ValueError("No LLM API key is configured. Set ARGUMENTUM_LLM_API_KEY / OPENAI_API_KEY, configure a local compatible server, or use --demo.")
                provider = OpenAICompatibleProvider(settings)
            pipeline = ResearchPipeline(provider, settings, demo_mode=args.demo)
            result = pipeline.run(request, args.output_dir, args.input_dir)
            print(f"Argumentum run completed: {result}")
            print(f"Integrity report: {result / 'integrity_report.json'}")
            print("Review every source and claim before academic use.")
            return 0
        except Exception as exc:
            print(f"Argumentum error: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 2

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
