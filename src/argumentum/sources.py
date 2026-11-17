"""Read-only scholarly discovery adapters for OpenAlex, Crossref, Semantic Scholar, Europe PMC and arXiv."""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any, Protocol

from .config import Settings
from .models import Paper


class SourceError(RuntimeError):
    """A scholarly catalogue could not be queried or returned invalid data."""


class LiteratureSource(Protocol):
    name: str

    def search(self, query: str, limit: int) -> list[Paper]: ...


MAX_RESPONSE_BYTES = 8 * 1024 * 1024


def normalize_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    value = doi.strip().lower()
    value = re.sub(r"^https?://(dx\.)?doi\.org/", "", value)
    value = re.sub(r"^doi:\s*", "", value)
    return value or None


def normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def reconstruct_abstract(inverted_index: dict[str, list[int]] | None) -> str | None:
    """Reconstruct OpenAlex inverted-index abstracts without inventing missing tokens."""
    if not inverted_index:
        return None
    positions: dict[int, str] = {}
    for word, offsets in inverted_index.items():
        if not isinstance(offsets, list):
            continue
        for offset in offsets:
            if isinstance(offset, int) and offset >= 0:
                positions[offset] = word
    if not positions:
        return None
    return " ".join(positions[index] for index in sorted(positions))


def _year_from_crossref(item: dict[str, Any]) -> int | None:
    for field in ("published-print", "published-online", "published", "created"):
        date_parts = (item.get(field) or {}).get("date-parts") or []
        if date_parts and date_parts[0] and isinstance(date_parts[0][0], int):
            return date_parts[0][0]
    return None


def _openalex_paper(item: dict[str, Any]) -> Paper | None:
    title = item.get("title")
    if not title:
        return None
    authors = []
    for authorship in item.get("authorships") or []:
        author = (authorship.get("author") or {}).get("display_name")
        if author:
            authors.append(author)
    source = (item.get("primary_location") or {}).get("source") or {}
    venue = source.get("display_name")
    ids = item.get("ids") or {}
    doi = normalize_doi(item.get("doi") or ids.get("doi"))
    primary = item.get("primary_location") or {}
    url = primary.get("landing_page_url") or (f"https://doi.org/{doi}" if doi else item.get("id"))
    return Paper(
        source_id="",
        title=str(title),
        authors=authors[:12],
        year=item.get("publication_year"),
        venue=venue,
        doi=doi,
        url=url,
        abstract=reconstruct_abstract(item.get("abstract_inverted_index")),
        catalog="OpenAlex",
        citation_count=item.get("cited_by_count"),
    )


def _crossref_paper(item: dict[str, Any]) -> Paper | None:
    titles = item.get("title") or []
    if not titles or not titles[0]:
        return None
    authors = []
    for author in item.get("author") or []:
        name = " ".join(part for part in (author.get("given"), author.get("family")) if part)
        if name:
            authors.append(name)
    doi = normalize_doi(item.get("DOI"))
    abstract = item.get("abstract")
    if abstract:
        abstract = re.sub(r"<[^>]+>", " ", abstract)
        abstract = re.sub(r"\s+", " ", abstract).strip()
    return Paper(
        source_id="",
        title=str(titles[0]),
        authors=authors[:12],
        year=_year_from_crossref(item),
        venue=(item.get("container-title") or [None])[0],
        doi=doi,
        url=item.get("URL") or (f"https://doi.org/{doi}" if doi else None),
        abstract=abstract,
        catalog="Crossref",
        citation_count=item.get("is-referenced-by-count"),
    )


def _semantic_scholar_paper(item: dict[str, Any]) -> Paper | None:
    title = item.get("title")
    if not title:
        return None
    authors = [str(a.get("name")) for a in item.get("authors") or [] if a.get("name")]
    external_ids = item.get("externalIds") or {}
    doi = normalize_doi(external_ids.get("DOI"))
    arxiv_id = external_ids.get("ArXiv")
    return Paper(
        source_id="",
        title=str(title),
        authors=authors[:12],
        year=item.get("year"),
        venue=item.get("venue"),
        doi=doi,
        url=item.get("url")
        or (f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else (f"https://doi.org/{doi}" if doi else None)),
        abstract=item.get("abstract"),
        catalog="Semantic Scholar",
        citation_count=item.get("citationCount"),
    )


def _europe_pmc_paper(item: dict[str, Any]) -> Paper | None:
    title = item.get("title")
    if not title:
        return None
    doi = normalize_doi(item.get("doi"))
    pmcid = item.get("pmcid")
    pmid = item.get("pmid")
    url = (
        f"https://europepmc.org/articles/{pmcid}"
        if pmcid
        else (f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else (f"https://doi.org/{doi}" if doi else None))
    )
    authors = [author.strip() for author in str(item.get("authorString") or "").split(",") if author.strip()]
    year_value = item.get("firstPublicationDate") or item.get("pubYear")
    year_match = re.match(r"(\d{4})", str(year_value or ""))
    abstract = item.get("abstractText")
    if abstract:
        abstract = re.sub(r"<[^>]+>", " ", str(abstract))
        abstract = re.sub(r"\s+", " ", abstract).strip()
    try:
        citation_count = int(item["citedByCount"]) if item.get("citedByCount") is not None else None
    except (TypeError, ValueError):
        citation_count = None
    return Paper(
        source_id="",
        title=str(title),
        authors=authors[:12],
        year=int(year_match.group(1)) if year_match else None,
        venue=item.get("journalTitle"),
        doi=doi,
        url=url,
        abstract=abstract,
        catalog="Europe PMC",
        citation_count=citation_count,
    )


