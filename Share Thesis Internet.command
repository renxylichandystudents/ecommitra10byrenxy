#!/bin/bash
set -e

cd "$(dirname "$0")"

echo "Menyiapkan aplikasi lokal di http://localhost:8501 ..."

if ! curl -fsS "http://localhost:8501" >/dev/null 2>&1; then
  if [ ! -d ".venv" ]; then
    python3 -m venv .venv
  fi

  source .venv/bin/activate

  python - <<'PY'
import importlib.util
import subprocess
import sys

if importlib.util.find_spec("streamlit") is None:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
PY

  streamlit run app.py \
    --server.port 8501 \
    --server.headless true \
    --server.fileWatcherType none \
    --server.runOnSave false \
    --browser.gatherUsageStats false \
    >/tmp/mitra10-thesis-streamlit.log 2>&1 &
  STREAMLIT_PID=$!
  trap 'kill "$STREAMLIT_PID" 2>/dev/null || true' EXIT

  for _ in {1..30}; do
    if curl -fsS "http://localhost:8501" >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
fi

echo ""
echo "Membuat link internet gratis sementara via localhost.run..."
echo "Salin URL https://... yang muncul di bawah ini."
echo "Biarkan jendela Terminal ini terbuka selama link internet dipakai."
echo ""

exec ssh -o StrictHostKeyChecking=accept-new -R 80:localhost:8501 nokey@localhost.run
