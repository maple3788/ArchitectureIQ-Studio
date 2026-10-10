#!/usr/bin/env bash
set -euo pipefail
studio_project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${studio_project_root}"
if [[ ! -x .venv/bin/python ]]; then
  uv venv --python "${STUDIO_PYTHON_VERSION:-3.12}" .venv
fi
# Linux inference/GT here uses the CPU benchmark engine; GLM is an external service.
if [[ "$(uname -s)" == "Linux" ]]; then
  uv pip install --python .venv/bin/python torch --index-url https://download.pytorch.org/whl/cpu
fi
uv pip install --python .venv/bin/python -e '.[studio,dev]'
npm --prefix frontend/workflow ci
npm --prefix frontend/workflow run build
bash tools/studio_server.sh --check
