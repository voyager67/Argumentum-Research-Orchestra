import pytest

from argumentum.harnesses import available_agent_harnesses, invoke_agent
from argumentum.providers import DemoProvider


def test_agent_harness_backends_are_registered():
    assert set(available_agent_harnesses()) == {"native", "langgraph", "crewai", "microsoft-agent-framework"}


def test_unknown_agent_harness_fails_closed():
    with pytest.raises(ValueError):
        invoke_agent("unknown", DemoProvider(), "research_director", {})
