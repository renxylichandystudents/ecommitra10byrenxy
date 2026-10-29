#!/bin/bash
set -e

cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "Membuat virtual environment Python..."
  python3 -m venv .venv
fi

source .venv/bin/activate

python - <<'PY'
import importlib.util
import subprocess
import sys

missing = [
    package
    for package in ("streamlit", "pandas", "numpy", "sklearn", "plotly")
    if importlib.util.find_spec(package) is None
]

if missing:
    print("Menginstall dependensi:", ", ".join(missing))
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
PY

echo ""
echo "Membuka aplikasi Thesis Mitra10 di http://localhost:8501"
echo "Biarkan jendela Terminal ini terbuka selama aplikasi dipakai."
echo ""

open "http://localhost:8501" 2>/dev/null || true
exec streamlit run app.py \
  --server.port 8501 \
  --server.headless true \
  --server.fileWatcherType none \
  --server.runOnSave false \
  --browser.gatherUsageStats false
