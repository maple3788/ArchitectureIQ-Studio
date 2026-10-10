#!/usr/bin/env bash
# Start Studio from this checkout. Never import a sibling worktree.
set -euo pipefail
studio_project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
studio_env_file="${STUDIO_ENV_FILE:-${studio_project_root}/.env}"
if [[ -f "${studio_env_file}" ]]; then
  set -a
  source "${studio_env_file}"
  set +a
fi
cd "${studio_project_root}"
studio_python="${STUDIO_PYTHON:-${studio_project_root}/.venv/bin/python}"
if [[ ! -x "${studio_python}" ]]; then
  echo "Studio Python is missing. Run: bash scripts/setup.sh" >&2
  exit 1
fi
export PYTHONPATH="${studio_project_root}/src:${studio_project_root}"
export STUDIO_STATE_ROOT="${STUDIO_STATE_ROOT:-${studio_project_root}/state}"
"${studio_python}" - <<'PY'
from pathlib import Path
import architecture_iq
expected = Path.cwd() / 'src/architecture_iq'
actual = Path(architecture_iq.__file__).resolve()
if not actual.is_relative_to(expected.resolve()):
    raise RuntimeError(f'Import provenance mismatch: {actual}')
print(f'Studio source: {Path.cwd()}', flush=True)
print(f'Engine imports: {actual}', flush=True)
PY
if [[ "${1:-}" == "--check" ]]; then
  "${studio_python}" - <<'PY'
from pathlib import Path
import json, os
import fastapi, uvicorn
from architecture_iq.kb.execution_host import execution_host_enabled
print(json.dumps({
    'project': 'ArchitectureIQ-Studio',
    'frontend_built': (Path.cwd() / 'frontend/workflow/dist/index.html').is_file(),
    'state_root': os.environ['STUDIO_STATE_ROOT'],
    'execution_enabled': execution_host_enabled(),
}, ensure_ascii=False))
PY
  exit 0
fi
exec "${studio_python}" -m uvicorn services.kb_workflow_api.app:app \
  --host "${STUDIO_HOST:-127.0.0.1}" --port "${STUDIO_PORT:-8094}" "$@"
