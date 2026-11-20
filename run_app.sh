#!/usr/bin/env bash
# Run the complete Vendor Risk Copilot app on macOS / Linux.
#   ./run_app.sh          UI on http://localhost:8501 (API in-process)
#   ./run_app.sh both     API on :8000 (docs at /docs) + UI on :8501
#   ./run_app.sh api      API only
#   ./run_app.sh test     full offline test suite
set -euo pipefail
cd "$(dirname "$0")"
MODE="${1:-ui}"
[ -x .venv/bin/python ] || { echo "Creating virtual environment .venv ..."; python3 -m venv .venv; }
PY=.venv/bin/python
echo "Installing app dependencies (first run takes a few minutes) ..."
"$PY" -m pip install --disable-pip-version-check -q -r docker/requirements-app.txt pytest
[ -f .env ] || { cp .env.example .env; echo "Created .env from .env.example (no keys needed for the offline demo)."; }
echo "Preparing the local database (data/processed/copilot.sqlite) ..."
"$PY" -m scripts.load_db
case "$MODE" in
  test) "$PY" -m pytest -q ;;
  api)  "$PY" -m uvicorn app.api.main:app --port 8000 ;;
  both) "$PY" -m uvicorn app.api.main:app --port 8000 & API_PID=$!; trap 'kill $API_PID' EXIT; sleep 4
        API_URL=http://localhost:8000 "$PY" -m streamlit run app/ui/streamlit_app.py --server.port 8501 ;;
  *)    "$PY" -m streamlit run app/ui/streamlit_app.py --server.port 8501 ;;
esac
