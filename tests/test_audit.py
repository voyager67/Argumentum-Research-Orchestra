from argumentum.audit import audit_manuscript
from argumentum.models import Paper


def test_demo_references_are_blocked():
    report = audit_manuscript("Example [DEMO-001]", [Paper("DEMO-001", "Fixture", is_demo=True)], {"claims": []}, True)
    assert report["status"] == "BLOCKED"


def test_unresolved_source_id_is_critical():
    report = audit_manuscript("Claim [A-099]", [Paper("A-001", "Paper", doi="10.1000/x")], {"claims": []})
    assert report["status"] == "BLOCKED" and report["unknown_source_ids"] == ["A-099"]
