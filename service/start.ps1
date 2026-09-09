$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$modelPath = if ([string]::IsNullOrWhiteSpace($env:MODEL_PATH)) {
    'models/Mistral-7B-Instruct-v0.1.Q4_K_M.gguf'
} else {
    $env:MODEL_PATH
}
$serverPort = if ([string]::IsNullOrWhiteSpace($env:LLAMA_SERVER_PORT)) { '8080' } else { $env:LLAMA_SERVER_PORT }
$numParallel = if ([string]::IsNullOrWhiteSpace($env:NUM_PARALLEL)) { '1' } else { $env:NUM_PARALLEL }
$numThreads = if ([string]::IsNullOrWhiteSpace($env:NUM_THREADS)) { '4' } else { $env:NUM_THREADS }
$contextSize = if ([string]::IsNullOrWhiteSpace($env:CONTEXT_SIZE)) { '2048' } else { $env:CONTEXT_SIZE }

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
Write-Host "Port:               $serverPort"
Write-Host "Max parallel:       $numParallel"
Write-Host "CPU threads:        $numThreads"
Write-Host "Context size:       $contextSize"
Write-Host 'Metrics enabled:    yes (GET /metrics)'
Write-Host '=========================================='
Write-Host "Verify with: curl.exe http://localhost:$serverPort/metrics"

& $llamaServerPath `
    --model $modelPath `
    --port $serverPort `
    --parallel $numParallel `
    --threads $numThreads `
    --ctx-size $contextSize `
    --metrics

exit $LASTEXITCODE