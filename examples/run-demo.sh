#!/usr/bin/env sh
set -eu
argumentum run \
  --topic "Research workflow demonstration" \
  --question "How can a research workflow document provenance and evidence boundaries?" \
  --demo \
  --output-dir ./argumentum-demo-output