class _HttpClient:
    def __init__(self, timeout: int = 20, mailto: str | None = None):
        self.timeout = timeout
        self.mailto = mailto

    def _request(self, url: str, headers: dict[str, str] | None = None) -> bytes:
        request_headers = {
            "User-Agent": f"Argumentum-Research-Engine/1.0 (mailto:{self.mailto or 'not-provided'})",
            "Accept": "application/json, application/atom+xml, application/xml;q=0.9",
        }
        request_headers.update(headers or {})
        request = urllib.request.Request(url, headers=request_headers)
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    body = response.read(MAX_RESPONSE_BYTES + 1)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise SourceError("The literature API response exceeded the configured response-size limit.")
                return body
            except urllib.error.HTTPError as exc:
                if exc.code not in (408, 425, 429, 500, 502, 503, 504) or attempt == 2:
                    raise SourceError(f"Literature API returned HTTP {exc.code}.") from exc
                retry_after = exc.headers.get("Retry-After")
                try:
                    delay = min(float(retry_after), 10) if retry_after else min(2**attempt, 8)
                except ValueError:
                    delay = min(2**attempt, 8)
                time.sleep(delay)
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt == 2:
                    raise SourceError(f"Literature request failed: {type(exc).__name__}.") from exc
                time.sleep(min(2**attempt, 8))
        raise SourceError("Literature request failed after retries.")


