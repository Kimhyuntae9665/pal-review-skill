# One explicitly pinned request per cloud model, using only a synthetic fixture.
param([string]$OutputDirectory)
$ErrorActionPreference = 'Stop'
if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path (Get-Location) ('work/cloud-review-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
}
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$palTestRoot = (Resolve-Path -LiteralPath $OutputDirectory).Path
$palFixtures = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../tests/fixtures')).Path
$palCases = @(
    @{ Provider='gemini'; Name='gemini'; Model='gemini-3.8-flash' },
    @{ Provider='groq'; Name='qwen'; Model='qwen/qwen3.8-27b' },
    @{ Provider='openrouter'; Name='nemotron'; Model='nvidia/nemotron-3-ultra-550b-a55b:free' },
    @{ Provider='openrouter'; Name='cohere'; Model='cohere/north-mini-code:free' }
)
$palResults = @()
foreach ($palCase in $palCases) {
    $palOutput = Join-Path $palTestRoot ($palCase.Name + '.json')
    if ((Test-Path -LiteralPath $palOutput) -or (Test-Path -LiteralPath ($palOutput + '.inflight'))) {
        throw "Existing evidence must be preserved. Choose a new output directory: $palOutput"
    }
    $palStdout = @(& (Join-Path $PSScriptRoot 'pal-review.ps1') run --profile free --model $palCase.Model --cwd $palFixtures --brief 'cloud-brief.md' --file 'cloud-example.py' --output $palOutput)
    $palExit = $LASTEXITCODE
    if (-not (Test-Path -LiteralPath $palOutput)) {
        # The client reports preflight failures on stdout before it reserves an
        # inference result file. Preserve that JSON as blocked-test evidence.
        $palPreflight = ($palStdout -join [Environment]::NewLine) | ConvertFrom-Json
        if (-not $palPreflight.status -or $palPreflight.inference_called -ne $false) {
            throw "No conclusive result record for $($palCase.Model). Exit: $palExit"
        }
        $palPreflight | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $palOutput -Encoding UTF8
    }
    $palResult = Get-Content -LiteralPath $palOutput -Raw -Encoding UTF8 | ConvertFrom-Json
    $palReason = if ($palResult.reason) { $palResult.reason } else { $palResult.message }
    $palResults += [pscustomobject]@{ provider=$palCase.Provider; model=$palCase.Model; status=$palResult.status; reason=$palReason; exit_code=$palExit; result=$palOutput }
}
$palSummary = [pscustomobject]@{
    created_at=(Get-Date).ToUniversalTime().ToString('o'); fixture='synthetic; no personal or confidential data';
    real_model_responses=@($palResults | Where-Object { $_.status -eq 'review_received' }).Count;
    results=$palResults
}
$palSummary | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $palTestRoot 'summary.json') -Encoding UTF8
$palSummary | ConvertTo-Json -Depth 8
if ($palSummary.real_model_responses -ne $palCases.Count) { exit 2 }
