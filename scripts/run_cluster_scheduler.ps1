# scripts/run_cluster_scheduler.ps1
# ─────────────────────────────────────────────────────────────────────────────
# Menjalankan Scheduler (Master) untuk skenario Multi-PC (4 Laptop).
# Dijalankan di Laptop 1 (Koordinator).
# ─────────────────────────────────────────────────────────────────────────────

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"

$ProjectRoot = Resolve-Path "$PSScriptRoot\.."
$VenvPython  = "$ProjectRoot\.venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Host "Virtual environment belum terpasang. Menjalankan setup.ps1..." -ForegroundColor Yellow
    & "$ProjectRoot\setup.ps1"
}

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "   RemoteLab v2.0 - Scheduler Node (Laptop 1 / Master)      " -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Dapatkan IP Lokal Laptop 1
$LocalIP = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.InterfaceAlias -notmatch "Loopback|vEthernet|VirtualBox" -and $_.IPAddress -notmatch "^169\.254\." } | Select-Object -First 1).IPAddress
if (-not $LocalIP) { $LocalIP = "127.0.0.1" }

Write-Host "IP Laptop Anda (Master): $LocalIP" -ForegroundColor Green
Write-Host "Web Dashboard dapat diakses di: http://$LocalIP:8000" -ForegroundColor Cyan
Write-Host ""

# Konfigurasi IP / URL 3 Laptop Teman (Executor)
Write-Host "Masukkan IP atau URL ketiga laptop / node teman Anda:" -ForegroundColor Yellow
Write-Host "(Bisa berupa IP lokal seperti 192.168.1.11 atau URL cloud seperti https://username-space.hf.space)" -ForegroundColor Gray
$IP2 = Read-Host "IP/URL Node 2 (exec1) [default: 127.0.0.1]"
$IP3 = Read-Host "IP/URL Node 3 (exec2) [default: 127.0.0.1]"
$IP4 = Read-Host "IP/URL Node 4 (exec3) [default: 127.0.0.1]"

function Format-NodeUrl($val, $defaultPort = 9001) {
    if (-not $val) { return "http://127.0.0.1:$defaultPort" }
    if ($val -match "^https?://") { return $val.TrimEnd("/") }
    return "http://${val}:$defaultPort"
}

$Url2 = Format-NodeUrl $IP2 9001
$Url3 = Format-NodeUrl $IP3 9001
$Url4 = Format-NodeUrl $IP4 9001

$ExecutorsEnv = "exec1=${Url2},exec2=${Url3},exec3=${Url4}"

$env:SCHEDULER_HOST       = "0.0.0.0"
$env:SCHEDULER_PORT       = "8000"
$env:EXECUTORS            = $ExecutorsEnv
$env:DB_PATH              = "$ProjectRoot\run_data\scheduler.db"
$env:PYTHONPATH           = $ProjectRoot
$env:PYTHONUNBUFFERED     = "1"

New-Item -ItemType Directory -Force -Path "$ProjectRoot\run_data" | Out-Null

Write-Host ""
Write-Host "🚀 Menjalankan Scheduler di port 8000..." -ForegroundColor Green
Write-Host "   Mendaftarkan worker:" -ForegroundColor Gray
Write-Host "   - exec1 -> http://${IP2}:9001" -ForegroundColor Gray
Write-Host "   - exec2 -> http://${IP3}:9001" -ForegroundColor Gray
Write-Host "   - exec3 -> http://${IP4}:9001" -ForegroundColor Gray
Write-Host ""
Write-Host "Tekan Ctrl+C untuk menghentikan Scheduler." -ForegroundColor Yellow
Write-Host ""

& $VenvPython -m uvicorn scheduler.main:app --host 0.0.0.0 --port 8000 --log-level info

