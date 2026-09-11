<#
.SYNOPSIS
    Live PowerShell dashboard for the Shield's real-time process state.

.DESCRIPTION
    Combines two sources every refresh, both live, neither simulated:
      1. Direct HTTP calls to the Shield and llama-server's own /health and
         /metrics endpoints -- the authoritative, right-now truth (queue depth,
         slots in use, whether either process is even reachable).
      2. shield/shield.log (see shield/main.py's FileHandler) -- cumulative
         counts of every defense that's fired since the Shield started, plus
         a rolling tail of the most recent raw log lines.

    Requires shield/main.py to be running with file logging enabled (this was
    added 2026-09-11 specifically so a separate terminal/window could watch
    the Shield live without needing access to whatever process originally
    launched it).

.PARAMETER ShieldUrl
    Base URL of the Shield. Defaults to http://localhost:9090.

.PARAMETER LogPath
    Path to shield.log. Defaults to shield\shield.log next to this script.

.PARAMETER RefreshSeconds
    How often to redraw. Defaults to 1 second.

.EXAMPLE
    .\shield\watch_dashboard.ps1
    .\shield\watch_dashboard.ps1 -ShieldUrl "http://10.185.191.136:9090" -RefreshSeconds 2
#>

param(
    [string]$ShieldUrl = "http://localhost:9090",
    [string]$LogPath = "$PSScriptRoot\shield.log",
    [int]$RefreshSeconds = 1,
    [int]$TailLines = 12
)

# Pull llama-server's URL out of the Shield's own /health-adjacent config if we
# can't otherwise guess it; fall back to reading .env directly (same value
# every other component in this repo reads, per CLAUDE.md).
function Get-LlamaServerUrl {
    $envPath = Join-Path $PSScriptRoot "..\.env"
    if (Test-Path $envPath) {
        $line = Get-Content $envPath | Where-Object { $_ -match '^\s*LLAMA_SERVER_URL\s*=\s*(.+)$' } | Select-Object -First 1
        if ($line -and $line -match '^\s*LLAMA_SERVER_URL\s*=\s*(.+?)\s*$') {
            return $Matches[1]
        }
    }
    return $null
}
$LlamaUrl = Get-LlamaServerUrl

function Get-LiveState {
    param([string]$Url, [string]$Path)
    try {
        $resp = Invoke-WebRequest -Uri "$Url$Path" -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop
        return @{ Ok = $true; Code = $resp.StatusCode; Body = $resp.Content }
    } catch {
        return @{ Ok = $false; Code = $null; Body = $null }
    }
}

function Parse-Metric {
    param([string]$Body, [string]$Name)
    if (-not $Body) { return $null }
    $m = [regex]::Match($Body, "^$Name\s+(\d+)", "Multiline")
    if ($m.Success) { return [int]$m.Groups[1].Value }
    return $null
}

Write-Host "Starting Shield live dashboard. Press Ctrl+C to stop." -ForegroundColor DarkGray
Start-Sleep -Milliseconds 500

while ($true) {
    $shieldHealth = Get-LiveState -Url $ShieldUrl -Path "/health"
    $llamaHealth  = if ($LlamaUrl) { Get-LiveState -Url $LlamaUrl -Path "/health" } else { @{ Ok = $false } }
    $llamaMetrics = if ($LlamaUrl) { Get-LiveState -Url $LlamaUrl -Path "/metrics" } else { @{ Ok = $false } }

    $deferred  = Parse-Metric -Body $llamaMetrics.Body -Name "llamacpp:requests_deferred"
    $processing = Parse-Metric -Body $llamaMetrics.Body -Name "llamacpp:requests_processing"

    $logExists = Test-Path $LogPath
    $logLines = if ($logExists) { Get-Content $LogPath -ErrorAction SilentlyContinue } else { @() }

    # Deliberately POST /completion only -- GET /health (including this dashboard's
    # own polling every refresh) would otherwise inflate this count with noise
    # that has nothing to do with actual admitted requests. Caught by testing.
    $count200 = ($logLines | Select-String -Pattern '"POST /completion HTTP/1\.1" 200').Count
    $count429 = ($logLines | Select-String -Pattern 'Token budget exceeded').Count
    $count503_B_deferred = ($logLines | Select-String -Pattern 'Shedding load: requests_deferred').Count
    $count503_B_slots    = ($logLines | Select-String -Pattern 'No slot available on llama-server').Count
    $count503_C          = ($logLines | Select-String -Pattern 'Slot reservation:').Count
    $totalShed = $count429 + $count503_B_deferred + $count503_B_slots + $count503_C

    Clear-Host
    Write-Host "=== SHIELD LIVE DASHBOARD ===" -ForegroundColor Cyan -NoNewline
    Write-Host "  $(Get-Date -Format 'HH:mm:ss')" -ForegroundColor DarkGray
    Write-Host ""

    Write-Host "-- Process health (right now, not from the log) --" -ForegroundColor Yellow
    $shieldStatus = if ($shieldHealth.Ok) { "UP (HTTP $($shieldHealth.Code))" } else { "DOWN / UNREACHABLE" }
    $shieldColor  = if ($shieldHealth.Ok) { "Green" } else { "Red" }
    Write-Host ("  Shield  ({0}): " -f $ShieldUrl) -NoNewline
    Write-Host $shieldStatus -ForegroundColor $shieldColor

    if ($LlamaUrl) {
        $llamaStatus = if ($llamaHealth.Ok) { "UP (HTTP $($llamaHealth.Code))" } else { "DOWN / UNREACHABLE" }
        $llamaColor  = if ($llamaHealth.Ok) { "Green" } else { "Red" }
        Write-Host ("  llama-server ({0}): " -f $LlamaUrl) -NoNewline
        Write-Host $llamaStatus -ForegroundColor $llamaColor

        if ($null -ne $deferred) {
            $deferredColor = if ($deferred -gt 10) { "Red" } elseif ($deferred -gt 0) { "Yellow" } else { "Green" }
            Write-Host ("  requests_deferred (queue depth): ") -NoNewline
            Write-Host $deferred -ForegroundColor $deferredColor -NoNewline
            Write-Host ("   |   requests_processing (of 4 slots): $processing")
        }
    } else {
        Write-Host "  (LLAMA_SERVER_URL not found in .env -- skipping)" -ForegroundColor DarkGray
    }

    Write-Host ""
    Write-Host "-- Cumulative since Shield started (from shield.log) --" -ForegroundColor Yellow
    if (-not $logExists) {
        Write-Host "  shield.log not found at $LogPath -- is the Shield running with file logging?" -ForegroundColor Red
    } else {
        Write-Host ("  200 Success:                {0,6}" -f $count200) -ForegroundColor Green
        Write-Host ("  429 Token budget (Defense A):{0,6}" -f $count429) -ForegroundColor Magenta
        Write-Host ("  503 Deferred queue (Def. B): {0,6}" -f $count503_B_deferred) -ForegroundColor DarkYellow
        Write-Host ("  503 No slot avail. (Def. B): {0,6}" -f $count503_B_slots) -ForegroundColor DarkYellow
        Write-Host ("  503 Slot reservation (Def.C):{0,6}" -f $count503_C) -ForegroundColor DarkYellow
        Write-Host ("  Total shed:                  {0,6}" -f $totalShed) -ForegroundColor Red
    }

    Write-Host ""
    Write-Host "-- Last $TailLines log lines --" -ForegroundColor Yellow
    if ($logExists) {
        Get-Content $LogPath -Tail $TailLines | ForEach-Object {
            $line = $_
            $color = "Gray"
            if ($line -match "ERROR") { $color = "Red" }
            elseif ($line -match "WARNING") { $color = "DarkYellow" }
            elseif ($line -match '" 200') { $color = "Green" }
            Write-Host "  $line" -ForegroundColor $color
        }
    }

    Write-Host ""
    Write-Host "(Ctrl+C to stop; refreshing every ${RefreshSeconds}s)" -ForegroundColor DarkGray

    Start-Sleep -Seconds $RefreshSeconds
}
