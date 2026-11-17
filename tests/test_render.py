from argumentum.models import Paper
from argumentum.render import render_bibtex, render_latex, render_manuscript


def test_demo_notice_is_rendered_in_exports():
    paper = Paper("DEMO-001", "Fixture title", is_demo=True)
    draft = {
        "title": "Demo",
        "abstract": "Example",
        "sections": [{"heading": "Methods", "content": "A note [DEMO-001]"}],
    }
    assert "DEMO FIXTURE" in render_manuscript(draft, [paper])
    assert "DEMO ONLY" in render_latex(draft, [paper])
    assert "DO NOT CITE" in render_bibtex([paper])
