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

function Load-EnvFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (-not (Test-Path $Path)) {
        return
    }

    foreach ($line in Get-Content $Path) {
        if ([string]::IsNullOrWhiteSpace($line)) {
            continue
        }

        $trimmed = $line.Trim()
        if ($trimmed.StartsWith("#")) {
            continue
        }

        $parts = $trimmed -split "=", 2
        if ($parts.Count -ne 2) {
            continue
        }

        $key = $parts[0].Trim()
        $value = $parts[1].Trim()

        if ($key -in @("SPOTDL_CLIENT_ID", "SPOTDL_CLIENT_SECRET")) {
            Set-Item -Path "Env:$key" -Value $value
        }
    }
}

function Get-ProjectPython {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectDir
    )

    $pythonExe = Join-Path $ProjectDir ".venv\Scripts\python.exe"
    if (Test-Path $pythonExe) {
        return $pythonExe
    }

    throw "Could not find the project virtual environment at $pythonExe. Run .\\run-spotdl.bat once first."
}

function Remove-Flags {
    param(
        [string[]]$Args,
        [string[]]$FlagsToRemove
    )

    $filtered = New-Object System.Collections.Generic.List[string]
    foreach ($arg in $Args) {
        if ($FlagsToRemove -contains $arg) {
            continue
        }

        $filtered.Add($arg)
    }

    return $filtered.ToArray()
}

