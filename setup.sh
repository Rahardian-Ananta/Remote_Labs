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
TOO_NEW_PYTHON=""
for cmd in python3.12 python3.11 python3.13 python3.10 python3 python py; do
    if command -v "$cmd" >/dev/null 2>&1; then
        VER=$($cmd -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)
        MAJOR=$(echo "$VER" | cut -d. -f1)
        MINOR=$(echo "$VER" | cut -d. -f2)
        if [ "$MAJOR" -eq 3 ] && [ "$MINOR" -ge 10 ] && [ "$MINOR" -le 13 ]; then
            PYTHON_CMD="$cmd"
            echo -e "${GREEN}   ✅ Ditemukan Python $VER menggunakan '$cmd'${NC}"
            break
        elif [ "$MAJOR" -eq 3 ] && [ "$MINOR" -gt 13 ] && [ -z "$TOO_NEW_PYTHON" ]; then
            TOO_NEW_PYTHON="Python $VER ($cmd)"
        fi
    fi
done

USE_PORTABLE=0
if [ -z "$PYTHON_CMD" ]; then
    echo -e "${YELLOW}   Python 3.10-3.13 tidak ditemukan di sistem / versi global tidak kompatibel.${NC}"
    echo -e "${CYAN}   Mengaktifkan mode Mandiri: Mengunduh engine portabel dan Python 3.12 mandiri...${NC}"
    USE_PORTABLE=1
fi

# 2. Virtual Environment
echo ""
echo -e "${YELLOW}📦 [2/5] Menyiapkan Virtual Environment (.venv)...${NC}"
if [ $USE_PORTABLE -eq 1 ]; then
    if ! command -v uv >/dev/null 2>&1; then
        echo "   Mengunduh engine portabel uv..."
        curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1 || true
        export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    fi
    if command -v uv >/dev/null 2>&1; then
        echo "   Membuat virtual environment Python 3.12 mandiri via uv..."
        uv venv --python 3.12 .venv
    else
        echo -e "${RED}❌ GAGAL: Tidak dapat menyiapkan Python mandiri otomatis.${NC}"
        echo -e "${RED}   Silakan pasang python3 (versi 3.11 atau 3.12).${NC}"
        exit 1
    fi
elif [ ! -f ".venv/bin/python" ]; then
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
if command -v uv >/dev/null 2>&1; then
    uv pip install -r requirements.txt --python "$VENV_PYTHON"
else
    $VENV_PYTHON -m pip install --upgrade pip --quiet || true
    if [ -f "requirements.txt" ]; then
        echo "   Mengunduh dan memasang paket..."
        $VENV_PIP install -r requirements.txt --quiet
    fi
fi
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

