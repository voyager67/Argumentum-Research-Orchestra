"""Full-pipeline execution backends.

Each backend owns the complete ordered research-stage graph. Individual agent
calls remain plain Argumentum provider calls; framework adapters do not create
shadow agents or change the scientific protocol.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Never, Protocol


@dataclass(frozen=True)
class PipelineStage:
    name: str
    action: Callable[[dict[str, Any]], None]


class PipelineHarness(Protocol):
    name: str

    def execute(self, stages: list[PipelineStage], state: dict[str, Any]) -> dict[str, Any]: ...


class NativePipelineHarness:
    name = "native"

    def execute(self, stages: list[PipelineStage], state: dict[str, Any]) -> dict[str, Any]:
        for stage in stages:
            stage.action(state)
        return state


class LangGraphPipelineHarness:
    """Run every research stage as a node in one compiled LangGraph."""

    name = "langgraph"

    def execute(self, stages: list[PipelineStage], state: dict[str, Any]) -> dict[str, Any]:
        try:
            from langgraph.graph import END, START, StateGraph
        except ImportError as exc:
            raise RuntimeError("LangGraph pipeline requested; install `argumentum-research[langgraph]`") from exc

        from typing_extensions import TypedDict

        class PipelineState(TypedDict):
            payload: dict[str, Any]

        graph = StateGraph(PipelineState)
        node_names = [f"stage_{index:02d}_{stage.name}" for index, stage in enumerate(stages)]
        for node_name, stage in zip(node_names, stages, strict=True):

            def execute_stage(
                current: PipelineState, action: Callable[[dict[str, Any]], None] = stage.action
            ) -> dict[str, Any]:
                action(current["payload"])
                return {"payload": current["payload"]}

            graph.add_node(node_name, execute_stage)
        graph.add_edge(START, node_names[0])
        for current, following in zip(node_names, node_names[1:], strict=False):
            graph.add_edge(current, following)
        graph.add_edge(node_names[-1], END)
        result = graph.compile().invoke({"payload": state})
        payload = result.get("payload")
        if not isinstance(payload, dict):
            raise TypeError("LangGraph pipeline returned an invalid state payload")
        return payload


class CrewAIPipelineHarness:
    """Run the full stage sequence as a state-carrying CrewAI Flow."""

    name = "crewai"

    def execute(self, stages: list[PipelineStage], state: dict[str, Any]) -> dict[str, Any]:
        try:
            from crewai.flow import Flow, listen, start
        except ImportError as exc:
            raise RuntimeError("CrewAI pipeline requested; install `argumentum-research[crewai]`") from exc

        namespace: dict[str, Any] = {"__module__": __name__}
        previous_method: Callable[..., Any] | None = None
        method_names: list[str] = []
        for index, stage in enumerate(stages):
            method_name = f"run_{index:02d}_{stage.name}"

            def make_method(action: Callable[[dict[str, Any]], None]) -> Callable[..., dict[str, Any]]:
                def run_stage(self: Any, _previous: Any = None) -> dict[str, Any]:
                    payload = self.state.get("payload")
                    if not isinstance(payload, dict):
                        raise TypeError("CrewAI Flow lost the Argumentum pipeline state")
                    action(payload)
                    return payload

                return run_stage

            method = make_method(stage.action)
            method.__name__ = method_name
            decorated = start()(method) if previous_method is None else listen(previous_method)(method)
            namespace[method_name] = decorated
            previous_method = method
            method_names.append(method_name)

        flow_type = type("ArgumentumResearchFlow", (Flow,), namespace)
        flow = flow_type()
        if not hasattr(flow, "state") or not hasattr(flow.state, "__setitem__"):
            raise TypeError("Installed CrewAI Flow does not expose mapping state required by Argumentum")
        flow.state["payload"] = state
        flow.kickoff()
        result = flow.state.get("payload")
        if not isinstance(result, dict):
            raise TypeError("CrewAI Flow returned an invalid Argumentum pipeline state")
        return result


class MicrosoftAgentFrameworkPipelineHarness:
    """Build a typed sequential WorkflowBuilder graph for the full research run."""

    name = "microsoft-agent-framework"

    def execute(self, stages: list[PipelineStage], state: dict[str, Any]) -> dict[str, Any]:
        try:
            from agent_framework import WorkflowBuilder, WorkflowContext, executor
        except ImportError as exc:
            raise RuntimeError(
                "Microsoft Agent Framework pipeline requested; install `argumentum-research[microsoft-agent-framework]`"
            ) from exc

        executors: list[Any] = []
        for index, stage in enumerate(stages):
            is_last = index == len(stages) - 1

            def make_executor(action: Callable[[dict[str, Any]], None], terminal: bool, name: str) -> Any:
                if terminal:

                    @executor(id=name)
                    async def execute_terminal(
                        payload: dict[str, Any], context: WorkflowContext[Never, dict[str, Any]]
                    ) -> None:
                        action(payload)
                        await context.yield_output(payload)

                    return execute_terminal

                @executor(id=name)
                async def execute_stage(payload: dict[str, Any], context: WorkflowContext[dict[str, Any]]) -> None:
                    action(payload)
                    await context.send_message(payload)

                return execute_stage

            executors.append(make_executor(stage.action, is_last, f"argumentum_{index:02d}_{stage.name}"))

        builder = WorkflowBuilder(start_executor=executors[0], output_from=[executors[-1]])
        for current, following in zip(executors, executors[1:], strict=False):
            builder.add_edge(current, following)
        workflow = builder.build()

        async def execute() -> dict[str, Any]:
            result = await workflow.run(state)
            outputs = result.get_outputs()
            if not outputs or not isinstance(outputs[-1], dict):
                raise TypeError("Microsoft Agent Framework returned no final pipeline state")
            return outputs[-1]

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(execute())
        raise RuntimeError(
            "Microsoft Agent Framework pipeline adapter is synchronous; call it from a worker thread, "
            "not from an active event loop"
        )


_PIPELINE_HARNESSES: dict[str, Callable[[], PipelineHarness]] = {
    "native": NativePipelineHarness,
    "langgraph": LangGraphPipelineHarness,
    "crewai": CrewAIPipelineHarness,
    "microsoft-agent-framework": MicrosoftAgentFrameworkPipelineHarness,
}


def available_pipeline_harnesses() -> tuple[str, ...]:
    return tuple(_PIPELINE_HARNESSES)


def execute_pipeline(
    harness_name: str,
    stages: list[PipelineStage],
    state: dict[str, Any],
) -> dict[str, Any]:
    """Execute all stages through one selected framework workflow."""
    normalized = harness_name.strip().lower()
    factory = _PIPELINE_HARNESSES.get(normalized)
    if factory is None:
        raise ValueError(
            f"Unknown pipeline harness {harness_name!r}; choose one of {', '.join(available_pipeline_harnesses())}"
        )
    if not stages:
        raise ValueError("A research workflow must contain at least one stage")
    if len({stage.name for stage in stages}) != len(stages):
        raise ValueError("Pipeline stage names must be unique")
    return factory().execute(stages, state)
