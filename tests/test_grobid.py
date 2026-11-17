import pytest

from argumentum.io_utils import GrobidError, _extract_grobid


def test_invalid_grobid_scheme_is_rejected(tmp_path):
    path = tmp_path / "paper.pdf"
    path.write_bytes(b"%PDF-1.4")
    with pytest.raises(GrobidError):
        _extract_grobid(path, "file:///tmp/grobid")
