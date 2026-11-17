from argumentum.server.api import ARTIFACT_ALLOWLIST,_token_digest

def test_artifact_names_are_allowlisted():
    assert "manuscript.md" in ARTIFACT_ALLOWLIST
    assert "../../.env" not in ARTIFACT_ALLOWLIST

def test_token_digest_is_sha256_hex():
    assert len(_token_digest("dummy-token"))==64
