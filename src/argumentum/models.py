"""Typed, dependency-free data models used by Argumentum."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class ResearchRequest:
    topic: str
    research_question: str
    discipline: str = "Interdisciplinary"
    study_type: str = "auto"
    audience: str = "graduate researchers"
    source_limit: int = 24
    search_queries: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.topic.strip():
            raise ValueError("topic must not be empty")
        if not self.research_question.strip():
            raise ValueError("research_question must not be empty")
        if not 1 <= self.source_limit <= 100:
            raise ValueError("source_limit must be between 1 and 100")


@dataclass
class Paper:
    source_id: str
    title: str
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    url: str | None = None
    abstract: str | None = None
    catalog: str = "unknown"
    citation_count: int | None = None
    is_demo: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class InputDocument:
    path: str
    text: str
    sha256: str
    size_bytes: int


@dataclass
class AgentResult:
    agent_id: str
    name: str
    status: str
    output: dict[str, Any]
    started_at: str
    finished_at: str
    elapsed_seconds: float
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
