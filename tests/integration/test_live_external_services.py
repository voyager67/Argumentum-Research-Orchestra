"""Explicitly opt-in live checks for inference, GROBID, and scholarly providers.

These tests make outbound requests only when their corresponding environment flags
are set. They are intentionally excluded from normal CI to avoid credential leaks,
provider quota consumption, and non-deterministic external dependencies.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


def test_live_openai_compatible_model_json_mode() -> None:
    if os.getenv("ARGUMENTUM_LIVE_MODEL_TESTS") != "1":
        pytest.skip("Set ARGUMENTUM_LIVE_MODEL_TESTS=1 to call the configured model endpoint")
    from argumentum.config import Settings
    from argumentum.providers import OpenAICompatibleProvider

    settings = Settings.from_env()
    result = OpenAICompatibleProvider(settings).complete_json(
        agent="integration_smoke",
        system_prompt='Return one JSON object with exactly one boolean field named "ready" set to true.',
        user_prompt='Return {"ready": true}.',
    )
    assert result.get("ready") is True


def test_live_grobid_extraction_of_operator_supplied_pdf() -> None:
    if os.getenv("ARGUMENTUM_LIVE_GROBID_TESTS") != "1":
        pytest.skip("Set ARGUMENTUM_LIVE_GROBID_TESTS=1 to test live GROBID extraction")
    pdf_value = os.getenv("ARGUMENTUM_LIVE_GROBID_TEST_PDF", "")
    grobid_url = os.getenv("ARGUMENTUM_GROBID_URL", "")
    if not pdf_value or not grobid_url:
        pytest.fail("Set ARGUMENTUM_LIVE_GROBID_TEST_PDF and ARGUMENTUM_GROBID_URL for this test")
    from argumentum.io_utils import _extract_grobid

    pdf_path = Path(pdf_value).expanduser().resolve()
    assert pdf_path.is_file(), "The supplied GROBID integration-test PDF must exist"
    text = _extract_grobid(pdf_path, grobid_url)
    assert text.strip()


def test_live_scholarly_metadata_catalogues() -> None:
    if os.getenv("ARGUMENTUM_LIVE_SCHOLARLY_TESTS") != "1":
        pytest.skip("Set ARGUMENTUM_LIVE_SCHOLARLY_TESTS=1 to call live scholarly metadata APIs")
    from argumentum.config import Settings
    from argumentum.sources import (
        ArxivSource,
        CrossrefSource,
        EuropePmcSource,
        OpenAlexSource,
        SemanticScholarSource,
    )

    settings = Settings.from_env()
    providers = [
        OpenAlexSource(settings),
        CrossrefSource(settings),
        SemanticScholarSource(settings),
        EuropePmcSource(settings),
        ArxivSource(settings),
    ]
    failures: list[str] = []
    for provider in providers:
        try:
            records = provider.search("reproducible machine learning evaluation", 2)
            assert isinstance(records, list)
        except Exception as exc:  # provider error detail may contain endpoint/credential data
            failures.append(f"{provider.name}:{type(exc).__name__}")
    assert not failures, "; ".join(failures)
