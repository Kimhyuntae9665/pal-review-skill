# Interactive local-only key entry. No web server, telemetry, or inference.
param([switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -le 5) {
    $env:PSModulePath = [IO.Path]::Combine($PSHOME, 'Modules')
}
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) { throw 'Windows DPAPI is required.' }
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$palSetupRoot = Join-Path $env:LOCALAPPDATA 'CodexPalReview'
$palSetupRoutes = @(
    @{ Id='gemini'; Title='1. Gemini 3.8 Flash'; Url='https://aistudio.google.com/api-keys'; NeedsFree=$true },
    @{ Id='groq'; Title='2. Qwen3.8 27B - Groq'; Url='https://console.groq.com/keys'; NeedsFree=$true },
    @{ Id='openrouter'; Title='3 + 4. Nemotron / Cohere - OpenRouter'; Url='https://openrouter.ai/settings/keys'; NeedsFree=$false }
)
$palForm = New-Object System.Windows.Forms.Form
$palForm.Text = 'PAL - Free reviewer connections'
$palForm.ClientSize = New-Object System.Drawing.Size(720, 555)
$palForm.StartPosition = 'CenterScreen'
$palForm.FormBorderStyle = 'FixedDialog'
$palForm.MaximizeBox = $false
$palForm.Font = New-Object System.Drawing.Font('Segoe UI', 10)
$palIntro = New-Object System.Windows.Forms.Label
$palIntro.Text = "Login and create keys on the official sites yourself. Paste keys ONLY here, never into chat.`r`nGoogle/Groq: Free plan, billing disabled. OpenRouter: exact :free routes only.`r`nKeys are encrypted for this Windows user. This window never calls a model or buys credits."
$palIntro.SetBounds(20, 16, 680, 75)
$palForm.Controls.Add($palIntro)
$palSetupControls = @()
$palRowY = 100
foreach ($palRoute in $palSetupRoutes) {
    $palCredentialPath = Join-Path $palSetupRoot ($palRoute.Id + '.credential.xml')
    $palAlreadyStored = Test-Path -LiteralPath $palCredentialPath
    $palTitle = New-Object System.Windows.Forms.Label
    $palTitle.Text = $palRoute.Title
    $palTitle.SetBounds(20, $palRowY, 475, 25)
    $palForm.Controls.Add($palTitle)
    $palLink = New-Object System.Windows.Forms.LinkLabel
    $palLink.Text = 'Official key page'
    $palLink.Tag = $palRoute.Url
    $palLink.SetBounds(530, $palRowY, 160, 25)
    $palLink.Add_LinkClicked({ param($sender, $eventArgs) Start-Process -FilePath ([string]$sender.Tag) })
    $palForm.Controls.Add($palLink)
    $palInput = New-Object System.Windows.Forms.TextBox
    $palInput.UseSystemPasswordChar = $true
    $palInput.SetBounds(20, ($palRowY + 28), 510, 28)
    $palInput.Enabled = -not $palAlreadyStored
    $palForm.Controls.Add($palInput)
    $palCheck = New-Object System.Windows.Forms.CheckBox
    $palCheck.Text = if ($palRoute.NeedsFree) { 'I checked: FREE plan and paid billing disabled' } else { 'Use only the two configured zero-price :free routes' }
    $palCheck.SetBounds(20, ($palRowY + 61), 660, 27)
    $palCheck.Enabled = -not $palAlreadyStored
    $palCheck.Checked = $palAlreadyStored
    $palForm.Controls.Add($palCheck)
    $palStatus = New-Object System.Windows.Forms.Label
    $palStatus.Text = if ($palAlreadyStored) { 'Stored locally (not live verified)' } else { 'Not connected' }
    $palStatus.SetBounds(20, ($palRowY + 90), 650, 25)
    $palForm.Controls.Add($palStatus)
    $palSetupControls += @{ Route=$palRoute; Input=$palInput; Check=$palCheck; Status=$palStatus; Stored=$palAlreadyStored }
    $palRowY += 125
}
$palSave = New-Object System.Windows.Forms.Button
$palSave.Text = 'Save entered keys'
$palSave.SetBounds(350, 495, 170, 36)
$palSave.Add_Click({
    foreach ($palEntry in $palSetupControls) {
        if ($palEntry.Stored -or [string]::IsNullOrWhiteSpace($palEntry.Input.Text)) { continue }
        if (-not $palEntry.Check.Checked) {
            $palEntry.Status.Text = 'Check the account condition first. Key not saved.'
            continue
        }
        $palSecret = $null
        $palCredential = $null
        try {
            $palLocalKey = $palEntry.Input.Text.Trim()
            if ($palLocalKey.Length -lt 16 -or $palLocalKey -match '\s') {
                $palEntry.Status.Text = 'Key format looks incomplete. Key not saved.'
                continue
            }
            $palSecret = ConvertTo-SecureString -String $palLocalKey -AsPlainText -Force
            $palUserName = $palEntry.Route.Id
            if ($palEntry.Route.NeedsFree) { $palUserName += '-free' }
            $palCredential = [pscredential]::new($palUserName, $palSecret)
            New-Item -ItemType Directory -Force -Path $palSetupRoot | Out-Null
            $palDestination = Join-Path $palSetupRoot ($palEntry.Route.Id + '.credential.xml')
            $palCredential | Export-Clixml -LiteralPath $palDestination -NoClobber
            $palEntry.Stored = $true
            $palEntry.Input.Clear()
            $palEntry.Input.Enabled = $false
            $palEntry.Check.Enabled = $false
            $palEntry.Status.Text = 'Encrypted and stored. No model request made yet.'
        } catch {
            $palEntry.Status.Text = 'Could not save. Existing credentials were not replaced.'
        } finally {
            $palLocalKey = $null
            $palCredential = $null
            if ($palSecret) { $palSecret.Dispose() }
            $palSecret = $null
        }
    }
})
$palForm.Controls.Add($palSave)
$palClose = New-Object System.Windows.Forms.Button
$palClose.Text = 'Close'
$palClose.SetBounds(540, 495, 150, 36)
$palClose.Add_Click({ $palForm.Close() })
$palForm.Controls.Add($palClose)
$palForm.Add_FormClosed({ foreach ($palEntry in $palSetupControls) { $palEntry.Input.Clear() } })
if ($CheckOnly) {
    [pscustomobject]@{ status='form_created_without_showing'; providers=$palSetupControls.Count; password_fields=@($palSetupControls | Where-Object { $_.Input.UseSystemPasswordChar }).Count; inference_called=$false; network_called=$false } | ConvertTo-Json
} else {
    [void]$palForm.ShowDialog()
}
$palForm.Dispose()
