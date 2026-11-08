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

# Aplikasi lama yang masih jalan di port 8501 memakai kode lama (modul sudah termuat di memori),
# jadi dihentikan dulu agar kode terbaru yang dipakai.
OLD_PIDS=$(lsof -ti tcp:8501 2>/dev/null || true)
if [ -n "$OLD_PIDS" ]; then
  echo "Menghentikan aplikasi lama di port 8501..."
  kill $OLD_PIDS 2>/dev/null || true
  sleep 2
fi

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
