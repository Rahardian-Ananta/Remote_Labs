# scripts/run_local.ps1
# ─────────────────────────────────────────────────────────────────────────────
# Menjalankan 3 executor (port 9001-9003) + 1 scheduler (port 8000) secara lokal
# di Windows tanpa Docker. Tekan Ctrl+C untuk menghentikan semua proses.
#
# Penggunaan: .\scripts\run_local.ps1
# ─────────────────────────────────────────────────────────────────────────────

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"

$ProjectRoot = Resolve-Path "$PSScriptRoot\.."
$VenvPython  = "$ProjectRoot\.venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Host "⚠️  Virtual environment belum terpasang. Menjalankan setup otomatis..." -ForegroundColor Yellow
    $SetupScript = Join-Path $ProjectRoot "setup.ps1"
    if (Test-Path $SetupScript) {
        & $SetupScript
    } else {
        Write-Error "Virtual environment tidak ditemukan di $ProjectRoot\.venv dan setup.ps1 tidak ditemukan."
        exit 1
    }
}

$DbDir = "$ProjectRoot\run_data"
New-Item -ItemType Directory -Force -Path $DbDir | Out-Null

function Wait-ExecutorHealthy {
    param([int]$Port, [int]$TimeoutSec = 30)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $res = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2
            if ($res -and $res.status -ne "INITIALIZING") { return $true }
        } catch { }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

# Preflight: cegah bentrok port dengan instance yang masih hidup.
foreach ($port in 8000, 9001, 9002, 9003) {
    try {
        $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    } catch {
        $conn = $null
    }
    if ($conn) {
        Write-Host "Port $port sudah dipakai PID $($conn.OwningProcess)." -ForegroundColor Red
        Write-Host 'Hentikan instance lama dulu, contoh: Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "uvicorn" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }' -ForegroundColor Yellow
        exit 1
    }
}

$Bootstraps    = "http://127.0.0.1:9001,http://127.0.0.1:9002,http://127.0.0.1:9003"
$ExecutorsEnv  = "exec1=http://127.0.0.1:9001,exec2=http://127.0.0.1:9002,exec3=http://127.0.0.1:9003"

$Processes = [System.Collections.Generic.List[System.Diagnostics.Process]]::new()

function Start-RemoteLabProcess {
    param(
        [string]$Label,
        [int]$Port,
        [string]$AppModule,
        [hashtable]$EnvVars
    )

    Write-Host "🚀 Memulai $Label (port $Port)..."

    $psi = [System.Diagnostics.ProcessStartInfo]::new()
    $psi.FileName  = $VenvPython
    $psi.Arguments = "-m uvicorn $AppModule --host 127.0.0.1 --port $Port --log-level warning"
    $psi.UseShellExecute = $false
    $psi.WorkingDirectory = $ProjectRoot

    # Inherit current environment, then apply overrides
    foreach ($kv in [System.Environment]::GetEnvironmentVariables([System.EnvironmentVariableTarget]::Process).GetEnumerator()) {
        $psi.EnvironmentVariables[$kv.Key] = $kv.Value
    }
    $psi.EnvironmentVariables["PYTHONPATH"]       = $ProjectRoot
    $psi.EnvironmentVariables["PYTHONUNBUFFERED"] = "1"
    foreach ($kv in $EnvVars.GetEnumerator()) {
        $psi.EnvironmentVariables[$kv.Key] = $kv.Value
    }

    $proc = [System.Diagnostics.Process]::Start($psi)
    $Processes.Add($proc)
    return $proc
}

function Stop-AllProcesses {
    Write-Host ""
    Write-Host "⏹  Menghentikan semua proses..."
    foreach ($proc in $Processes) {
        try {
            if (-not $proc.HasExited) {
                # taskkill kompatibel dengan Windows PowerShell 5.1 (.NET Framework).
                & taskkill /PID $proc.Id /T /F 2>$null | Out-Null
                if (-not $proc.HasExited) { $proc.Kill() }
            }
        } catch {
            # Proses sudah berhenti, abaikan
        }
    }
    Write-Host "✅ Selesai."
}

