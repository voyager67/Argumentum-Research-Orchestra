# Security policy

## Scope

This policy covers the Argumentum source code and its default local workflow. It does not guarantee the security of model providers, local inference servers, scholarly APIs, optional document parsers, or the host environment.

## Reporting

Do not open a public issue containing an exploitable vulnerability, secret, or private research material. Contact the repository maintainer privately through the security contact published on the Git hosting account. Include affected version/commit, impact, reproduction steps, and a suggested mitigation where possible.

## Security design

- API keys are read from environment variables and are not intentionally written to output artifacts.
- Input material ingestion is bounded by file count and byte limits.
- Output directories are not recursively deleted or overwritten.
- Model-generated code and document-embedded instructions are not executed.
- Literature discovery adapters are read-only and use bounded timeouts/retries.
- No agent is provided direct shell, browser, or unrestricted filesystem tools.

## User responsibilities

Keep secrets out of source control, protect local run directories, use trusted provider endpoints, restrict network access to local inference servers, update Python and optional parsing libraries, and obtain approval before sending sensitive research material to hosted services. Treat generated text, citations, URLs, and model outputs as untrusted until independently verified.