class _JsonClient(_HttpClient):
    def get_json(self, url: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
        try:
            payload = json.loads(self._request(url, headers).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SourceError("The literature API returned invalid JSON.") from exc
        if not isinstance(payload, dict):
            raise SourceError("The literature API returned an unexpected response.")
        return payload


class OpenAlexSource(_JsonClient):
    name = "OpenAlex"

    def __init__(self, settings: Settings):
        super().__init__(timeout=25, mailto=settings.mailto)
        self.api_key = settings.openalex_api_key

    def search(self, query: str, limit: int) -> list[Paper]:
        params: dict[str, str | int] = {"search": query, "per_page": min(limit, 100), "sort": "relevance_score:desc"}
        if self.api_key:
            params["api_key"] = self.api_key
        if self.mailto:
            params["mailto"] = self.mailto
        payload = self.get_json("https://api.openalex.org/works?" + urllib.parse.urlencode(params))
        return [paper for item in payload.get("results", []) if (paper := _openalex_paper(item)) is not None]


class CrossrefSource(_JsonClient):
    name = "Crossref"

    def __init__(self, settings: Settings):
        super().__init__(timeout=25, mailto=settings.mailto)

    def search(self, query: str, limit: int) -> list[Paper]:
        params = {
            "query": query,
            "rows": min(limit, 100),
            "select": "DOI,title,author,published,published-print,published-online,container-title,URL,abstract,is-referenced-by-count",
        }
        if self.mailto:
            params["mailto"] = self.mailto
        payload = self.get_json("https://api.crossref.org/works?" + urllib.parse.urlencode(params))
        items = (payload.get("message") or {}).get("items") or []
        return [paper for item in items if (paper := _crossref_paper(item)) is not None]


class SemanticScholarSource(_JsonClient):
    name = "Semantic Scholar"

    def __init__(self, settings: Settings):
        super().__init__(timeout=25, mailto=settings.mailto)
        self.api_key = settings.semantic_scholar_api_key

    def search(self, query: str, limit: int) -> list[Paper]:
        params = {
            "query": query,
            "limit": min(limit, 100),
            "fields": "title,authors,year,venue,externalIds,url,abstract,citationCount",
        }
        headers = {"x-api-key": self.api_key} if self.api_key else None
        payload = self.get_json(
            "https://api.semanticscholar.org/graph/v1/paper/search?" + urllib.parse.urlencode(params), headers
        )
        return [paper for item in payload.get("data", []) if (paper := _semantic_scholar_paper(item)) is not None]


class EuropePmcSource(_JsonClient):
    name = "Europe PMC"

    def __init__(self, settings: Settings):
        super().__init__(timeout=25, mailto=settings.mailto)

    def search(self, query: str, limit: int) -> list[Paper]:
        params = {"query": query, "format": "json", "pageSize": min(limit, 100), "resultType": "core"}
        payload = self.get_json(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search?" + urllib.parse.urlencode(params)
        )
        results = (payload.get("resultList") or {}).get("result") or []
        return [paper for item in results if (paper := _europe_pmc_paper(item)) is not None]


class ArxivSource(_HttpClient):
    name = "arXiv"
    ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}

    def __init__(self, settings: Settings):
        super().__init__(timeout=35, mailto=settings.mailto)

    def search(self, query: str, limit: int) -> list[Paper]:
        params = {
            "search_query": f"all:{query}",
            "start": "0",
            "max_results": str(min(limit, 100)),
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
        body = self._request(
            "https://export.arxiv.org/api/query?" + urllib.parse.urlencode(params), {"Accept": "application/atom+xml"}
        )
        try:
            root = ET.fromstring(body)
        except ET.ParseError as exc:
            raise SourceError("arXiv returned invalid Atom XML.") from exc
        papers: list[Paper] = []
        for entry in root.findall("atom:entry", self.ATOM_NS):
            title = " ".join((entry.findtext("atom:title", default="", namespaces=self.ATOM_NS) or "").split())
            if not title:
                continue
            authors = [
                " ".join((node.findtext("atom:name", default="", namespaces=self.ATOM_NS) or "").split())
                for node in entry.findall("atom:author", self.ATOM_NS)
            ]
            published = entry.findtext("atom:published", default="", namespaces=self.ATOM_NS)
            year_match = re.match(r"(\d{4})", published or "")
            abs_url = entry.findtext("atom:id", default=None, namespaces=self.ATOM_NS)
            summary = entry.findtext("atom:summary", default=None, namespaces=self.ATOM_NS)
            arxiv_id = abs_url.rsplit("/", 1)[-1].split("v", 1)[0] if abs_url else None
            doi = None
            for link in entry.findall("atom:link", self.ATOM_NS):
                if link.attrib.get("title", "").lower() == "doi":
                    doi = normalize_doi(link.attrib.get("href"))
            papers.append(
                Paper(
                    source_id="",
                    title=title,
                    authors=[a for a in authors if a][:12],
                    year=int(year_match.group(1)) if year_match else None,
                    venue="arXiv preprint",
                    doi=doi,
                    url=abs_url or (f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else None),
                    abstract=" ".join((summary or "").split()) or None,
                    catalog="arXiv",
                    citation_count=None,
                )
            )
        return papers


@dataclass
class SearchOutcome:
    papers: list[Paper]
    warnings: list[str]
    queries: list[str]


def merge_papers(papers: list[Paper], limit: int) -> list[Paper]:
    """Deduplicate by DOI first, then conservative title/year/first-author matching."""
    merged: list[Paper] = []
    seen_doi: set[str] = set()
    seen_weak: set[tuple[str, int | None, str]] = set()
    for paper in papers:
        doi_key = normalize_doi(paper.doi)
        title_key = normalize_title(paper.title)
        first_author = paper.authors[0].lower().strip() if paper.authors else ""
        weak_key = (title_key, paper.year, first_author)
        if doi_key and doi_key in seen_doi:
            continue
        if not doi_key and weak_key in seen_weak:
            continue
        if doi_key:
            seen_doi.add(doi_key)
        if title_key:
            seen_weak.add(weak_key)
        merged.append(paper)
    merged.sort(key=lambda p: (p.year or 0, p.citation_count or 0), reverse=True)
    result = merged[:limit]
    for index, paper in enumerate(result, start=1):
        paper.source_id = f"A-{index:03d}"
    return result


def search_literature(queries: list[str], settings: Settings, limit: int) -> SearchOutcome:
    """Query five independent catalogues; preserve partial failures as explicit warnings."""
    clients: list[LiteratureSource] = [
        OpenAlexSource(settings),
        CrossrefSource(settings),
        SemanticScholarSource(settings),
        EuropePmcSource(settings),
        ArxivSource(settings),
    ]
    raw: list[Paper] = []
    warnings: list[str] = []
    per_query = max(5, min(20, limit))
    for query in queries:
        for client in clients:
            try:
                raw.extend(client.search(query, per_query))
            except SourceError as exc:
                warnings.append(f"{client.name} search failed for query {query!r}: {exc}")
    return SearchOutcome(papers=merge_papers(raw, limit), warnings=warnings, queries=queries)


DEMO_PAPERS = [
    Paper(
        source_id="DEMO-001",
        title="DEMO FIXTURE: Provenance Patterns in Research Workflows",
        authors=["Example Author"],
        year=2025,
        venue="Illustrative Demo Records",
        doi=None,
        url="https://example.invalid/demo-001",
        abstract="This fictional record exists solely to demonstrate how a source can be attached to an evidence record. It is not a scholarly publication.",
        catalog="Demo fixture",
        is_demo=True,
    ),
    Paper(
        source_id="DEMO-002",
        title="DEMO FIXTURE: Transparent Review of AI-Assisted Manuscripts",
        authors=["Sample Researcher"],
        year=2024,
        venue="Illustrative Demo Records",
        doi=None,
        url="https://example.invalid/demo-002",
        abstract="This fictional record is included to exercise the offline demonstration. It must not be cited as a real publication.",
        catalog="Demo fixture",
        is_demo=True,
    ),
]
