param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$CliArgs
)

$ErrorActionPreference = "Stop"

if ($null -eq $CliArgs) {
    $CliArgs = @()
}

function Test-HasFlag {
    param(
        [string[]]$Args,
        [Parameter(Mandatory = $true)]
        [string]$Flag
    )

    return ($Args -contains $Flag)
}

$projectDir = $PSScriptRoot
$uiDir = Join-Path $projectDir "local-web-ui"
$spotdlLauncher = Join-Path $projectDir "run-spotdl.ps1"

if (-not (Test-Path $uiDir)) {
    throw "Could not find bundled dashboard UI at: $uiDir"
}

$defaultArgs = @("web")
if (-not (Test-HasFlag -Args $CliArgs -Flag "--host")) {
    $defaultArgs += @("--host", "0.0.0.0")
}

if (-not (Test-HasFlag -Args $CliArgs -Flag "--port")) {
    $defaultArgs += @("--port", "8800")
}

if (-not (Test-HasFlag -Args $CliArgs -Flag "--keep-alive")) {
    $defaultArgs += "--keep-alive"
}

if (-not (Test-HasFlag -Args $CliArgs -Flag "--web-gui-location")) {
    $defaultArgs += @("--web-gui-location", $uiDir)
}

if (-not (Test-HasFlag -Args $CliArgs -Flag "--output")) {
    $defaultArgs += @("--output", "{album-artist}/{album}/{title}.{output-ext}")
}

if (-not (Test-HasFlag -Args $CliArgs -Flag "--audio")) {
    $defaultArgs += @("--audio", "youtube-music", "youtube")
}

Write-Host "Starting spotDL Control Room..."
Write-Host "The dashboard will listen on your local network so you can open it from your phone."
Write-Host "Web downloads use an isolated session folder so they do not get skipped by songs already on this PC."

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

& $spotdlLauncher @defaultArgs @CliArgs
exit $LASTEXITCODE
