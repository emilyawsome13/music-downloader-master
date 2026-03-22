param()

$ErrorActionPreference = "Stop"

function Get-ServerInfoPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectDir
    )

    return (Join-Path $ProjectDir ".spotdl-web\server-info.json")
}

function Get-CommandLineArgumentValue {
    param(
        [Parameter(Mandatory = $true)]
        [string]$CommandLine,
        [Parameter(Mandatory = $true)]
        [string]$Flag,
        [string]$DefaultValue
    )

    $pattern = "{0}\s+(?:`"([^`"]+)`"|(\S+))" -f [regex]::Escape($Flag)
    $match = [regex]::Match($CommandLine, $pattern)
    if ($match.Success) {
        if ($match.Groups[1].Success) {
            return $match.Groups[1].Value
        }

        return $match.Groups[2].Value
    }

    return $DefaultValue
}

function Get-LanUrl {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Protocol,
        [Parameter(Mandatory = $true)]
        [string]$BindHost,
        [Parameter(Mandatory = $true)]
        [int]$Port
    )

    if ($BindHost -notin @("0.0.0.0", "::")) {
        return "${Protocol}://${BindHost}:${Port}/"
    }

    try {
        $socket = New-Object System.Net.Sockets.Socket(
            [System.Net.Sockets.AddressFamily]::InterNetwork,
            [System.Net.Sockets.SocketType]::Dgram,
            [System.Net.Sockets.ProtocolType]::Udp
        )
        $socket.Connect("8.8.8.8", 80)
        $endpoint = [System.Net.IPEndPoint]$socket.LocalEndPoint
        $lanIp = $endpoint.Address.ToString()
        $socket.Dispose()
    }
    catch {
        $lanIp = "127.0.0.1"
    }

    return "${Protocol}://${lanIp}:${Port}/"
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

function Get-PublicUrlFromLog {
    param(
        [Parameter(Mandatory = $true)]
        [string]$LogPath
    )

    if (-not (Test-Path $LogPath)) {
        return $null
    }

    $content = Get-Content $LogPath -Raw
    $matches = [regex]::Matches($content, "https://[-a-z0-9]+\.trycloudflare\.com")
    if ($matches.Count -gt 0) {
        return $matches[$matches.Count - 1].Value
    }

    return $null
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

$projectDir = $PSScriptRoot
$infoPath = Get-ServerInfoPath -ProjectDir $projectDir
$info = $null

if (Test-Path $infoPath) {
    $info = Get-Content $infoPath -Raw | ConvertFrom-Json
}

$serverProcess = $null
if ($null -ne $info -and $info.pid) {
    $serverProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $($info.pid)" -ErrorAction SilentlyContinue
}

if ($null -eq $serverProcess) {
    $serverProcess = Find-SpotdlWebProcess -ProjectDir $projectDir
}

if ($null -eq $serverProcess) {
    Remove-Item -Path $infoPath -ErrorAction SilentlyContinue
    Write-Host "spotDL Control Room is not running."
    exit 0
}

$hostValue = if ($null -ne $info -and -not [string]::IsNullOrWhiteSpace($info.host)) {
    $info.host
} else {
    Get-CommandLineArgumentValue -CommandLine $serverProcess.CommandLine -Flag "--host" -DefaultValue "0.0.0.0"
}

$portValue = if ($null -ne $info -and $info.port) {
    [int]$info.port
} else {
    [int](Get-CommandLineArgumentValue -CommandLine $serverProcess.CommandLine -Flag "--port" -DefaultValue "8800")
}

$localUrl = if ($hostValue -in @("0.0.0.0", "::")) {
    "http://127.0.0.1:${portValue}/"
} else {
    "http://${hostValue}:${portValue}/"
}

$lanUrl = Get-LanUrl -Protocol "http" -BindHost $hostValue -Port $portValue
$stdoutLog = if ($null -ne $info -and -not [string]::IsNullOrWhiteSpace($info.stdout_log)) {
    $info.stdout_log
} else {
    Join-Path $projectDir ".spotdl-web\stdout.log"
}

$publicTunnelLog = if ($null -ne $info -and -not [string]::IsNullOrWhiteSpace($info.public_tunnel_log)) {
    $info.public_tunnel_log
} else {
    Join-Path $projectDir ".spotdl-web\public-tunnel.log"
}

$publicUrl = $null
$loggedPublicUrl = Get-PublicUrlFromLog -LogPath $publicTunnelLog
$publicUrlCandidates = @()

if ($null -ne $loggedPublicUrl) {
    $publicUrlCandidates += $loggedPublicUrl
}

if ($null -ne $info -and -not [string]::IsNullOrWhiteSpace($info.public_url)) {
    if ($publicUrlCandidates -notcontains $info.public_url) {
        $publicUrlCandidates += $info.public_url
    }
}

foreach ($candidate in $publicUrlCandidates) {
    if (Test-RemoteUrl -Url $candidate) {
        $publicUrl = $candidate
        break
    }
}

$tunnelProcess = $null
if ($null -ne $info -and $info.public_tunnel_pid) {
    $tunnelProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $($info.public_tunnel_pid)" -ErrorAction SilentlyContinue
}

if ($null -eq $tunnelProcess) {
    $tunnelProcess = Find-PublicTunnelProcess -ProjectDir $projectDir
}

Write-Host "spotDL Control Room is running."
Write-Host "PID: $($serverProcess.ProcessId)"
if ($null -ne $info -and -not [string]::IsNullOrWhiteSpace($info.started_at)) {
    Write-Host "Started: $($info.started_at)"
}
Write-Host "This PC: $localUrl"
Write-Host "Phone/tablet on same Wi-Fi: $lanUrl"

if ($null -ne $tunnelProcess -and -not [string]::IsNullOrWhiteSpace($publicUrl)) {
    Write-Host "Anywhere: $publicUrl"
    Write-Host "Public tunnel PID: $($tunnelProcess.ProcessId)"
}
elseif ($null -ne $tunnelProcess) {
    Write-Host "Anywhere: tunnel is starting. Check: $publicTunnelLog"
}
else {
    Write-Host "Anywhere: public link is not active."
}

Write-Host "Logs: $stdoutLog"
