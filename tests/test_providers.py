import pytest

from argumentum.providers import ProviderError, parse_json_object


def test_parse_json_from_markdown_fence():
    assert parse_json_object('```json\n{"ok":true}\n```') == {"ok": True}


def test_parse_json_rejects_non_object():
    with pytest.raises(ProviderError):
        parse_json_object("[1,2]")