function Get-ArgumentValue {
    param(
        [string[]]$Args,
        [Parameter(Mandatory = $true)]
        [string]$Flag
    )

    for ($index = 0; $index -lt $Args.Count; $index++) {
        if ($Args[$index] -ne $Flag) {
            continue
        }

        if ($index + 1 -lt $Args.Count) {
            return $Args[$index + 1]
        }
    }

    return $null
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
        [string]$ProjectDir,
        [Parameter(Mandatory = $true)]
        [int]$Port
    )

    $escapedProjectDir = [regex]::Escape($ProjectDir)
    $candidates = @(
        Get-CimInstance Win32_Process | Where-Object {
            $_.Name -like "python*" -and
            -not [string]::IsNullOrWhiteSpace($_.CommandLine) -and
            $_.CommandLine -match "(^|\s)-m\s+spotdl\s+web(\s|$)" -and
            $_.CommandLine -match $escapedProjectDir -and
            ([int](Get-CommandLineArgumentValue `
                -CommandLine $_.CommandLine `
                -Flag "--port" `
                -DefaultValue "8800")) -eq $Port
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
        [string]$ProjectDir,
        [Parameter(Mandatory = $true)]
        [int]$Port,
        [Parameter(Mandatory = $true)]
        [string]$TunnelLogPath
    )

    $escapedProjectDir = [regex]::Escape($ProjectDir)
    $escapedTunnelLog = [regex]::Escape($TunnelLogPath)
    $escapedOriginUrl = [regex]::Escape("http://127.0.0.1:${Port}")

    $candidates = @(
        Get-CimInstance Win32_Process | Where-Object {
            $_.Name -like "cloudflared*" -and
            -not [string]::IsNullOrWhiteSpace($_.CommandLine) -and
            $_.CommandLine -match $escapedProjectDir -and
            $_.CommandLine -match "tunnel" -and
            (
                $_.CommandLine -match $escapedTunnelLog -or
                $_.CommandLine -match $escapedOriginUrl
            )
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

function Test-PortListening {
    param(
        [Parameter(Mandatory = $true)]
        [int]$Port
    )

    return $null -ne (
        Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
        Select-Object -First 1
    )
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

function Ensure-Cloudflared {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectDir
    )

    $cloudflaredDir = Join-Path $ProjectDir ".spotdl-tools\cloudflared"
    $cloudflaredPath = Join-Path $cloudflaredDir "cloudflared.exe"

    if (Test-Path $cloudflaredPath) {
        return $cloudflaredPath
    }

    New-Item -ItemType Directory -Path $cloudflaredDir -Force | Out-Null
    Write-Host "Downloading Cloudflare tunnel helper..."
    Invoke-WebRequest `
        -Uri "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe" `
        -OutFile $cloudflaredPath

    return $cloudflaredPath
}

function Stop-ProcessTree {
    param(
        [Parameter(Mandatory = $true)]
        [int]$ProcessId
    )

    & taskkill /PID $ProcessId /T /F *> $null
}

function Write-ServerInfo {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectDir,
        [Parameter(Mandatory = $true)]
        [Microsoft.Management.Infrastructure.CimInstance]$ServerProcess,
        [Parameter(Mandatory = $true)]
        [string]$HostValue,
        [Parameter(Mandatory = $true)]
        [int]$PortValue,
        [Parameter(Mandatory = $true)]
        [string]$LocalUrl,
        [Parameter(Mandatory = $true)]
        [string]$LanUrl,
        [Parameter(Mandatory = $true)]
        [string]$StdoutLog,
        [Parameter(Mandatory = $true)]
        [string]$StderrLog,
        [string]$PublicUrl,
        [Nullable[int]]$PublicTunnelPid,
        [string]$PublicTunnelLog,
        [string]$PublicTunnelStatus
    )

    $info = [ordered]@{
        pid = [int]$ServerProcess.ProcessId
        host = $HostValue
        port = $PortValue
        local_url = $LocalUrl
        lan_url = $LanUrl
        stdout_log = $StdoutLog
        stderr_log = $StderrLog
        started_at = (Get-Date).ToString("o")
        command_line = $ServerProcess.CommandLine
        public_url = $PublicUrl
        public_tunnel_pid = $PublicTunnelPid
        public_tunnel_log = $PublicTunnelLog
        public_tunnel_status = $PublicTunnelStatus
    }

    $info | ConvertTo-Json | Set-Content -Path (Get-ServerInfoPath -ProjectDir $ProjectDir) -Encoding UTF8
}

$projectDir = $PSScriptRoot
$runtimeDir = Join-Path $projectDir ".spotdl-web"
$outerDir = Split-Path -Parent $projectDir
$uiDir = Join-Path $projectDir "local-web-ui"
$stdoutLog = Join-Path $runtimeDir "stdout.log"
$stderrLog = Join-Path $runtimeDir "stderr.log"
$publicTunnelLog = Join-Path $runtimeDir "public-tunnel.log"
$infoPath = Get-ServerInfoPath -ProjectDir $projectDir

$localOnly = (Test-HasFlag -Args $CliArgs -Flag "--local-only") -or
    (Test-HasFlag -Args $CliArgs -Flag "--no-public-tunnel")
$skipMonitor = Test-HasFlag -Args $CliArgs -Flag "--skip-monitor"
$refreshPublicTunnel = Test-HasFlag -Args $CliArgs -Flag "--refresh-public-tunnel"
$forwardArgs = Remove-Flags -Args $CliArgs -FlagsToRemove @("--local-only", "--no-public-tunnel", "--refresh-public-tunnel", "--skip-monitor")

$hostValue = Get-ArgumentValue -Args $forwardArgs -Flag "--host"
if ([string]::IsNullOrWhiteSpace($hostValue)) {
    $hostValue = "0.0.0.0"
}

$portValue = Get-ArgumentValue -Args $forwardArgs -Flag "--port"
if ([string]::IsNullOrWhiteSpace($portValue)) {
    $portValue = "8800"
}

$portNumber = [int]$portValue
$protocol = "http"
$localHost = if ($hostValue -in @("0.0.0.0", "::")) { "127.0.0.1" } else { $hostValue }
$localUrl = "${protocol}://${localHost}:${portNumber}/"
$lanUrl = Get-LanUrl -Protocol $protocol -BindHost $hostValue -Port $portNumber

New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null

Load-EnvFile -Path (Join-Path $projectDir ".spotdl.env")
if (-not $env:SPOTDL_CLIENT_ID -or -not $env:SPOTDL_CLIENT_SECRET) {
    Load-EnvFile -Path (Join-Path $outerDir ".spotdl.env")
}

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$serverProcess = Find-SpotdlWebProcess -ProjectDir $projectDir -Port $portNumber
$serverWasAlreadyRunning = $null -ne $serverProcess

if (-not $serverWasAlreadyRunning) {
    Remove-Item -Path $stdoutLog -ErrorAction SilentlyContinue
    Remove-Item -Path $stderrLog -ErrorAction SilentlyContinue

    $pythonExe = Get-ProjectPython -ProjectDir $projectDir
    $startArgs = @("-m", "spotdl", "web")

    if ($env:SPOTDL_CLIENT_ID -and $env:SPOTDL_CLIENT_SECRET) {
        $startArgs += @("--client-id", $env:SPOTDL_CLIENT_ID, "--client-secret", $env:SPOTDL_CLIENT_SECRET)
    }

    if (-not (Test-HasFlag -Args $forwardArgs -Flag "--use-cache-file") -and -not (Test-HasFlag -Args $forwardArgs -Flag "--no-cache")) {
        $startArgs += "--use-cache-file"
    }

    if (-not (Test-HasFlag -Args $forwardArgs -Flag "--bitrate")) {
        $startArgs += @("--bitrate", "192k")
    }

    if (-not (Test-HasFlag -Args $forwardArgs -Flag "--host")) {
        $startArgs += @("--host", $hostValue)
    }

    if (-not (Test-HasFlag -Args $forwardArgs -Flag "--port")) {
        $startArgs += @("--port", "$portNumber")
    }

    if (-not (Test-HasFlag -Args $forwardArgs -Flag "--keep-alive")) {
        $startArgs += "--keep-alive"
    }

    if (-not (Test-HasFlag -Args $forwardArgs -Flag "--web-gui-location")) {
        $startArgs += @("--web-gui-location", $uiDir)
    }

    if (-not (Test-HasFlag -Args $forwardArgs -Flag "--output")) {
        $startArgs += @("--output", "{album-artist}/{album}/{title}.{output-ext}")
    }

    if (-not (Test-HasFlag -Args $forwardArgs -Flag "--audio")) {
        $startArgs += @("--audio", "youtube-music", "youtube")
    }

    $startArgs += $forwardArgs

    $launcherProcess = Start-Process `
        -FilePath $pythonExe `
        -ArgumentList $startArgs `
        -WorkingDirectory $projectDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog `
        -PassThru

    $serverReady = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Seconds 1

        $serverProcess = Find-SpotdlWebProcess -ProjectDir $projectDir -Port $portNumber
        if (($null -ne $serverProcess) -and (Test-PortListening -Port $portNumber)) {
            $serverReady = $true
            break
        }

        $launcherProcess.Refresh()
        if ($launcherProcess.HasExited -and $null -eq $serverProcess) {
            break
        }
    }

    if (-not $serverReady -or $null -eq $serverProcess) {
        if ($null -ne $serverProcess) {
            Stop-ProcessTree -ProcessId $serverProcess.ProcessId
        }
        elseif (-not $launcherProcess.HasExited) {
            Stop-ProcessTree -ProcessId $launcherProcess.Id
        }

        $errorOutput = ""
        if (Test-Path $stderrLog) {
            $errorOutput += (Get-Content $stderrLog -Raw)
        }
        if ([string]::IsNullOrWhiteSpace($errorOutput) -and (Test-Path $stdoutLog)) {
            $errorOutput = Get-Content $stdoutLog -Raw
        }

        throw "Background dashboard failed to start cleanly.`n$errorOutput"
    }
}

$publicUrl = $null
$publicTunnelPid = $null
$publicTunnelStatus = if ($localOnly) { "disabled" } else { "starting" }

if (-not $localOnly) {
    try {
        $cloudflaredPath = Ensure-Cloudflared -ProjectDir $projectDir
        $tunnelProcess = Find-PublicTunnelProcess `
            -ProjectDir $projectDir `
            -Port $portNumber `
            -TunnelLogPath $publicTunnelLog

        if ($null -ne $tunnelProcess) {
            $publicUrl = Get-PublicUrlFromLog -LogPath $publicTunnelLog
            $restartTunnel = $refreshPublicTunnel -or [string]::IsNullOrWhiteSpace($publicUrl)

            if (-not $restartTunnel) {
                $restartTunnel = -not (Test-RemoteUrl -Url $publicUrl)
            }

            if ($restartTunnel) {
                Stop-ProcessTree -ProcessId $tunnelProcess.ProcessId
                Start-Sleep -Seconds 1
                $tunnelProcess = $null
                $publicUrl = $null
                Remove-Item -Path $publicTunnelLog -ErrorAction SilentlyContinue
            }
        }

        if ($null -eq $tunnelProcess) {
            Remove-Item -Path $publicTunnelLog -ErrorAction SilentlyContinue

            $tunnelProcess = Start-Process `
                -FilePath $cloudflaredPath `
                -ArgumentList @(
                    "tunnel",
                    "--url",
                    $localUrl,
                    "--no-autoupdate",
                    "--protocol",
                    "http2",
                    "--logfile",
                    $publicTunnelLog
                ) `
                -WorkingDirectory $projectDir `
                -WindowStyle Hidden `
                -PassThru
        }

        for ($attempt = 0; $attempt -lt 30; $attempt++) {
            Start-Sleep -Seconds 1
            $publicUrl = Get-PublicUrlFromLog -LogPath $publicTunnelLog
            if (-not [string]::IsNullOrWhiteSpace($publicUrl)) {
                break
            }
        }

        if (-not [string]::IsNullOrWhiteSpace($publicUrl)) {
            $tunnelBecameReachable = $false
            for ($attempt = 0; $attempt -lt 30; $attempt++) {
                if (Test-RemoteUrl -Url $publicUrl) {
                    $tunnelBecameReachable = $true
                    break
                }

                Start-Sleep -Seconds 1
            }

            if (-not $tunnelBecameReachable) {
                $publicUrl = $null
            }
        }

        $liveTunnel = Find-PublicTunnelProcess `
            -ProjectDir $projectDir `
            -Port $portNumber `
            -TunnelLogPath $publicTunnelLog

        if ($null -ne $liveTunnel) {
            $publicTunnelPid = [int]$liveTunnel.ProcessId
        }

        if ([string]::IsNullOrWhiteSpace($publicUrl)) {
            $publicTunnelStatus = "unavailable"
        }
        else {
            $publicTunnelStatus = "running"
        }
    }
    catch {
        $publicTunnelStatus = "error"
        Write-Host "The public tunnel could not be started automatically."
        Write-Host $_.Exception.Message
    }
}

if ((-not $localOnly) -and (-not $skipMonitor)) {
    $monitorScript = Join-Path $projectDir "maintain-web-tunnel.ps1"
    $monitorProcess = Find-TunnelMonitorProcess -ProjectDir $projectDir

    if (($null -eq $monitorProcess) -and (Test-Path $monitorScript)) {
        $powershellExe = (Get-Command powershell -ErrorAction Stop).Source
        Start-Process `
            -FilePath $powershellExe `
            -ArgumentList @(
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                $monitorScript,
                "-ProjectDir",
                $projectDir,
                "-IntervalSeconds",
                "20"
            ) `
            -WorkingDirectory $projectDir `
            -WindowStyle Hidden | Out-Null
    }
}

Write-ServerInfo `
    -ProjectDir $projectDir `
    -ServerProcess $serverProcess `
    -HostValue $hostValue `
    -PortValue $portNumber `
    -LocalUrl $localUrl `
    -LanUrl $lanUrl `
    -StdoutLog $stdoutLog `
    -StderrLog $stderrLog `
    -PublicUrl $publicUrl `
    -PublicTunnelPid $publicTunnelPid `
    -PublicTunnelLog $publicTunnelLog `
    -PublicTunnelStatus $publicTunnelStatus

if ($serverWasAlreadyRunning) {
    Write-Host "spotDL Control Room is already running in the background."
}
else {
    Write-Host "spotDL Control Room is now running in the background."
}

Write-Host "This PC: $localUrl"
Write-Host "Phone/tablet on same Wi-Fi: $lanUrl"

if ($localOnly) {
    Write-Host "Anywhere link disabled because --local-only was used."
}
elseif (-not [string]::IsNullOrWhiteSpace($publicUrl)) {
    Write-Host "Anywhere: $publicUrl"
    Write-Host "The public link is temporary and may change whenever you restart the dashboard."
}
else {
    Write-Host "Anywhere link is not ready yet. Check: $publicTunnelLog"
}

Write-Host "Logs: $stdoutLog"
Write-Host "To stop it, run .\\stop-web.bat"
