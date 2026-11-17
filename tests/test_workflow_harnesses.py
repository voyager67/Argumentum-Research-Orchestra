import pytest
from argumentum.workflows import PipelineStage,available_pipeline_harnesses,execute_pipeline

def test_native_harness_executes_ordered_stages():
    seen=[];stages=[PipelineStage("first",lambda state:seen.append(1)),PipelineStage("second",lambda state:seen.append(2))]
    execute_pipeline("native",stages,{})
    assert seen==[1,2]

def test_all_pipeline_backends_are_registered():
    assert set(available_pipeline_harnesses())=={"native","langgraph","crewai","microsoft-agent-framework"}

def test_unknown_pipeline_backend_is_rejected():
    with pytest.raises(ValueError):execute_pipeline("missing",[PipelineStage("x",lambda state:None)],{})
