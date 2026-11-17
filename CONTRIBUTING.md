# Contributing

Thank you for helping improve Argumentum. Contributions should preserve the project's research-integrity boundary and keep the core implementation understandable.

## Before opening a change

- Explain the user-facing problem and expected behavior.
- Inspect the relevant stage contract and output format before changing it.
- Prefer a focused patch over broad refactoring.
- Add a regression test for bugs and edge cases.
- Never add fabricated benchmark results, sample research findings, credentials, or private materials.
- Keep generated-code execution, arbitrary shell access, and unrestricted agent tools out of the default workflow.

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\Activate.ps1
python -m pip install -e '.[dev]'
python -m pytest
ruff check .
```

## Pull request checklist

- [ ] Scope is limited and motivation is documented.
- [ ] Existing conventions and output compatibility are preserved or migration notes are supplied.
- [ ] Tests cover expected behavior and a relevant failure/edge case.
- [ ] No secrets, personal data, confidential research data, or generated run output is included.
- [ ] Documentation accurately describes actual behavior and limitations.
- [ ] No unverified performance or research-quality claims are added.

## Research quality issues

Report reproducible issues with the model/provider identified, the stage artifact, and whether the issue persists across repeated runs. Redact sensitive data and API keys.
