"""Execution adapters for specialist agent calls."""
from __future__ import annotations
import asyncio
from typing import Any, Protocol
from .agents import run_agent
from .providers import ModelProvider

class AgentHarness(Protocol):
    name: str
    def invoke(self, provider: ModelProvider, agent_id: str, context: dict[str, Any]) -> dict[str, Any]: ...

class NativeHarness:
    name = "native"
    def invoke(self, provider: ModelProvider, agent_id: str, context: dict[str, Any]) -> dict[str, Any]:
        return run_agent(provider, agent_id, context)

class LangGraphHarness:
    name = "langgraph"
    def invoke(self, provider: ModelProvider, agent_id: str, context: dict[str, Any]) -> dict[str, Any]:
        try: from langgraph.graph import END, START, StateGraph
        except ImportError as exc: raise RuntimeError("Install argumentum-research[langgraph]") from exc
        from typing_extensions import TypedDict
        class State(TypedDict): result: dict[str, Any] | None
        def run(state: State) -> dict[str, Any]: return {"result": run_agent(provider, agent_id, context)}
        graph=StateGraph(State);graph.add_node("specialist",run);graph.add_edge(START,"specialist");graph.add_edge("specialist",END)
        result=graph.compile().invoke({"result":None}).get("result")
        if not isinstance(result,dict): raise TypeError("LangGraph returned invalid output")
        return result

class CrewAIHarness:
    name = "crewai"
    def invoke(self, provider: ModelProvider, agent_id: str, context: dict[str, Any]) -> dict[str, Any]:
        try: from crewai.flow import Flow, start
        except ImportError as exc: raise RuntimeError("Install argumentum-research[crewai]") from exc
        class Invocation(Flow):
            @start()
            def execute(self) -> dict[str, Any]: return run_agent(provider,agent_id,context)
        result=Invocation().kickoff()
        if not isinstance(result,dict): raise TypeError("CrewAI returned invalid output")
        return result

class MicrosoftAgentFrameworkHarness:
    name = "microsoft-agent-framework"
    def invoke(self, provider: ModelProvider, agent_id: str, context: dict[str, Any]) -> dict[str, Any]:
        try: from agent_framework import workflow
        except ImportError as exc: raise RuntimeError("Install argumentum-research[microsoft-agent-framework]") from exc
        @workflow(name=f"argumentum-{agent_id}",description="Run an Argumentum specialist stage")
        async def flow() -> dict[str, Any]: return run_agent(provider,agent_id,context)
        instance=flow.build()
        try: asyncio.get_running_loop()
        except RuntimeError: result=asyncio.run(instance.run())
        else: raise RuntimeError("Synchronous adapter cannot run in active event loop")
        outputs=result.get_outputs()
        if not outputs or not isinstance(outputs[0],dict): raise TypeError("Microsoft workflow returned invalid output")
        return outputs[0]

_FACTORIES={"native":NativeHarness,"langgraph":LangGraphHarness,"crewai":CrewAIHarness,"microsoft-agent-framework":MicrosoftAgentFrameworkHarness}
def available_agent_harnesses()->tuple[str,...]: return tuple(_FACTORIES)
def invoke_agent(harness_name:str,provider:ModelProvider,agent_id:str,context:dict[str,Any])->dict[str,Any]:
    factory=_FACTORIES.get(harness_name.strip().lower())
    if factory is None: raise ValueError(f"Unknown agent harness {harness_name!r}; choose from {', '.join(_FACTORIES)}")
    return factory().invoke(provider,agent_id,context)
