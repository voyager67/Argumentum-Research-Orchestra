from argumentum.config import Settings
from argumentum.models import ResearchRequest
from argumentum.pipeline import ResearchPipeline
from argumentum.providers import DemoProvider

def test_offline_pipeline_exports_integrity_artifacts(tmp_path,sample_question):
    request=ResearchRequest(topic="Research provenance",research_question=sample_question)
    out=ResearchPipeline(DemoProvider(),Settings(),demo_mode=True).run(request,tmp_path/"demo")
    assert (out/"manuscript.md").is_file() and (out/"run_manifest.json").is_file()
    assert (out/"integrity_report.json").is_file()
