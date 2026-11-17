.PHONY: install test lint ui-check check demo

install:
	python -m pip install -e '.[dev,server,all-documents]'

test:
	python -m pytest -q

lint:
	./scripts/lint.sh

ui-check:
	python scripts/check-ui-js.py

check: lint ui-check test

demo:
	argumentum run --topic "Research workflow demonstration" --question "How can research provenance be represented in an auditable workflow?" --demo --output-dir ./runs/demo
