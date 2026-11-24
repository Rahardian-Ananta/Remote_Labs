@echo off
setlocal
set "RL_PROJECT_ROOT=%~dp0"
set "_tmp=%TEMP%\rl_setup_%RANDOM%.ps1"
powershell -NoProfile -Command "(Get-Content '%~f0' -Encoding UTF8 | Select-Object -Skip 10) -join \"`r`n\" | Set-Content -Path '%_tmp%' -Encoding UTF8"
powershell -NoProfile -ExecutionPolicy Bypass -File "%_tmp%"
set _EC=%ERRORLEVEL%
del "%_tmp%" >nul 2>&1
pause
exit /b %_EC%
# ================================================================
# setup.ps1 — RemoteLab v2.0 Setup Otomatis Lingkungan Kerja
# (Bagian ini dibaca otomatis oleh batch di atas)
# ================================================================
$ErrorActionPreference = "Stop"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "   RemoteLab v2.0 - Setup Otomatis Lingkungan Kerja         " -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

if ($env:RL_PROJECT_ROOT) {
    $ProjectRoot = $env:RL_PROJECT_ROOT.TrimEnd('\', '/')
} else {
    $ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
}
if (-not $ProjectRoot -or $ProjectRoot -eq "") {
    $ProjectRoot = (Get-Location).Path
}
Set-Location $ProjectRoot

$VenvDir    = Join-Path $ProjectRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$VenvPip    = Join-Path $VenvDir "Scripts\pip.exe"
$ToolsDir   = Join-Path $ProjectRoot ".tools"
$UvExe      = Join-Path $ToolsDir "uv.exe"

function Ensure-UvPortable {
    if (Test-Path $UvExe) { return $UvExe }
    Write-Host "   Mengunduh engine instalasi portabel mandiri (uv)..." -ForegroundColor Yellow
    if (-not (Test-Path $ToolsDir)) { New-Item -ItemType Directory -Path $ToolsDir -Force | Out-Null }
    $uvZip = Join-Path $ToolsDir "uv.zip"
    $uvUrl = "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip"

    if (Get-Command "curl.exe" -ErrorAction SilentlyContinue) {
        & curl.exe -sSL -o $uvZip $uvUrl
    } else {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $uvUrl -OutFile $uvZip -UseBasicParsing
    }

    if (Get-Command "tar.exe" -ErrorAction SilentlyContinue) {
        & tar.exe -xf $uvZip -C $ToolsDir
    } else {
        Expand-Archive -Path $uvZip -DestinationPath $ToolsDir -Force
    }

    Remove-Item $uvZip -Force -ErrorAction SilentlyContinue
    if (Test-Path $UvExe) {
        Write-Host "   Engine portabel siap." -ForegroundColor Green
        return $UvExe
    }
    throw "Gagal mengunduh engine portabel."
}

# 1. Deteksi Interpreter Python Lokal
Write-Host "[1/6] Memeriksa interpreter Python..." -ForegroundColor Yellow
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
            if ($major -eq 3 -and $minor -ge 10 -and $minor -le 13) {
                $PythonCmd = $cmd
                Write-Host "   Ditemukan $verStr kompatibel di sistem menggunakan '$cmd'" -ForegroundColor Green
                break
            }
        }
    } catch { }
}

$usePortable = $false
if (-not $PythonCmd) {
    Write-Host "   Python 3.10-3.13 tidak ditemukan. Mengaktifkan mode Mandiri (uv)..." -ForegroundColor Cyan
    $usePortable = $true
}

# 2. Virtual Environment (.venv)
Write-Host ""
Write-Host "[2/6] Menyiapkan Virtual Environment (.venv)..." -ForegroundColor Yellow

$needCreateVenv = $true
if (Test-Path $VenvPython) {
    try {
        $vStr = & $VenvPython --version 2>&1
        if ($LASTEXITCODE -eq 0 -and $vStr -match "Python (\d+)\.(\d+)") {
            $vMaj = [int]$Matches[1]
            $vMin = [int]$Matches[2]
            if ($vMaj -eq 3 -and $vMin -ge 10 -and $vMin -le 13) {
                $needCreateVenv = $false
                Write-Host "   Virtual environment valid ($vStr) sudah ada di .venv" -ForegroundColor Green
            } else {
                Write-Host "   .venv lama ($vStr) tidak kompatibel. Membuat ulang..." -ForegroundColor DarkYellow
                Remove-Item -Recurse -Force $VenvDir -ErrorAction SilentlyContinue
            }
        }
    } catch {
        Remove-Item -Recurse -Force $VenvDir -ErrorAction SilentlyContinue
    }
}

