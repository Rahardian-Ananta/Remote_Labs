# scripts/run_cluster_executor.ps1
# ─────────────────────────────────────────────────────────────────────────────
# Menjalankan Node Executor untuk skenario Multi-PC (4 Laptop).
# Dijalankan di Laptop 2, Laptop 3, atau Laptop 4.
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
Write-Host "   RemoteLab v2.0 - Executor Node (Laptop Worker / Chord)   " -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Dapatkan IP Lokal Laptop ini
$LocalIP = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.InterfaceAlias -notmatch "Loopback|vEthernet|VirtualBox" -and $_.IPAddress -notmatch "^169\.254\." } | Select-Object -First 1).IPAddress
if (-not $LocalIP) { $LocalIP = "127.0.0.1" }

Write-Host "IP Laptop Anda yang terdeteksi: $LocalIP" -ForegroundColor Green
$ConfirmIP = Read-Host "Gunakan IP ini? (Tekan Enter jika YA, atau ketik IP lain)"
if ($ConfirmIP) { $LocalIP = $ConfirmIP }

Write-Host ""
Write-Host "Pilih peran laptop ini:" -ForegroundColor Yellow
Write-Host "1. exec1 (Laptop 2)" -ForegroundColor White
Write-Host "2. exec2 (Laptop 3)" -ForegroundColor White
Write-Host "3. exec3 (Laptop 4)" -ForegroundColor White
$Pilihan = Read-Host "Pilihan Anda (1/2/3) [default: 1]"

$ExecutorID = "exec1"
$Port = 9001
if ($Pilihan -eq "2") {
    $ExecutorID = "exec2"
} elseif ($Pilihan -eq "3") {
    $ExecutorID = "exec3"
}

Write-Host ""
Write-Host "Masukkan IP node bootstrap (IP laptop teman sesama executor untuk join Chord ring):" -ForegroundColor Yellow
Write-Host "(Jika Anda yang pertama kali jalan, masukkan IP laptop ini sendiri)" -ForegroundColor Gray
$BootstrapIP = Read-Host "IP Bootstrap Node [default: $LocalIP]"
if (-not $BootstrapIP) { $BootstrapIP = $LocalIP }

$BootstrapUrl = "http://${BootstrapIP}:9001"
$MyUrl        = "http://${LocalIP}:${Port}"

$env:EXECUTOR_ID           = $ExecutorID
$env:EXECUTOR_HOST         = "0.0.0.0"
$env:EXECUTOR_PORT         = "$Port"
$env:EXECUTOR_URL          = $MyUrl
$env:EXECUTOR_CAPACITY     = "4"
$env:MAX_RANKS             = "4"
$env:EXECUTOR_DB_PATH      = "$ProjectRoot\run_data\${ExecutorID}_dedup.db"
$env:BOOTSTRAP_NODES       = "$BootstrapUrl,$MyUrl"
$env:CHORD_MAINTENANCE_SEC = "1.5"
$env:PYTHONPATH            = $ProjectRoot
$env:PYTHONUNBUFFERED      = "1"

New-Item -ItemType Directory -Force -Path "$ProjectRoot\run_data" | Out-Null

Write-Host ""
Write-Host "🚀 Menjalankan Executor $ExecutorID..." -ForegroundColor Green
Write-Host "   URL Terbuka: $MyUrl" -ForegroundColor Cyan
Write-Host "   Bootstrap Ring: $BootstrapUrl" -ForegroundColor Cyan
Write-Host ""
Write-Host "Tekan Ctrl+C untuk menghentikan Node." -ForegroundColor Yellow
Write-Host ""

& $VenvPython -m uvicorn executor.main:app --host 0.0.0.0 --port $Port --log-level info