# Register Ctrl+C handler
try { [Console]::TreatControlCAsInput = $false } catch { }
$null = Register-EngineEvent -SourceIdentifier PowerShell.Exiting -Action { Stop-AllProcesses }

try {
    # ── Executor 1 (start first, wait until healthy, so peers can join it) ──
    Start-RemoteLabProcess -Label "Executor 1" -Port 9001 -AppModule "executor.main:app" -EnvVars @{
        EXECUTOR_ID             = "exec1"
        EXECUTOR_HOST           = "127.0.0.1"
        EXECUTOR_PORT           = "9001"
        EXECUTOR_CAPACITY       = "4"
        MAX_RANKS               = "4"
        EXECUTOR_DB_PATH        = "$DbDir\exec1.db"
        BOOTSTRAP_NODES         = $Bootstraps
        CHORD_MAINTENANCE_SEC   = "5.0"
    } | Out-Null
    if (-not (Wait-ExecutorHealthy -Port 9001 -TimeoutSec 30)) {
        throw "Executor 1 tidak siap dalam 30 detik."
    }

    # ── Executor 2 ──────────────────────────────────────────────────────────
    Start-RemoteLabProcess -Label "Executor 2" -Port 9002 -AppModule "executor.main:app" -EnvVars @{
        EXECUTOR_ID             = "exec2"
        EXECUTOR_HOST           = "127.0.0.1"
        EXECUTOR_PORT           = "9002"
        EXECUTOR_CAPACITY       = "4"
        MAX_RANKS               = "4"
        EXECUTOR_DB_PATH        = "$DbDir\exec2.db"
        BOOTSTRAP_NODES         = $Bootstraps
        CHORD_MAINTENANCE_SEC   = "5.0"
    } | Out-Null
    if (-not (Wait-ExecutorHealthy -Port 9002 -TimeoutSec 30)) {
        throw "Executor 2 tidak siap dalam 30 detik."
    }

    # ── Executor 3 ──────────────────────────────────────────────────────────
    Start-RemoteLabProcess -Label "Executor 3" -Port 9003 -AppModule "executor.main:app" -EnvVars @{
        EXECUTOR_ID             = "exec3"
        EXECUTOR_HOST           = "127.0.0.1"
        EXECUTOR_PORT           = "9003"
        EXECUTOR_CAPACITY       = "4"
        MAX_RANKS               = "4"
        EXECUTOR_DB_PATH        = "$DbDir\exec3.db"
        BOOTSTRAP_NODES         = $Bootstraps
        CHORD_MAINTENANCE_SEC   = "5.0"
    } | Out-Null
    if (-not (Wait-ExecutorHealthy -Port 9003 -TimeoutSec 30)) {
        throw "Executor 3 tidak siap dalam 30 detik."
    }

    # ── Scheduler ───────────────────────────────────────────────────────────
    Start-RemoteLabProcess -Label "Scheduler" -Port 8000 -AppModule "scheduler.main:app" -EnvVars @{
        SCHEDULER_HOST      = "127.0.0.1"
        SCHEDULER_PORT      = "8000"
        EXECUTORS           = $ExecutorsEnv
        DB_PATH             = "$DbDir\scheduler.db"
        HEALTH_INTERVAL_SEC = "5.0"
        CACHE_CAPACITY      = "500"
        CACHE_LEASE_SEC     = "60.0"
    } | Out-Null

    Write-Host ""
    Write-Host "═══════════════════════════════════════════════════════"
    Write-Host "  ✅ RemoteLab v2.0 berjalan"
    Write-Host "  🌐 UI: http://localhost:8000"
    Write-Host "  📡 Executor: :9001  :9002  :9003"
    Write-Host "  Tekan Ctrl+C untuk menghentikan semua proses"
    Write-Host "═══════════════════════════════════════════════════════"

    # Tunggu sampai salah satu proses keluar atau Ctrl+C
    while ($true) {
        Start-Sleep -Seconds 2
        $dead = @($Processes | Where-Object { $_.HasExited })
        if ($dead.Count -gt 0) {
            foreach ($proc in $dead) {
                Write-Warning "Proses $($proc.Id) telah keluar dengan kode $($proc.ExitCode). Menghentikan klaster..."
            }
            break
        }
    }
}
finally {
    Stop-AllProcesses
}

