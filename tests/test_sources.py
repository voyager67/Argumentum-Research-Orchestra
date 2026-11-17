from argumentum.sources import normalize_doi, normalize_title, reconstruct_abstract


def test_doi_url_is_normalized():
    assert normalize_doi("https://doi.org/10.1000/ABC") == "10.1000/abc"


def test_title_punctuation_is_normalized():
    assert normalize_title("Research: Methods & Evidence!") == "research methods evidence"


def test_openalex_abstract_positions_are_reconstructed():
    assert reconstruct_abstract({"world": [1], "hello": [0]}) == "hello world"
