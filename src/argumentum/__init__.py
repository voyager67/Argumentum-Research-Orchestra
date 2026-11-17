"""Argumentum: an evidence-traceable, researcher-controlled research workflow."""

from ._version import __version__
from .models import ResearchRequest
from .pipeline import ResearchPipeline

__all__ = ["ResearchPipeline", "ResearchRequest", "__version__"]
