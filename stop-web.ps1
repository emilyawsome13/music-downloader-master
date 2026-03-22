param()

$ErrorActionPreference = "Stop"

function Get-ServerInfoPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectDir
    )

    return (Join-Path $ProjectDir ".spotdl-web\server-info.json")
}

function Find-SpotdlWebProcess {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectDir
    )

    $escapedProjectDir = [regex]::Escape($ProjectDir)
    $candidates = @(
        Get-CimInstance Win32_Process | Where-Object {
            $_.Name -like "python*" -and
            -not [string]::IsNullOrWhiteSpace($_.CommandLine) -and
            $_.CommandLine -match "(^|\s)-m\s+spotdl\s+web(\s|$)" -and
            $_.CommandLine -match $escapedProjectDir
        }
    )

    if ($candidates.Count -eq 0) {
        return $null
    }

    $candidateIds = @($candidates | ForEach-Object { [int]$_.ProcessId })
    $rootProcess = $candidates | Where-Object {
        $candidateIds -notcontains [int]$_.ParentProcessId
    } | Select-Object -First 1

    if ($null -eq $rootProcess) {
        $rootProcess = $candidates | Sort-Object ProcessId | Select-Object -First 1
    }

    return $rootProcess
}

function Find-PublicTunnelProcess {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectDir
    )

    $escapedProjectDir = [regex]::Escape($ProjectDir)
    $candidates = @(
        Get-CimInstance Win32_Process | Where-Object {
            $_.Name -like "cloudflared*" -and
            -not [string]::IsNullOrWhiteSpace($_.CommandLine) -and
            $_.CommandLine -match $escapedProjectDir -and
            $_.CommandLine -match "tunnel"
        }
    )

    if ($candidates.Count -eq 0) {
        return $null
    }

    return ($candidates | Sort-Object ProcessId | Select-Object -First 1)
}

function Find-TunnelMonitorProcess {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectDir
    )

    $monitorScript = Join-Path $ProjectDir "maintain-web-tunnel.ps1"
    $escapedMonitorScript = [regex]::Escape($monitorScript)

    $candidates = @(
        Get-CimInstance Win32_Process | Where-Object {
            $_.Name -like "powershell*" -and
            -not [string]::IsNullOrWhiteSpace($_.CommandLine) -and
            $_.CommandLine -match $escapedMonitorScript
        }
    )

    if ($candidates.Count -eq 0) {
        return $null
    }

    return ($candidates | Sort-Object ProcessId | Select-Object -First 1)
}

function Stop-ProcessTree {
    param(
        [Parameter(Mandatory = $true)]
        [int]$ProcessId
    )

    & taskkill /PID $ProcessId /T /F *> $null
}

$projectDir = $PSScriptRoot
$infoPath = Get-ServerInfoPath -ProjectDir $projectDir
$info = $null

if (Test-Path $infoPath) {
    $info = Get-Content $infoPath -Raw | ConvertFrom-Json
}

$tunnelProcess = $null
if ($null -ne $info -and $info.public_tunnel_pid) {
    $tunnelProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $($info.public_tunnel_pid)" -ErrorAction SilentlyContinue
}

if ($null -eq $tunnelProcess) {
    $tunnelProcess = Find-PublicTunnelProcess -ProjectDir $projectDir
}

if ($null -ne $tunnelProcess) {
    Stop-ProcessTree -ProcessId $tunnelProcess.ProcessId
}

$monitorProcess = Find-TunnelMonitorProcess -ProjectDir $projectDir
if ($null -ne $monitorProcess) {
    Stop-ProcessTree -ProcessId $monitorProcess.ProcessId
}

$serverProcess = $null
if ($null -ne $info -and $info.pid) {
    $serverProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $($info.pid)" -ErrorAction SilentlyContinue
}

if ($null -eq $serverProcess) {
    $serverProcess = Find-SpotdlWebProcess -ProjectDir $projectDir
}

if ($null -ne $serverProcess) {
    Stop-ProcessTree -ProcessId $serverProcess.ProcessId
}

Remove-Item -Path $infoPath -ErrorAction SilentlyContinue

if ($null -eq $tunnelProcess -and $null -eq $serverProcess) {
    Write-Host "spotDL Control Room is not running."
    exit 0
}

Write-Host "Stopped spotDL Control Room."
if ($null -ne $info -and -not [string]::IsNullOrWhiteSpace($info.stdout_log)) {
    Write-Host "Log file: $($info.stdout_log)"
}
