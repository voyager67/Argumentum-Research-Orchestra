"""Small OpenAI-compatible chat client and deterministic demo provider."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Protocol

from .config import Settings


class ModelProvider(Protocol):
    def complete_json(self, *, agent: str, system_prompt: str, user_prompt: str) -> dict[str, Any]: ...


MAX_MODEL_RESPONSE_BYTES = 8 * 1024 * 1024


class ProviderError(RuntimeError):
    pass


def parse_json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ProviderError("The model response did not contain a JSON object.")
        try:
            value = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ProviderError(f"The model returned invalid JSON: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ProviderError("The model response must be a JSON object.")
    return value


class OpenAICompatibleProvider:
    """Uses /chat/completions; works with compatible hosted APIs and local servers."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.usage: list[dict[str, Any]] = []
        if not settings.base_url.startswith(("https://", "http://")):
            raise ValueError("LLM base URL must use http:// or https://")
        if settings.timeout_seconds < 1 or settings.max_retries < 0:
            raise ValueError("Invalid timeout or retry setting")

    def complete_json(self, *, agent: str, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        url = f"{self.settings.base_url}/chat/completions"
        payload = {
            "model": self.settings.model,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json", "User-Agent": "Argumentum-Research-Engine/1.0"}
        if self.settings.api_key:
            headers["Authorization"] = f"Bearer {self.settings.api_key}"
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        last_error: Exception | None = None
        for attempt in range(self.settings.max_retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.settings.timeout_seconds) as response:
                    raw_response = response.read(MAX_MODEL_RESPONSE_BYTES + 1)
                if len(raw_response) > MAX_MODEL_RESPONSE_BYTES:
                    raise ProviderError("The model response exceeded the configured 8 MiB limit.")
                result = json.loads(raw_response.decode("utf-8"))
                content = result["choices"][0]["message"]["content"]
                if isinstance(content, list):
                    content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
                if not isinstance(content, str) or not content.strip():
                    raise ProviderError(f"Agent {agent} returned an empty message.")
                usage = result.get("usage") or {}
                self.usage.append({
                    "agent": agent,
                    "model": self.settings.model,
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "completion_tokens": usage.get("completion_tokens"),
                    "total_tokens": usage.get("total_tokens"),
                })
                return parse_json_object(content)
            except urllib.error.HTTPError as exc:
                last_error = ProviderError(f"LLM API returned HTTP {exc.code}.")
                if exc.code not in (408, 425, 429, 500, 502, 503, 504) or attempt >= self.settings.max_retries:
                    break
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
                last_error = ProviderError(f"LLM request failed for {agent} ({type(exc).__name__}).")
                if attempt >= self.settings.max_retries:
                    break
            time.sleep(min(2 ** attempt, 8))
        raise last_error or ProviderError(f"LLM request failed for {agent}.")


class DemoProvider:
    """Offline provider for smoke tests and demonstrations; never represents research findings."""

    def __init__(self) -> None:
        self.usage: list[dict[str, Any]] = []

    def complete_json(self, *, agent: str, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        if agent == "research_director":
            return {
                "working_title": "Demonstration research brief",
                "research_question": "How can a small research team evaluate a proposed workflow transparently?",
                "objective": "Demonstrate a traceable research workflow without making empirical claims.",
                "scope": ["Workflow design", "Evidence traceability", "Reproducibility"],
                "search_queries": ["research workflow reproducibility", "evidence traceability research methods"],
                "assumptions": ["This is a software demonstration, not a scientific study."],
                "inclusion_criteria": ["Sources supplied as explicitly marked demo fixtures."],
                "exclusion_criteria": ["Treating demo records as real scholarly publications."],
            }
        if agent == "literature_scout":
            return {"selected_source_ids": ["DEMO-001", "DEMO-002"], "screening_notes": ["Fixture sources only; live literature search was not performed."], "excluded_source_ids": []}
        if agent == "evidence_analyst":
            return {"claims": [{"claim_id": "C-001", "claim": "A traceable workflow makes source handling inspectable.", "source_ids": ["DEMO-001"], "evidence_type": "illustrative_fixture", "confidence_label": "not_assessed", "limitations": ["Demonstration record; not evidence for a real-world conclusion."]}], "evidence_gaps": ["No live scholarly evidence was retrieved in demo mode."]}
        if agent == "methodologist":
            return {"design_assessment": "No empirical study design was supplied.", "strengths": ["The workflow records input hashes and deterministic checks."], "threats_to_validity": ["All records in demo mode are fixtures."], "recommended_checks": ["Repeat with a preregistered protocol and real sources."], "missing_information": ["Study population", "Sampling plan", "Analysis protocol"]}
        if agent == "synthesis_architect":
            return {"themes": [{"theme": "Traceability", "summary": "The example pipeline records the provenance of inputs and outputs.", "source_ids": ["DEMO-001"]}], "agreements": [], "contradictions": [], "research_gaps": ["Live source coverage and empirical validation are absent in this demonstration."], "contribution_opportunity": "Use this workflow to demonstrate how research artifacts can be inspected."}
        if agent == "figure_analyst":
            return {"figure_recommendations": [], "data_findings": [], "limitations": ["No empirical dataset was analysed; no figures or results are claimed."], "table_recommendations": ["A source register and evidence matrix would be useful in a real study."]}
        if agent == "manuscript_composer":
            return {
                "title": "An Auditable Workflow for Research Synthesis: Demonstration Manuscript",
                "abstract": "This demonstration illustrates a traceable workflow for organizing research materials and documenting evidence decisions. It uses fixture records only and reports no empirical findings.",
                "keywords": ["research workflow", "provenance", "demonstration"],
                "sections": [
                    {"heading": "Introduction", "content": "Research workflows benefit from explicit records of their inputs, decisions, and limitations. This demonstration is a software walkthrough, not a study of research outcomes."},
                    {"heading": "Workflow", "content": "The example separates source discovery, evidence mapping, methodological review, manuscript drafting, and integrity checks. The included source records are artificial fixtures and should not be cited as scholarship [DEMO-001]."},
                    {"heading": "Limitations", "content": "No live literature retrieval, empirical data collection, statistical testing, or expert peer review occurred. The example cannot support substantive conclusions."},
                    {"heading": "Conclusion", "content": "The demonstration shows the structure of the pipeline. A real research project must replace fixtures with verified primary sources and researcher-reviewed evidence."},
                ],
            }
        if agent == "adversarial_reviewer":
            return {"overall_assessment": "Demonstration only; not ready for scholarly submission.", "major_concerns": ["The cited record is a fixture, not a publication.", "No empirical validation is provided."], "minor_concerns": ["A target venue and formatting template were not specified."], "questions_for_authors": ["What is the real research design?", "Which verified sources support the central claims?"], "recommendation": "not_assessable"}
        if agent == "revision_editor":
            return {"title": "An Auditable Workflow for Research Synthesis: Demonstration Manuscript", "abstract": "This demonstration describes a traceable research workflow using fixture records only. It does not report empirical findings or support substantive scientific conclusions.", "keywords": ["research workflow", "provenance", "demonstration"], "sections": [
                {"heading": "Introduction", "content": "Research workflows should make their inputs, evidence decisions, and limitations visible. This document demonstrates software behavior rather than presenting a scientific result."},
                {"heading": "Workflow", "content": "The demonstration records source metadata, maps claims to source identifiers, and applies deterministic citation checks. The available records are artificial fixtures [DEMO-001]."},
                {"heading": "Limitations", "content": "No live literature retrieval, empirical data collection, statistical analysis, or independent expert review was conducted. The example does not justify general conclusions."},
                {"heading": "Conclusion", "content": "A real project should repeat the workflow using verified scholarly records, primary data where applicable, and researcher-led review."},
            ]}
        if agent == "integrity_auditor":
            return {"issues": [{"severity": "critical", "issue": "The source set contains demonstration fixtures only.", "recommendation": "Do not use this output as a scholarly manuscript."}], "ai_disclosure": "AI-assisted demonstration; human review required.", "submission_readiness": "not_ready", "notes": ["Demo mode is intentionally non-scholarly."]}
        return {"notes": [f"No demo response is configured for agent {agent}."]}
