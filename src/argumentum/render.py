"""Deterministic renderers for manuscript and reference artifacts."""

from __future__ import annotations

import re
from typing import Any

from .models import Paper


def clean_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def render_manuscript(content: dict[str, Any], papers: list[Paper]) -> str:
    title = clean_text(content.get("title")) or "Untitled research manuscript"
    abstract = clean_text(content.get("abstract")) or "[Abstract not supplied by the drafting agent. Human completion required.]"
    keywords = content.get("keywords") if isinstance(content.get("keywords"), list) else []
    sections = content.get("sections") if isinstance(content.get("sections"), list) else []
    lines = [f"# {title}", "", "> **Working draft.** This document was AI-assisted. All claims, methods, citations, results, ethics statements, and submission requirements require researcher verification.", "", "## Abstract", "", abstract]
    if keywords:
        lines.extend(["", "**Keywords:** " + "; ".join(str(item) for item in keywords if str(item).strip())])
    for section in sections:
        if not isinstance(section, dict):
            continue
        heading = clean_text(section.get("heading")) or "Untitled section"
        body = clean_text(section.get("content")) or "[No section content supplied. Human completion required.]"
        lines.extend(["", f"## {heading}", "", body])
    lines.extend(["", "## References", ""])
    if not papers:
        lines.append("No scholarly sources were retrieved. Do not use this draft as a literature-grounded manuscript.")
    else:
        for paper in papers:
            authors = ", ".join(paper.authors) if paper.authors else "Author metadata unavailable"
            year = str(paper.year) if paper.year else "n.d."
            venue = f" *{paper.venue}*." if paper.venue else ""
            doi = f" https://doi.org/{paper.doi}" if paper.doi else (f" {paper.url}" if paper.url else "")
            label = " **[DEMO FIXTURE — NOT A REAL PUBLICATION]**" if paper.is_demo else ""
            lines.append(f"- [{paper.source_id}] {authors} ({year}). {paper.title}.{venue}{doi}{label}")
    return "\n".join(lines).rstrip() + "\n"


def _bib_escape(value: str) -> str:
    replacements = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}"}
    return "".join(replacements.get(char, char) for char in value)


def render_bibtex(papers: list[Paper]) -> str:
    entries: list[str] = []
    for paper in papers:
        key = paper.source_id.replace("-", "")
        year = str(paper.year) if paper.year else ""
        fields = [f"  title = {{{_bib_escape(paper.title)}}}"]
        if paper.authors:
            fields.append(f"  author = {{{_bib_escape(' and '.join(paper.authors))}}}")
        if year:
            fields.append(f"  year = {{{year}}}")
        if paper.venue:
            fields.append(f"  journal = {{{_bib_escape(paper.venue)}}}")
        if paper.doi:
            fields.append(f"  doi = {{{_bib_escape(paper.doi)}}}")
        if paper.url:
            fields.append(f"  url = {{{_bib_escape(paper.url)}}}")
        if paper.is_demo:
            fields.append("  note = {DEMO FIXTURE - NOT A REAL PUBLICATION. DO NOT CITE}")
        entries.append("@misc{" + key + ",\n" + ",\n".join(fields) + "\n}")
    return "\n\n".join(entries) + ("\n" if entries else "")


def render_peer_review(review: dict[str, Any]) -> str:
    lines = ["# Adversarial Peer Review", "", "> Automated critique for author assistance only. This is not independent human peer review.", "", "## Overall assessment", "", clean_text(review.get("overall_assessment")) or "No assessment returned."]
    for key, heading in (("major_concerns", "Major concerns"), ("minor_concerns", "Minor concerns"), ("questions_for_authors", "Questions for authors")):
        lines.extend(["", f"## {heading}", ""])
        items = review.get(key) if isinstance(review.get(key), list) else []
        lines.extend([f"- {item}" for item in items] or ["- None returned."])
    lines.extend(["", "## Recommendation", "", clean_text(review.get("recommendation")) or "Not returned."])
    return "\n".join(lines) + "\n"


def render_evidence_ledger(ledger: dict[str, Any]) -> str:
    claims = ledger.get("claims", []) if isinstance(ledger, dict) else []
    rows = ["# Claim-to-source evidence ledger", "", "| Claim ID | Claim | Source IDs | Evidence type | Qualitative label | Limitations |", "|---|---|---|---|---|---|"]
    for item in claims if isinstance(claims, list) else []:
        if not isinstance(item, dict):
            continue
        source_ids = item.get("source_ids", [])
        limitations = item.get("limitations", [])
        cells = [
            item.get("claim_id", ""),
            item.get("claim", ""),
            ", ".join(str(value) for value in source_ids) if isinstance(source_ids, list) else "",
            item.get("evidence_type", ""),
            item.get("confidence_label", ""),
            "; ".join(str(value) for value in limitations) if isinstance(limitations, list) else "",
        ]
        rows.append("| " + " | ".join(re.sub(r"[\r\n|]+", " ", str(cell)) for cell in cells) + " |")
    rows.extend(["", "Qualitative labels are model-generated triage prompts, not calibrated probabilities or validated evidence grades."])
    return "\n".join(rows) + "\n"

LATEX_SPECIAL = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def _latex_escape(value: str) -> str:
    return "".join(LATEX_SPECIAL.get(char, char) for char in value)


