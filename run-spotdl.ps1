param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$CliArgs
)

$ErrorActionPreference = "Stop"

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Command
    )

    & $Command[0] $Command[1..($Command.Length - 1)]
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $($Command -join ' ')"
    }
}

function Test-SupportedPython {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PythonExe
    )

    & $PythonExe -c "import sys; raise SystemExit(0 if (3, 10) <= sys.version_info[:2] < (3, 14) else 1)" *> $null
    return $LASTEXITCODE -eq 0
}

function Find-PythonLauncher {
    $candidates = @(
        @{ Exe = "py"; Args = @("-3.13") },
        @{ Exe = "py"; Args = @("-3.12") },
        @{ Exe = "py"; Args = @("-3.11") },
        @{ Exe = "py"; Args = @("-3.10") }
    )

    foreach ($candidate in $candidates) {
        $exists = Get-Command $candidate.Exe -ErrorAction SilentlyContinue
        if (-not $exists) {
            continue
        }

        & $candidate.Exe @($candidate.Args + @("-c", "import sys")) *> $null
        if ($LASTEXITCODE -eq 0) {
            return $candidate
        }
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python -and (Test-SupportedPython -PythonExe "python")) {
        return @{ Exe = "python"; Args = @() }
    }

    return $null
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

function Ensure-Venv {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectDir
    )

    $venvPython = Join-Path $ProjectDir ".venv\Scripts\python.exe"
    if ((Test-Path $venvPython) -and (Test-SupportedPython -PythonExe $venvPython)) {
        return $venvPython
    }

    if (Test-Path (Join-Path $ProjectDir ".venv")) {
        Write-Host "Existing .venv uses an unsupported Python version. Recreating it..."
        Remove-Item -Recurse -Force (Join-Path $ProjectDir ".venv")
    }

    $launcher = Find-PythonLauncher
    if (-not $launcher) {
        throw "Could not find a supported Python version. Install Python 3.10, 3.11, 3.12, or 3.13."
    }

    Write-Host "Creating local virtual environment..."
    Push-Location $ProjectDir
    try {
        Invoke-CheckedCommand -Command @($launcher.Exe) + $launcher.Args + @("-m", "venv", ".venv")
    }
    finally {
        Pop-Location
    }

    return $venvPython
}

function Ensure-ProjectInstall {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectDir,
        [Parameter(Mandatory = $true)]
        [string]$PythonExe
    )

    & $PythonExe -c "import yt_dlp, spotdl" *> $null
    if ($LASTEXITCODE -eq 0) {
        return
    }

    Write-Host "Installing project dependencies into .venv..."
    Push-Location $ProjectDir
    try {
        Invoke-CheckedCommand -Command @($PythonExe, "-m", "pip", "install", "--upgrade", "pip")
        Invoke-CheckedCommand -Command @($PythonExe, "-m", "pip", "install", "-e", ".")
    }
    finally {
        Pop-Location
    }
}

function Ensure-Ffmpeg {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectDir,
        [Parameter(Mandatory = $true)]
        [string]$PythonExe
    )

    & $PythonExe -c "from spotdl.utils.ffmpeg import is_ffmpeg_installed; raise SystemExit(0 if is_ffmpeg_installed() else 1)" *> $null
    if ($LASTEXITCODE -eq 0) {
        return
    }

    Write-Host "FFmpeg not found. Downloading it now..."
    Push-Location $ProjectDir
    try {
        Invoke-CheckedCommand -Command @($PythonExe, "-m", "spotdl", "--download-ffmpeg")
    }
    finally {
        Pop-Location
    }
}

function Test-RequiresUserAuth {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Args
    )

    foreach ($arg in $Args) {
        if ([string]::IsNullOrWhiteSpace($arg) -or $arg.StartsWith("-")) {
            continue
        }

        if (
            $arg -match "open\.spotify\.com/playlist/" -or
            $arg -match "open\.spotify\.com/user/" -or
            $arg -eq "saved" -or
            $arg -eq "all-user-playlists" -or
            $arg -eq "all-saved-playlists" -or
            $arg -eq "all-user-followed-artists" -or
            $arg -eq "all-user-saved-albums" -or
            $arg -like "playlist:*"
        ) {
            return $true
        }
    }

    return $false
}

function Test-HasExplicitOutput {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Args
    )

    return ($Args -contains "--output")
}

function Test-HasExplicitBitrate {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Args
    )

    return ($Args -contains "--bitrate")
}

function Test-HasExplicitCachePreference {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Args
    )

    return (($Args -contains "--use-cache-file") -or ($Args -contains "--no-cache"))
}

function Get-OperationInfo {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Args
    )

    $operations = @("download", "save", "web", "sync", "meta", "url")

    for ($index = 0; $index -lt $Args.Count; $index++) {
        $arg = $Args[$index]
        if ([string]::IsNullOrWhiteSpace($arg)) {
            continue
        }

        if ($operations -contains $arg.ToLowerInvariant()) {
            return @{
                Index = $index
                Name = $arg.ToLowerInvariant()
            }
        }

        if (-not $arg.StartsWith("-")) {
            break
        }
    }

    return $null
}

