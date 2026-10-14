#!/usr/bin/env bash
set -euo pipefail
# Uses the upstream project's validator/schema at checkout time.
# Apache Ossie 0.2.0.dev0 is a draft, so changes on main may break this demo.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TEMP="$(mktemp -d)"
trap 'rm -rf "$TEMP"' EXIT
git clone --depth=1 https://github.com/apache/ossie.git "$TEMP/ossie"
python -m pip install 'jsonschema>=4.20' 'sqlglot>=30.12' 'pyyaml>=6'
python "$TEMP/ossie/validation/validate.py" "$ROOT/models/gaming.yaml" --schema "$TEMP/ossie/core-spec/ossie-schema.json"