def _latex_inline(value: str, papers: list[Paper]) -> str:
    """Convert a deliberately small, safe subset of Markdown inline syntax."""
    known = {paper.source_id: paper for paper in papers}
    pattern = re.compile(
        r"(\[(?:A|DEMO)-\d{3}\]|\[([^\]]+)\]\((https?://[^)]+)\)|\*\*(.+?)\*\*|\*(.+?)\*|`(.+?)`)")
    result: list[str] = []
    cursor = 0
    for match in pattern.finditer(value):
        result.append(_latex_escape(value[cursor:match.start()]))
        token = match.group(0)
        if re.fullmatch(r"\[(?:A|DEMO)-\d{3}\]", token):
            source_id = token[1:-1]
            if source_id in known and not known[source_id].is_demo:
                result.append(r"\cite{" + source_id.replace("-", "") + "}")
            else:
                result.append(_latex_escape(token))
        elif match.group(2) is not None and match.group(3) is not None:
            result.append(r"\href{" + _latex_escape(match.group(3)) + "}{" + _latex_escape(match.group(2)) + "}")
        elif match.group(4) is not None:
            result.append(r"\textbf{" + _latex_escape(match.group(4)) + "}")
        elif match.group(5) is not None:
            result.append(r"\emph{" + _latex_escape(match.group(5)) + "}")
        elif match.group(6) is not None:
            result.append(r"\texttt{" + _latex_escape(match.group(6)) + "}")
        cursor = match.end()
    result.append(_latex_escape(value[cursor:]))
    return "".join(result)


def _latex_body(value: str, papers: list[Paper]) -> str:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", value.strip()) if part.strip()]
    rendered: list[str] = []
    for paragraph in paragraphs:
        lines = paragraph.splitlines()
        if all(line.lstrip().startswith("- ") for line in lines):
            items = [r"\item " + _latex_inline(line.lstrip()[2:], papers) for line in lines]
            rendered.append("\\begin{itemize}\n" + "\n".join(items) + "\n\\end{itemize}")
        elif all(re.match(r"^\s*\d+[.)]\s+", line) for line in lines):
            items = [r"\item " + _latex_inline(re.sub(r"^\s*\d+[.)]\s+", "", line), papers) for line in lines]
            rendered.append("\\begin{enumerate}\n" + "\n".join(items) + "\n\\end{enumerate}")
        else:
            rendered.append(_latex_inline(" ".join(line.strip() for line in lines), papers))
    return "\n\n".join(rendered)


def render_latex(content: dict[str, Any], papers: list[Paper]) -> str:
    """Render a generic article-class LaTeX draft; target-venue compliance is out of scope."""
    title = _latex_escape(clean_text(content.get("title")) or "Untitled research manuscript")
    abstract = _latex_body(clean_text(content.get("abstract")) or "Abstract completion required by the authors.", papers)
    keywords = content.get("keywords") if isinstance(content.get("keywords"), list) else []
    sections = content.get("sections") if isinstance(content.get("sections"), list) else []
    lines = [
        r"\documentclass[11pt]{article}",
        r"\usepackage[utf8]{inputenc}",
        r"\usepackage[T1]{fontenc}",
        r"\usepackage{geometry}",
        r"\usepackage{graphicx}",
        r"\usepackage{booktabs}",
        r"\usepackage{hyperref}",
        r"\geometry{margin=1in}",
        r"\title{" + title + "}",
        r"\author{Author names and affiliations to be completed}",
        r"\date{\today}",
        r"\begin{document}",
        r"\maketitle",
    ]
    if any(paper.is_demo for paper in papers):
        lines.extend([
            r"\noindent\fbox{\parbox{0.95\linewidth}{\textbf{DEMO ONLY: Fictional source records. Do not cite or submit this output.}}}",
        ])
    lines.extend([
        r"\begin{abstract}",
        abstract,
        r"\end{abstract}",
    ])
    if keywords:
        clean_keywords = "; ".join(str(item) for item in keywords if str(item).strip())
        lines.extend([r"\noindent\textbf{Keywords:} " + _latex_escape(clean_keywords)])
    for section in sections:
        if not isinstance(section, dict):
            continue
        heading = clean_text(section.get("heading")) or "Untitled section"
        body = clean_text(section.get("content")) or "Section completion required by the authors."
        lines.extend(["", r"\section{" + _latex_escape(heading) + "}", _latex_body(body, papers)])
    lines.extend(["", r"\begin{thebibliography}{99}"])
    for paper in papers:
        key = paper.source_id.replace("-", "")
        authors = "; ".join(paper.authors) if paper.authors else "Author metadata unavailable"
        year = str(paper.year) if paper.year else "n.d."
        entry = r"\bibitem{" + key + "} " + _latex_escape(authors) + f" ({year}). " + _latex_escape(paper.title) + "."
        if paper.venue:
            entry += r" \emph{" + _latex_escape(paper.venue) + "}."
        if paper.doi:
            entry += r" \href{https://doi.org/" + _latex_escape(paper.doi) + "}{doi: " + _latex_escape(paper.doi) + "}."
        elif paper.url:
            entry += r" \url{" + paper.url.replace("%", r"\%") + "}."
        if paper.is_demo:
            entry += r" \textbf{DEMO FIXTURE - NOT A REAL PUBLICATION. DO NOT CITE.}"
        lines.append(entry)
    lines.extend([r"\end{thebibliography}", r"\end{document}", ""])
    return "\n".join(lines)