function Add-ArgsRespectingOperation {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Args,
        [Parameter(Mandatory = $true)]
        [string[]]$ArgsToInsert
    )

    $operationInfo = Get-OperationInfo -Args $Args
    if ($null -eq $operationInfo) {
        return $ArgsToInsert + $Args
    }

    $before = @($Args[0..$operationInfo.Index])
    $after = @()
    if ($operationInfo.Index + 1 -lt $Args.Count) {
        $after = @($Args[($operationInfo.Index + 1)..($Args.Count - 1)])
    }

    return $before + $ArgsToInsert + $after
}

function Test-ArtistQuery {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Args
    )

    foreach ($arg in $Args) {
        if ([string]::IsNullOrWhiteSpace($arg) -or $arg.StartsWith("-")) {
            continue
        }

        if (
            $arg -match "open\.spotify\.com/artist/" -or
            $arg -like "artist:*" -or
            $arg -match "music\.youtube\.com/(channel|browse)/" -or
            $arg -match "(^|/)(?:www\.)?youtube\.com/(channel|browse|c|user)/" -or
            $arg -match "(^|/)(?:www\.)?youtube\.com/@" -or
            $arg -like "ytartist:*"
        ) {
            return $true
        }
    }

    return $false
}

$projectDir = $PSScriptRoot
$outerDir = Split-Path -Parent $projectDir

Load-EnvFile -Path (Join-Path $projectDir ".spotdl.env")
if (-not $env:SPOTDL_CLIENT_ID -or -not $env:SPOTDL_CLIENT_SECRET) {
    Load-EnvFile -Path (Join-Path $outerDir ".spotdl.env")
}

if (-not $CliArgs -or $CliArgs.Count -eq 0) {
    Write-Host "No arguments were provided."
    Write-Host "Paste a Spotify or YouTube URL to download, or press Enter to cancel."
    $url = Read-Host "URL"
    if ([string]::IsNullOrWhiteSpace($url)) {
        Write-Host "Cancelled."
        exit 1
    }
    $CliArgs = @($url)
}

if (-not $env:SPOTDL_CLIENT_ID -or -not $env:SPOTDL_CLIENT_SECRET) {
    Write-Host "Using bundled Spotify app credentials."
    Write-Host "If you keep hitting rate limits, run ..\setup-spotify-creds.bat to save your own Spotify app credentials."
}
else {
    Write-Host "Using local Spotify app credentials from .spotdl.env."
}

$hasExplicitSpotifyAuth = $CliArgs -contains "--user-auth" -or $CliArgs -contains "--auth-token"
if (-not $hasExplicitSpotifyAuth -and (Test-RequiresUserAuth -Args $CliArgs)) {
    Write-Host "Playlist and library queries need Spotify user login. Enabling --user-auth automatically."
    $CliArgs = Add-ArgsRespectingOperation -Args $CliArgs -ArgsToInsert @("--user-auth")
}

$hasExplicitOutput = Test-HasExplicitOutput -Args $CliArgs
if (-not $hasExplicitOutput -and (Test-ArtistQuery -Args $CliArgs)) {
    Write-Host "Artist downloads will be organized as Artist\\Album\\Song."
    $CliArgs = Add-ArgsRespectingOperation `
        -Args $CliArgs `
        -ArgsToInsert @("--output", "{album-artist}/{album}/{title}.{output-ext}")
}

$hasExplicitBitrate = Test-HasExplicitBitrate -Args $CliArgs
if (-not $hasExplicitBitrate) {
    Write-Host "Using balanced audio quality (192k)."
    $CliArgs = Add-ArgsRespectingOperation -Args $CliArgs -ArgsToInsert @("--bitrate", "192k")
}

$hasExplicitCachePreference = Test-HasExplicitCachePreference -Args $CliArgs
if (-not $hasExplicitCachePreference) {
    Write-Host "Using Spotify metadata cache to reduce repeat requests."
    $CliArgs = Add-ArgsRespectingOperation -Args $CliArgs -ArgsToInsert @("--use-cache-file")
}

$pythonExe = Ensure-Venv -ProjectDir $projectDir
Ensure-ProjectInstall -ProjectDir $projectDir -PythonExe $pythonExe

$isHelpOnly = $CliArgs.Count -gt 0 -and $CliArgs[0] -in @("-h", "--help", "-v", "--version", "--download-ffmpeg")
if (-not $isHelpOnly) {
    Ensure-Ffmpeg -ProjectDir $projectDir -PythonExe $pythonExe
}

$spotdlArgs = @("-m", "spotdl")
$operationInfo = Get-OperationInfo -Args $CliArgs

if ($null -ne $operationInfo) {
    $spotdlArgs += $CliArgs[$operationInfo.Index]
}

if ($env:SPOTDL_CLIENT_ID -and $env:SPOTDL_CLIENT_SECRET) {
    $spotdlArgs += @("--client-id", $env:SPOTDL_CLIENT_ID, "--client-secret", $env:SPOTDL_CLIENT_SECRET)
}

if ($null -eq $operationInfo) {
    $spotdlArgs += $CliArgs
}
else {
    if ($operationInfo.Index -gt 0) {
        $spotdlArgs += $CliArgs[0..($operationInfo.Index - 1)]
    }

    if ($operationInfo.Index + 1 -lt $CliArgs.Count) {
        $spotdlArgs += $CliArgs[($operationInfo.Index + 1)..($CliArgs.Count - 1)]
    }
}

Push-Location $projectDir
try {
    & $pythonExe $spotdlArgs
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
