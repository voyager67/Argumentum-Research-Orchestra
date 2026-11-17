# Full research-workflow harnesses

Argumentum owns one research protocol and exposes four selectable orchestration backends for the **complete ordered workflow**. Each backend executes the same 13 explicit pipeline stages against a shared, bounded run-state contract. The framework does not redefine the scientific process, prompts, citation rules, source-screening requirements, or artifact format.

## Select a workflow harness

Set `ARGUMENTUM_PIPELINE_HARNESS` in the environment, or use the CLI `--harness` flag:

```bash
argumentum run \
  --topic "Evidence synthesis in scientific retrieval" \
  --question "How do evaluation protocols differ across scientific retrieval systems?" \
  --harness langgraph
```

Supported values:

| Harness | Whole-pipeline implementation | Intended use |
|---|---|---|
| `native` | Dependency-light sequential stage runner | Default and lowest operational overhead |
| `langgraph` | One compiled `StateGraph` with a node for every stage | Graph-native execution and framework-level tracing/checkpoint extensions |
| `crewai` | One state-carrying `Flow` with chained listeners | Flow-oriented orchestration and state inspection |
| `microsoft-agent-framework` | One typed `WorkflowBuilder` graph of sequential executors | Workflow events, typed message routing and future checkpoint integration |

Install only the selected optional dependency:

```bash
python -m pip install 'argumentum-research[langgraph]'
# or
python -m pip install 'argumentum-research[crewai]'
# or
python -m pip install 'argumentum-research[microsoft-agent-framework]'
```

The adapters are deliberately optional. The native harness remains available without those dependency trees. Optional framework versions are constrained in `pyproject.toml`; validate them in a clean environment before institutional rollout.

## Shared stage protocol

Each backend receives the same `PipelineStage` list and a mutable run-state object. Stage actions are ordered and stateful:

1. Prepare researcher materials and bounded excerpts.
2. Frame the research question and propose queries.
3. Discover scholarly records.
4. Screen the source catalogue and establish the citable shortlist.
5. Analyse evidence.
6. Review methodology.
7. Synthesise themes, disagreements and gaps.
8. Review supplied data and figure opportunities.
9. Compose the first manuscript draft.
10. Conduct adversarial review.
11. Revise only evidence-supported claims.
12. Run research-integrity review and deterministic citation checks.
13. Export manuscript, evidence, review and provenance artifacts.

The pipeline still refuses to treat unscreened discovered records as citable. The final integrity report distinguishes deterministic identifier checks from model-generated critique; neither is a substitute for full-text verification or expert peer review.

## Boundaries and trade-offs

- This is **workflow-level orchestration support**, not a claim that all frameworks have identical persistence, retry, observability, streaming or checkpoint semantics.
- The current Argumentum stages are sequential because later prompts depend on earlier research decisions. No artificial parallel fan-out is added just to make the graph look sophisticated.
- The full research run remains the recovery unit in the self-hosted RQ worker. Framework-specific stage checkpoints are not yet wired into the PostgreSQL recovery protocol; a worker retry may rerun the pipeline rather than resume at an individual framework node.
- Model/provider calls remain inside Argumentum's provider contract. Frameworks are not granted shell, browser, filesystem or general tool permissions.
- The Microsoft Agent Framework adapter uses its Python workflow API. Check the framework's current API maturity and pin versions before production adoption.

## Verification

`tests/test_workflow_harnesses.py` tests the full stage graph and state handoff for all four harnesses using contract-compatible test doubles. CI has separate optional-dependency jobs that install each framework and run an end-to-end demo pipeline against the actual package. A local skip means that framework was not installed or exercised locally; it is not an integration pass.

Official framework references:

- [LangGraph graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)
- [CrewAI Flow state and orchestration](https://docs.crewai.com/en/concepts/flows)
- [Microsoft Agent Framework workflow builder and execution](https://learn.microsoft.com/en-us/agent-framework/concepts/workflows/builder-and-execution)
