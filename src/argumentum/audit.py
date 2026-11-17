"""Deterministic manuscript and provenance checks."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .models import Paper

CITATION_PATTERN = re.compile(r"\[(A-\d{3}|DEMO-\d{3})\]")


def audit_manuscript(
    manuscript: str, papers: list[Paper], evidence_ledger: dict[str, Any], demo_mode: bool = False
) -> dict[str, Any]:
    known_ids = {paper.source_id for paper in papers}
    found_ids = set(CITATION_PATTERN.findall(manuscript))
    unknown_ids = sorted(found_ids - known_ids)
    referenced_id_set = found_ids & known_ids
    referenced_ids = sorted(referenced_id_set)
    issues: list[dict[str, str]] = []
    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": passed, "detail": detail})

    check(
        "citation_ids_resolve",
        not unknown_ids,
        "All in-text source IDs resolve to the retrieved source catalogue."
        if not unknown_ids
        else f"Unknown citation IDs: {', '.join(unknown_ids)}",
    )
    if unknown_ids:
        issues.append(
            {
                "severity": "critical",
                "issue": f"Unresolved citation IDs: {', '.join(unknown_ids)}",
                "recommendation": "Remove or replace them with verified source IDs; do not invent references.",
            }
        )

    check(
        "sources_are_present",
        bool(papers),
        "Retrieved source records are available." if papers else "No literature sources were retrieved.",
    )
    if not papers:
        issues.append(
            {
                "severity": "critical",
                "issue": "No scholarly sources were retrieved.",
                "recommendation": "Repeat literature discovery or supply a verified reference library before using the draft.",
            }
        )

    check(
        "draft_contains_citations",
        bool(referenced_ids),
        "At least one citation marker is present."
        if referenced_ids
        else "No recognized in-text citation markers were found.",
    )
    if papers and not referenced_ids:
        issues.append(
            {
                "severity": "high",
                "issue": "The draft does not cite any retrieved source IDs.",
                "recommendation": "Review each factual and literature claim and attach valid source IDs where supported.",
            }
        )

    demo_sources = [paper.source_id for paper in papers if paper.is_demo]
    check(
        "no_demo_fixtures",
        not demo_sources and not demo_mode,
        "No demonstration fixture sources were used."
        if not demo_sources and not demo_mode
        else "The run used demonstration fixtures and is not scholarly evidence.",
    )
    if demo_sources or demo_mode:
        issues.append(
            {
                "severity": "critical",
                "issue": "The output was generated in demonstration mode with fictional fixture sources.",
                "recommendation": "Do not submit or cite this output. Run a real literature search and verify every source.",
            }
        )

    missing_doi = [paper.source_id for paper in papers if not paper.doi]
    check(
        "doi_metadata_available",
        not missing_doi,
        "Every source has a DOI."
        if not missing_doi
        else f"DOI metadata is absent for: {', '.join(missing_doi)}. This is not proof that the work has no DOI.",
    )
    if missing_doi:
        issues.append(
            {
                "severity": "medium",
                "issue": f"DOI metadata is missing for: {', '.join(missing_doi)}.",
                "recommendation": "Verify each bibliographic record manually; a missing DOI field in the API response does not establish that no DOI exists.",
            }
        )

    claims = evidence_ledger.get("claims", []) if isinstance(evidence_ledger, dict) else []
    invalid_claim_ids: list[str] = []
    for claim in claims if isinstance(claims, list) else []:
        if not isinstance(claim, dict):
            continue
        source_ids = claim.get("source_ids", [])
        if not isinstance(source_ids, list) or any(
            not isinstance(source_id, str) or source_id not in known_ids for source_id in source_ids
        ):
            invalid_claim_ids.append(str(claim.get("claim_id", "unknown")))
    check(
        "evidence_ledger_ids_resolve",
        not invalid_claim_ids,
        "Evidence ledger source IDs resolve."
        if not invalid_claim_ids
        else f"Invalid source IDs in claims: {', '.join(invalid_claim_ids)}",
    )
    if invalid_claim_ids:
        issues.append(
            {
                "severity": "critical",
                "issue": "Evidence ledger contains source IDs outside the retrieved catalogue.",
                "recommendation": "Rebuild affected evidence records using only valid source IDs.",
            }
        )

    cited_unlisted = sorted(referenced_id_set - known_ids)
    check(
        "reference_integrity", not cited_unlisted, "All recognized citations are in the generated reference catalogue."
    )

    return {
        "status": "BLOCKED"
        if any(issue["severity"] == "critical" for issue in issues)
        else ("REVIEW_REQUIRED" if issues or any(not item["passed"] for item in checks) else "CHECKS_PASSED"),
        "automated_checks": checks,
        "issues": issues,
        "cited_source_ids": referenced_ids,
        "uncited_source_ids": sorted(known_ids - found_ids),
        "unknown_source_ids": unknown_ids,
        "limitations": [
            "Automated checks validate identifiers and metadata consistency, not whether a source substantively supports a claim.",
            "DOI absence in retrieved metadata does not establish that a DOI does not exist.",
            "No automated detector can certify originality, ethics compliance, or publication readiness.",
        ],
    }


def audit_run_directory(run_directory: str | Path) -> dict[str, Any]:
    """Re-run deterministic checks against the current Markdown draft and saved run records."""
    root = Path(run_directory).expanduser().resolve()

    def read_json(filename: str) -> dict[str, Any]:
        path = root / filename
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Cannot read valid {filename} from run directory {root}: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{filename} must contain a JSON object.")
        return value

    manifest = read_json("run_manifest.json")
    source_data = read_json("sources.json")
    evidence = read_json("evidence_ledger.json")
    source_rows = source_data.get("sources", [])
    if not isinstance(source_rows, list):
        raise ValueError("sources.json must contain a 'sources' array.")
    all_papers = [Paper(**item) for item in source_rows if isinstance(item, dict)]
    selected_ids = manifest.get("selected_source_ids", [])
    selected_ids = (
        {value for value in selected_ids if isinstance(value, str)} if isinstance(selected_ids, list) else set()
    )
    screened_papers = [paper for paper in all_papers if paper.source_id in selected_ids]
    manuscript_path = root / "manuscript.md"
    try:
        manuscript = manuscript_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Cannot read manuscript.md from run directory {root}: {exc}") from exc
    return audit_manuscript(manuscript, screened_papers, evidence, bool(manifest.get("demo_mode")))
