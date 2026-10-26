# Cloud API connection helper; credentials use Windows user/machine-bound DPAPI.
# API keys are accepted only in an interactive hidden local prompt.
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -le 5) {
    # Codex's bundled PowerShell 7 module path is incompatible with powershell.exe.
    $env:PSModulePath = [IO.Path]::Combine($PSHOME, 'Modules')
}
$palCredentialRoot = if ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA 'CodexPalReview' } else { $null }
$palProviders = @{
    gemini = @{ Key = 'GEMINI_API_KEY'; Flag = 'PAL_GEMINI_FREE_TIER_CONFIRMED' }
    groq = @{ Key = 'GROQ_API_KEY'; Flag = 'PAL_GROQ_FREE_TIER_CONFIRMED' }
    openrouter = @{ Key = 'OPENROUTER_API_KEY'; Flag = $null }
}
$palCommandIndex = 0
while ($palCommandIndex -lt $args.Count) {
    if ($args[$palCommandIndex] -eq '--config') { $palCommandIndex += 2; continue }
    if ([string]$args[$palCommandIndex] -like '--config=*') { $palCommandIndex++; continue }
    break
}
$palCommand = if ($palCommandIndex -lt $args.Count) { [string]$args[$palCommandIndex] } else { 'doctor' }
if ($palCommand -in @('connect', 'disconnect')) {
    if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
        throw 'This credential helper requires Windows DPAPI.'
    }
    if ($args.Count -gt 2) { throw 'Use connect/disconnect [gemini|groq|openrouter]. Never supply a key argument.' }
    $palProvider = if ($args.Count -eq 2) { [string]$args[1] } else { 'openrouter' }
    if (-not $palProviders.ContainsKey($palProvider)) { throw 'Unknown provider. Use gemini, groq, or openrouter.' }
    $palCredentialPath = Join-Path $palCredentialRoot ($palProvider + '.credential.xml')
    if ($palCommand -eq 'disconnect') {
        if (Test-Path -LiteralPath $palCredentialPath) { Remove-Item -LiteralPath $palCredentialPath }
        Write-Output "Stored $palProvider credential removed. The service key is not revoked."
        exit 0
    }
    if (Test-Path -LiteralPath $palCredentialPath) { throw 'Credential already exists. Use disconnect before replacing it.' }
    $palUserName = $palProvider
    if ($palProvider -in @('gemini', 'groq')) {
        Write-Host 'Check the service console: this key must belong to the Free plan, with paid billing disabled.'
        $palPlanAnswer = Read-Host 'Type FREE only after checking (otherwise press Enter to cancel)'
        if ($palPlanAnswer -cne 'FREE') { throw 'Free plan not confirmed. No credential saved and no API call made.' }
        $palUserName += '-free'
    }
    $palSecureKey = Read-Host "$palProvider API key (hidden; never paste into chat)" -AsSecureString
    if ($palSecureKey.Length -eq 0) { throw 'No key supplied.' }
    $palCredential = [pscredential]::new($palUserName, $palSecureKey)
    New-Item -ItemType Directory -Force -Path $palCredentialRoot | Out-Null
    $palCredential | Export-Clixml -LiteralPath $palCredentialPath
    Remove-Variable palCredential,palSecureKey
    Write-Output "$palProvider credential stored with Windows DPAPI. No API request made."
    exit 0
}
# Match runtime_config.load_config: config-relative paths and a fixed platform token.
$palConfigPath = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../references/models.json'))
for ($palIndex = 0; $palIndex -lt $args.Count; $palIndex++) {
    if ($args[$palIndex] -eq '--config') {
        if ($palIndex + 1 -ge $args.Count) { throw '--config requires a file path.' }
        $palConfigPath = [IO.Path]::GetFullPath([string]$args[$palIndex + 1])
    } elseif ([string]$args[$palIndex] -like '--config=*') {
        $palConfigPath = [IO.Path]::GetFullPath(([string]$args[$palIndex]).Substring(9))
    }
}
$palConfig = Get-Content -LiteralPath $palConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
$palPythonSuffix = if ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT) { 'Scripts/python.exe' } else { 'bin/python' }
$palPythonPath = ([string]$palConfig.pal_python).Replace('{venv_python}', $palPythonSuffix)
if (-not [IO.Path]::IsPathRooted($palPythonPath)) { $palPythonPath = Join-Path ([IO.Path]::GetDirectoryName($palConfigPath)) $palPythonPath }
$palPythonPath = [IO.Path]::GetFullPath($palPythonPath)
if (-not (Test-Path -LiteralPath $palPythonPath -PathType Leaf)) {
    throw 'PAL runtime is missing. Run python scripts/bootstrap.py from the repository first.'
}
$palClient = Join-Path $PSScriptRoot 'pal_review.py'
$palArguments = @($args)
if ($palCommand -eq 'rounds') {
    $palClient = Join-Path $PSScriptRoot 'review_rounds.py'
    $palArguments = @(for ($palIndex = 0; $palIndex -lt $args.Count; $palIndex++) { if ($palIndex -ne $palCommandIndex) { $args[$palIndex] } })
}
$palPriorEnvironment = @{}
try {
    foreach ($palProvider in $palProviders.Keys) {
        $palRoute = $palProviders[$palProvider]
        foreach ($palName in @($palRoute.Key, $palRoute.Flag)) {
            if ($palName) { $palPriorEnvironment[$palName] = [Environment]::GetEnvironmentVariable($palName, 'Process') }
        }
        $palCredentialPath = if ($palCredentialRoot) { Join-Path $palCredentialRoot ($palProvider + '.credential.xml') } else { $null }
        if ($palCredentialPath -and -not $palPriorEnvironment[$palRoute.Key] -and (Test-Path -LiteralPath $palCredentialPath)) {
            $palCredential = Import-Clixml -LiteralPath $palCredentialPath
            $palExpectedName = if ($palRoute.Flag) { $palProvider + '-free' } else { $palProvider }
            if ($palCredential -isnot [pscredential] -or $palCredential.UserName -ne $palExpectedName) {
                throw "Unexpected $palProvider credential type or missing Free plan confirmation."
            }
            [Environment]::SetEnvironmentVariable($palRoute.Key, $palCredential.GetNetworkCredential().Password, 'Process')
            if ($palRoute.Flag) { [Environment]::SetEnvironmentVariable($palRoute.Flag, '1', 'Process') }
            Remove-Variable palCredential
        }
    }
    if ($palArguments.Count) { & $palPythonPath -X utf8 $palClient @palArguments }
    else { & $palPythonPath -X utf8 $palClient doctor }
    $palExitCode = $LASTEXITCODE
} finally {
    foreach ($palName in $palPriorEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($palName, $palPriorEnvironment[$palName], 'Process')
    }
    $palPriorEnvironment.Clear()
}
exit $palExitCode
