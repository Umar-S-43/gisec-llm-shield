$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$modelPath = if ([string]::IsNullOrWhiteSpace($env:MODEL_PATH)) {
    'models/Mistral-7B-Instruct-v0.1.Q4_K_M.gguf'
} else {
    $env:MODEL_PATH
}
$serverHost = if ([string]::IsNullOrWhiteSpace($env:LLAMA_SERVER_HOST)) { '0.0.0.0' } else { $env:LLAMA_SERVER_HOST }
$serverPort = if ([string]::IsNullOrWhiteSpace($env:LLAMA_SERVER_PORT)) { '8080' } else { $env:LLAMA_SERVER_PORT }
$numParallel = if ([string]::IsNullOrWhiteSpace($env:NUM_PARALLEL)) { '4' } else { $env:NUM_PARALLEL }
$numThreads = if ([string]::IsNullOrWhiteSpace($env:NUM_THREADS)) { '4' } else { $env:NUM_THREADS }

# -c/--ctx-size is llama-server's TOTAL context, divided EVENLY across $numParallel
# slots (confirmed empirically: --parallel 4 --ctx-size 2048 -> n_ctx_slot=512, not
# 2048/slot). CONTEXT_SIZE must therefore scale with NUM_PARALLEL. Default per-slot
# budget is sized to fit Profile D's ~2112-token maximum-cost requests
# (loadgen/profiles/profile-d.js) with headroom. See docs/MANUAL_CONFIG.md.
$contextSizePerSlot = if ([string]::IsNullOrWhiteSpace($env:CONTEXT_SIZE_PER_SLOT)) { 2560 } else { [int]$env:CONTEXT_SIZE_PER_SLOT }
$contextSize = if ([string]::IsNullOrWhiteSpace($env:CONTEXT_SIZE)) { [int]$numParallel * $contextSizePerSlot } else { $env:CONTEXT_SIZE }

if (-not (Test-Path -LiteralPath $modelPath -PathType Leaf)) {
    Write-Error "Model file not found at $modelPath. Download it with: python service/download_model.py"
}

# Look for llama-server in the project's llama folder
$llamaServerPath = Join-Path $PSScriptRoot "..\llama\llama-server.exe"
if (-not (Test-Path -LiteralPath $llamaServerPath -PathType Leaf)) {
    Write-Error "llama-server not found at $llamaServerPath. Please check the path."
}

Write-Host '=========================================='
Write-Host 'llama-server Configuration'
Write-Host '=========================================='
Write-Host "Model:              $modelPath"
Write-Host "Host:               $serverHost"
Write-Host "Port:               $serverPort"
Write-Host "Max parallel:       $numParallel"
Write-Host "CPU threads:        $numThreads"
Write-Host "Context size:       $contextSize total (~$contextSizePerSlot per slot)"
Write-Host 'Metrics enabled:    yes (GET /metrics)'
Write-Host '=========================================='
Write-Host "Verify with: curl.exe http://localhost:$serverPort/metrics"
Write-Host ''
Write-Host "To target from another machine, find this machine's LAN IP (ipconfig) and post it"
Write-Host 'in the team chat per CLAUDE.md; everyone else sets LLAMA_SERVER_URL in their .env.'
Write-Host ''
Write-Host "REMINDER: TOTAL_LLAMA_SLOTS in the Shield's .env MUST equal Max parallel ($numParallel)"
Write-Host 'or Defense C (slot reservation) will silently do the wrong thing. See docs/MANUAL_CONFIG.md.'

& $llamaServerPath `
    --model $modelPath `
    --host $serverHost `
    --port $serverPort `
    --parallel $numParallel `
    --threads $numThreads `
    --ctx-size $contextSize `
    --metrics

exit $LASTEXITCODE
