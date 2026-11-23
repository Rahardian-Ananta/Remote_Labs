#!/usr/bin/env bash
# setup.sh — RemoteLab v2.0 Setup Otomatis Lingkungan Kerja (Linux / macOS)
# ─────────────────────────────────────────────────────────────────────────────
# Penggunaan:
#   chmod +x setup.sh && ./setup.sh
# ─────────────────────────────────────────────────────────────────────────────

set -e

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${CYAN}============================================================${NC}"
echo -e "${GREEN}   🚀 RemoteLab v2.0 — Setup Otomatis Lingkungan Kerja      ${NC}"
echo -e "${CYAN}============================================================${NC}"
echo ""

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

# 1. Deteksi Python
echo -e "${YELLOW}🔍 [1/5] Memeriksa interpreter Python...${NC}"
PYTHON_CMD=""
for cmd in python3 python py; do
    if command -v "$cmd" >/dev/null 2>&1; then
        VER=$($cmd -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)
        MAJOR=$(echo "$VER" | cut -d. -f1)
        MINOR=$(echo "$VER" | cut -d. -f2)
        if [ "$MAJOR" -ge 3 ] && [ "$MINOR" -ge 10 ]; then
            PYTHON_CMD="$cmd"
            echo -e "${GREEN}   ✅ Ditemukan Python $VER menggunakan '$cmd'${NC}"
            break
        fi
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    echo -e "${RED}❌ GAGAL: Python 3.10 atau versi lebih baru tidak ditemukan!${NC}"
    echo -e "${RED}   Silakan install python3 (>=3.10) dan python3-venv.${NC}"
    exit 1
fi

# 2. Virtual Environment
echo ""
echo -e "${YELLOW}📦 [2/5] Menyiapkan Virtual Environment (.venv)...${NC}"
if [ ! -f ".venv/bin/python" ]; then
    echo "   Membuat direktori .venv..."
    $PYTHON_CMD -m venv .venv
    echo -e "${GREEN}   ✅ Virtual environment berhasil dibuat di .venv${NC}"
else
    echo -e "${GREEN}   ✅ Virtual environment sudah ada di .venv${NC}"
fi

VENV_PYTHON=".venv/bin/python"
VENV_PIP=".venv/bin/pip"

# 3. Upgrade pip & Pasang Dependensi
echo ""
echo -e "${YELLOW}📥 [3/5] Menginstal dependensi dari requirements.txt...${NC}"
$VENV_PYTHON -m pip install --upgrade pip --quiet || true
if [ -f "requirements.txt" ]; then
    echo "   Mengunduh dan memasang paket..."
    $VENV_PIP install -r requirements.txt --quiet
    echo -e "${GREEN}   ✅ Seluruh dependensi berhasil dipasang.${NC}"
else
    echo -e "${RED}❌ File requirements.txt tidak ditemukan!${NC}"
    exit 1
fi

# 4. Verifikasi Paket
echo ""
echo -e "${YELLOW}🧪 [4/5] Memverifikasi integritas paket...${NC}"
if $VENV_PYTHON -c "import fastapi, uvicorn, pydantic, httpx, pytest, numpy; print('OK')" | grep -q "OK"; then
    echo -e "${GREEN}   ✅ Modul kritis siap.${NC}"
else
    echo -e "${RED}❌ Verifikasi paket gagal!${NC}"
    exit 1
fi

# 5. Siapkan run_data
echo ""
echo -e "${YELLOW}📁 [5/5] Menyiapkan direktori operasional...${NC}"
mkdir -p run_data
echo -e "${GREEN}   ✅ Direktori run_data siap.${NC}"

echo ""
echo -e "${CYAN}============================================================${NC}"
echo -e "${GREEN}   🎉 SETUP SELESAI! Proyek RemoteLab v2.0 Siap Digunakan   ${NC}"
echo -e "${CYAN}============================================================${NC}"
echo ""
echo "Perintah selanjutnya:"
echo "1. Jalankan Klaster Lokal:       ./scripts/run_local.sh"
echo "2. Buka Web Dashboard Browser:  http://127.0.0.1:8000"
echo "3. Jalankan Demo Interaktif:     .venv/bin/python scripts/demo.py"
echo "4. Jalankan Pengujian (Pytest): .venv/bin/pytest -v"
echo "5. Jalankan Benchmark:           .venv/bin/python scripts/benchmark.py"
echo ""

