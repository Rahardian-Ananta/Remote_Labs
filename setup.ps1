# setup.ps1 — RemoteLab v2.0 Setup Otomatis Lingkungan Kerja (Universal Windows)
$ErrorActionPreference = "Stop"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "   RemoteLab v2.0 - Setup Otomatis Lingkungan Kerja         " -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

$ProjectRoot = $PSScriptRoot
Set-Location $ProjectRoot

# 1. Deteksi Interpreter Python (Prioritaskan versi stabil 3.11 - 3.13 yang punya wheel lengkap)
Write-Host "[1/5] Memeriksa interpreter Python..." -ForegroundColor Yellow
$PythonCmd = $null
$candidates = @("py -3.12", "py -3.11", "py -3.13", "py -3.10", "py -3", "python", "python3")
foreach ($cmd in $candidates) {
    try {
        $parts = $cmd.Split(" ")
        $exe = $parts[0]
        $args = if ($parts.Length -gt 1) { $parts[1..($parts.Length-1)] } else { @() }
        $verStr = & $exe $args --version 2>&1
        if ($LASTEXITCODE -eq 0 -and $verStr -match "Python (\d+)\.(\d+)") {
            $major = [int]$Matches[1]
            $minor = [int]$Matches[2]
            if ($major -ge 3 -and $minor -ge 10) {
                $PythonCmd = $cmd
                Write-Host "   Ditemukan $verStr menggunakan '$cmd'" -ForegroundColor Green
                break
            }
        }
    } catch {
        # lanjut ke kandidat berikutnya
    }
}

if (-not $PythonCmd) {
    Write-Host "GAGAL: Python 3.10 atau versi lebih baru tidak ditemukan!" -ForegroundColor Red
    Write-Host "Silakan pasang Python 3.12 dari https://www.python.org/downloads/" -ForegroundColor Red
    exit 1
}

# 2. Virtual Environment (.venv) - Validasi & Buat Ulang Jika Rusak / Bawaan PC Lain
$VenvDir = Join-Path $ProjectRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$VenvPip = Join-Path $VenvDir "Scripts\pip.exe"

Write-Host ""
Write-Host "[2/5] Menyiapkan Virtual Environment (.venv)..." -ForegroundColor Yellow

$needCreateVenv = $true
if (Test-Path $VenvPython) {
    try {
        $null = & $VenvPython --version 2>&1
        if ($LASTEXITCODE -eq 0) {
            $needCreateVenv = $false
            Write-Host "   Virtual environment valid dan siap digunakan di .venv" -ForegroundColor Green
        }
    } catch {
        $needCreateVenv = $true
    }

    if ($needCreateVenv) {
        Write-Host "   Terdeteksi .venv lama/rusak dari perangkat lain. Membuat ulang..." -ForegroundColor DarkYellow
        Remove-Item -Recurse -Force $VenvDir
    }
}

if ($needCreateVenv) {
    Write-Host "   Membuat direktori .venv baru..." -ForegroundColor Gray
    $parts = $PythonCmd.Split(" ")
    $exe = $parts[0]
    $args = if ($parts.Length -gt 1) { $parts[1..($parts.Length-1)] + @("-m", "venv", ".venv") } else { @("-m", "venv", ".venv") }
    & $exe $args
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Gagal membuat virtual environment!" -ForegroundColor Red
        exit 1
    }
    Write-Host "   Virtual environment berhasil dibuat di .venv" -ForegroundColor Green
}

# 3. Upgrade pip & Install requirements
Write-Host ""
Write-Host "[3/5] Menginstal dependensi dari requirements.txt..." -ForegroundColor Yellow
& $VenvPython -m pip install --upgrade pip --quiet
$ReqFile = Join-Path $ProjectRoot "requirements.txt"
if (Test-Path $ReqFile) {
    Write-Host "   Memasang paket (FastAPI, Uvicorn, Pydantic, HTTPX, Pytest, NumPy)..." -ForegroundColor Gray
    & $VenvPip install -r $ReqFile --quiet
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Gagal menginstal dependensi dari requirements.txt!" -ForegroundColor Red
        exit 1
    }
    Write-Host "   Seluruh dependensi berhasil dipasang." -ForegroundColor Green
} else {
    Write-Host "File requirements.txt tidak ditemukan!" -ForegroundColor Red
    exit 1
}

# 4. Verifikasi modul
Write-Host ""
Write-Host "[4/5] Memverifikasi integritas paket..." -ForegroundColor Yellow
$verifyScript = "import fastapi, uvicorn, pydantic, httpx, pytest, numpy; print('OK')"
$res = & $VenvPython -c $verifyScript 2>&1
if ($res -match "OK") {
    Write-Host "   Modul kritis (FastAPI, Uvicorn, Pydantic, HTTPX, Pytest, NumPy) siap." -ForegroundColor Green
} else {
    Write-Host "Verifikasi paket gagal: $res" -ForegroundColor Red
    exit 1
}

# 5. Direktori data
Write-Host ""
Write-Host "[5/5] Menyiapkan direktori operasional..." -ForegroundColor Yellow
$RunDataDir = Join-Path $ProjectRoot "run_data"
if (-not (Test-Path $RunDataDir)) {
    New-Item -ItemType Directory -Path $RunDataDir -Force | Out-Null
}
Write-Host "   Direktori run_data siap." -ForegroundColor Green

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "   SETUP SELESAI! Proyek RemoteLab v2.0 Siap Digunakan      " -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""