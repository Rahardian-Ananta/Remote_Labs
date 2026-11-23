#!/usr/bin/env bash
# scripts/run_local.sh
# ─────────────────────────────────────────────────────────────────────────────
# Menjalankan 3 executor (port 9001-9003) + 1 scheduler (port 8000) secara lokal
# tanpa Docker. Bersihkan semua proses anak saat Ctrl+C ditekan.
#
# Penggunaan: bash scripts/run_local.sh
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Aktifkan virtualenv jika ada, atau jalankan setup jika belum ada
if [[ -f "$PROJECT_ROOT/.venv/bin/activate" ]]; then
    source "$PROJECT_ROOT/.venv/bin/activate"
elif [[ -f "$PROJECT_ROOT/setup.sh" ]]; then
    echo "Virtual environment belum ada. Menjalankan setup.sh..."
    bash "$PROJECT_ROOT/setup.sh"
    source "$PROJECT_ROOT/.venv/bin/activate"
fi

export PYTHONPATH="$PROJECT_ROOT"
export PYTHONUNBUFFERED=1

DB_DIR="$PROJECT_ROOT/run_data"
mkdir -p "$DB_DIR"

BOOTSTRAPS="http://127.0.0.1:9001,http://127.0.0.1:9002,http://127.0.0.1:9003"
EXECUTORS_ENV="exec1=http://127.0.0.1:9001,exec2=http://127.0.0.1:9002,exec3=http://127.0.0.1:9003"

PIDS=()

cleanup() {
    echo ""
    echo "⏹  Menghentikan semua proses..."
    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
    wait 2>/dev/null
    echo "✅ Selesai."
    exit 0
}
trap cleanup SIGINT SIGTERM

# ── Executor 1 ─────────────────────────────────────────────────────────────
echo "🚀 Memulai Executor 1 (port 9001)..."
EXECUTOR_ID=exec1 \
EXECUTOR_HOST=127.0.0.1 \
EXECUTOR_PORT=9001 \
EXECUTOR_CAPACITY=4 \
MAX_RANKS=4 \
EXECUTOR_DB_PATH="$DB_DIR/exec1.db" \
BOOTSTRAP_NODES="$BOOTSTRAPS" \
CHORD_MAINTENANCE_SEC=5.0 \
    python -m uvicorn executor.main:app \
        --host 127.0.0.1 --port 9001 --log-level warning &
PIDS+=($!)

# ── Executor 2 ─────────────────────────────────────────────────────────────
echo "🚀 Memulai Executor 2 (port 9002)..."
EXECUTOR_ID=exec2 \
EXECUTOR_HOST=127.0.0.1 \
EXECUTOR_PORT=9002 \
EXECUTOR_CAPACITY=4 \
MAX_RANKS=4 \
EXECUTOR_DB_PATH="$DB_DIR/exec2.db" \
BOOTSTRAP_NODES="$BOOTSTRAPS" \
CHORD_MAINTENANCE_SEC=5.0 \
    python -m uvicorn executor.main:app \
        --host 127.0.0.1 --port 9002 --log-level warning &
PIDS+=($!)

# ── Executor 3 ─────────────────────────────────────────────────────────────
echo "🚀 Memulai Executor 3 (port 9003)..."
EXECUTOR_ID=exec3 \
EXECUTOR_HOST=127.0.0.1 \
EXECUTOR_PORT=9003 \
EXECUTOR_CAPACITY=4 \
MAX_RANKS=4 \
EXECUTOR_DB_PATH="$DB_DIR/exec3.db" \
BOOTSTRAP_NODES="$BOOTSTRAPS" \
CHORD_MAINTENANCE_SEC=5.0 \
    python -m uvicorn executor.main:app \
        --host 127.0.0.1 --port 9003 --log-level warning &
PIDS+=($!)

# Tunggu executor siap
echo "⏳ Menunggu executor siap..."
sleep 8

# ── Scheduler ─────────────────────────────────────────────────────────────
echo "🚀 Memulai Scheduler (port 8000)..."
SCHEDULER_HOST=127.0.0.1 \
SCHEDULER_PORT=8000 \
EXECUTORS="$EXECUTORS_ENV" \
DB_PATH="$DB_DIR/scheduler.db" \
HEALTH_INTERVAL_SEC=5.0 \
CACHE_CAPACITY=500 \
CACHE_LEASE_SEC=60.0 \
    python -m uvicorn scheduler.main:app \
        --host 127.0.0.1 --port 8000 --log-level warning &
PIDS+=($!)

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  ✅ RemoteLab v2.0 berjalan"
echo "  🌐 UI: http://localhost:8000"
echo "  📡 Executor: :9001  :9002  :9003"
echo "  Tekan Ctrl+C untuk menghentikan semua proses"
echo "═══════════════════════════════════════════════════════"

wait

