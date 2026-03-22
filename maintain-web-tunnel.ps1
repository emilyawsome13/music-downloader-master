param(
    [string]$ProjectDir = $PSScriptRoot,
    [int]$IntervalSeconds = 60
)

$ErrorActionPreference = "SilentlyContinue"

function Get-ServerInfoPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RootDir
    )

    return (Join-Path $RootDir ".spotdl-web\server-info.json")
}

function Test-RemoteUrl {
    param(
        [string]$Url
    )

    if ([string]::IsNullOrWhiteSpace($Url)) {
        return $false
    }

    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 10
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 400
    }
    catch {
        return $false
    }
}

while ($true) {
    $infoPath = Get-ServerInfoPath -RootDir $ProjectDir
    if (-not (Test-Path $infoPath)) {
        break
    }

    $info = $null
    try {
        $info = Get-Content $infoPath -Raw | ConvertFrom-Json
    }
    catch {
        Start-Sleep -Seconds 5
        continue
    }

    if ($null -eq $info -or $null -eq $info.pid) {
        Start-Sleep -Seconds $IntervalSeconds
        continue
    }

    $serverProcess = Get-CimInstance `
        Win32_Process `
        -Filter "ProcessId = $($info.pid)" `
        -ErrorAction SilentlyContinue
    if ($null -eq $serverProcess) {
        break
    }

    $publicUrl = $info.public_url
    if (-not (Test-RemoteUrl -Url $publicUrl)) {
        $launcher = Join-Path $ProjectDir "run-web-background.ps1"
        $powershellExe = (Get-Command powershell -ErrorAction SilentlyContinue).Source

        if (-not [string]::IsNullOrWhiteSpace($powershellExe) -and (Test-Path $launcher)) {
            & $powershellExe `
                -NoProfile `
                -ExecutionPolicy Bypass `
                -File $launcher `
                --refresh-public-tunnel `
                --skip-monitor *> $null
        }
    }

    Start-Sleep -Seconds $IntervalSeconds
}