if ($needCreateVenv) {
    if ($usePortable) {
        $uv = Ensure-UvPortable
        Write-Host "   Menyiapkan Python 3.12 mandiri ke dalam .venv..." -ForegroundColor Gray
        & $uv venv --python 3.12 $VenvDir
    } else {
        Write-Host "   Membuat .venv menggunakan Python lokal ($PythonCmd)..." -ForegroundColor Gray
        $parts = $PythonCmd.Split(" ")
        $exe = $parts[0]
        $args = if ($parts.Length -gt 1) { $parts[1..($parts.Length-1)] + @("-m", "venv", ".venv") } else { @("-m", "venv", ".venv") }
        & $exe $args
    }
    if (-not (Test-Path $VenvPython)) {
        Write-Host "GAGAL membuat virtual environment!" -ForegroundColor Red
        exit 1
    }
    Write-Host "   Virtual environment berhasil dibuat di .venv" -ForegroundColor Green
}

# 3. Install requirements
Write-Host ""
Write-Host "[3/6] Menginstal dependensi dari requirements.txt..." -ForegroundColor Yellow
$ReqFile = Join-Path $ProjectRoot "requirements.txt"
if (-not (Test-Path $ReqFile)) {
    Write-Host "File requirements.txt tidak ditemukan!" -ForegroundColor Red
    exit 1
}

Write-Host "   Memasang paket (FastAPI, Uvicorn, Pydantic, HTTPX, NumPy, MPI4Py)..." -ForegroundColor Gray

if ($usePortable -or (Test-Path $UvExe)) {
    $uv = Ensure-UvPortable
    & $uv pip install -r $ReqFile --python $VenvPython
} else {
    & $VenvPython -m pip install --upgrade pip --quiet
    & $VenvPip install -r $ReqFile
}

if ($LASTEXITCODE -ne 0) {
    Write-Host "   Gagal via pip, mencoba fallback uv..." -ForegroundColor DarkYellow
    $uv = Ensure-UvPortable
    & $uv pip install -r $ReqFile --python $VenvPython
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Gagal menginstal dependensi!" -ForegroundColor Red
        exit 1
    }
}
Write-Host "   Seluruh dependensi berhasil dipasang." -ForegroundColor Green

# 4. Verifikasi modul
Write-Host ""
Write-Host "[4/6] Memverifikasi integritas paket..." -ForegroundColor Yellow
$verifyScript = "import fastapi, uvicorn, pydantic, httpx, numpy; print('OK')"
$res = & $VenvPython -c $verifyScript 2>&1
if ($res -match "OK") {
    Write-Host "   Modul kritis (FastAPI, Uvicorn, Pydantic, HTTPX, NumPy) siap." -ForegroundColor Green
} else {
    Write-Host "Verifikasi paket gagal: $res" -ForegroundColor Red
    exit 1
}

# 5. Direktori data
Write-Host ""
Write-Host "[5/6] Menyiapkan direktori operasional..." -ForegroundColor Yellow
$RunDataDir = Join-Path $ProjectRoot "run_data"
if (-not (Test-Path $RunDataDir)) {
    New-Item -ItemType Directory -Path $RunDataDir -Force | Out-Null
}
Write-Host "   Direktori run_data siap." -ForegroundColor Green

# 6. Install Microsoft MPI (dibutuhkan untuk mpi4py)
Write-Host ""
Write-Host "[6/6] Memeriksa & menginstal Microsoft MPI..." -ForegroundColor Yellow
if (Get-Command "mpiexec" -ErrorAction SilentlyContinue) {
    Write-Host "   Microsoft MPI (mpiexec) sudah terpasang di sistem." -ForegroundColor Green
} elseif (Get-Command "winget" -ErrorAction SilentlyContinue) {
    Write-Host "   Menginstal Microsoft.msmpi melalui winget..." -ForegroundColor Gray
    & winget install --id Microsoft.msmpi -e --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -eq 0) {
        Write-Host "   Microsoft MPI berhasil dipasang." -ForegroundColor Green
    } else {
        Write-Host "   Peringatan: Instalasi winget selesai dengan kode $LASTEXITCODE (mungkin sudah terpasang atau butuh izin Admin)." -ForegroundColor DarkYellow
    }
} else {
    Write-Host "   Peringatan: winget tidak ditemukan. Silakan instal MS-MPI secara manual." -ForegroundColor DarkYellow
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "   SETUP SELESAI! RemoteLab v2.0 Siap Digunakan             " -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""