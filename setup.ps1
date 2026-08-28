[CmdletBinding()]
param(
    [string]$RepoRoot = $PSScriptRoot,
    [string]$DataDir,
    [string]$WorkingDir,
    [switch]$NoShortcut,
    [switch]$NoMigrate
)

$ErrorActionPreference = "Stop"
$InvocationCwd = (Get-Location).ProviderPath

function ConvertTo-AbsolutePath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Value
    )

    $expanded = [Environment]::ExpandEnvironmentVariables($Value)
    if ([System.IO.Path]::IsPathRooted($expanded)) {
        return [System.IO.Path]::GetFullPath($expanded)
    }
    return [System.IO.Path]::GetFullPath((Join-Path -Path $InvocationCwd -ChildPath $expanded))
}

$RepoRoot = ConvertTo-AbsolutePath $RepoRoot
if (-not $DataDir) {
    if (-not $env:APPDATA) {
        throw "APPDATA is not defined; specify -DataDir explicitly."
    }
    $DataDir = Join-Path -Path $env:APPDATA -ChildPath "RTUForge"
}
$DataDir = ConvertTo-AbsolutePath $DataDir
if (-not $WorkingDir) {
    $WorkingDir = $DataDir
}
$WorkingDir = ConvertTo-AbsolutePath $WorkingDir

if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot "pyproject.toml") -PathType Leaf)) {
    throw "RepoRoot does not contain pyproject.toml: $RepoRoot"
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv is required but was not found in PATH."
}

New-Item -ItemType Directory -Force -Path $DataDir, $WorkingDir | Out-Null

& uv tool install --editable $RepoRoot --force
if ($LASTEXITCODE -ne 0) {
    throw "uv tool install failed with exit code $LASTEXITCODE"
}
& uv tool update-shell
if ($LASTEXITCODE -ne 0) {
    throw "uv tool update-shell failed with exit code $LASTEXITCODE"
}

$ToolBinOutput = & uv tool dir --bin
if ($LASTEXITCODE -ne 0) {
    throw "uv tool dir --bin failed with exit code $LASTEXITCODE"
}
$ToolBin = ConvertTo-AbsolutePath (($ToolBinOutput | Select-Object -Last 1).Trim())
$RtuForgeExe = Join-Path -Path $ToolBin -ChildPath "rtuforge.exe"
if (-not (Test-Path -LiteralPath $RtuForgeExe -PathType Leaf)) {
    throw "Installed executable was not found: $RtuForgeExe"
}

[Environment]::SetEnvironmentVariable("RTUFORGE_HOME", $DataDir, "User")
$env:RTUFORGE_HOME = $DataDir

if (-not $NoMigrate) {
    foreach ($Name in @("config.ini", "scripts.ini", ".rtuforge_history")) {
        $Source = Join-Path -Path $RepoRoot -ChildPath $Name
        $Destination = Join-Path -Path $DataDir -ChildPath $Name
        if ((Test-Path -LiteralPath $Source -PathType Leaf) -and
            -not (Test-Path -LiteralPath $Destination)) {
            Copy-Item -LiteralPath $Source -Destination $Destination
            Write-Host "Migrated without overwrite: $Destination"
        }
    }
}

$ShortcutPath = "not created"
if (-not $NoShortcut) {
    $DesktopDir = [Environment]::GetFolderPath([Environment+SpecialFolder]::DesktopDirectory)
    if (-not $DesktopDir) {
        throw "Unable to determine the current user's Desktop directory."
    }
    $ShortcutPath = Join-Path -Path $DesktopDir -ChildPath "RTU Forge.lnk"
    $WshShell = New-Object -ComObject WScript.Shell
    $Shortcut = $WshShell.CreateShortcut($ShortcutPath)
    $Shortcut.TargetPath = $RtuForgeExe
    $Shortcut.Arguments = '--home "' + $DataDir + '"'
    $Shortcut.WorkingDirectory = $WorkingDir
    $Shortcut.Description = "RTU Forge Modbus RTU console"
    $Shortcut.Save()
}

Write-Host "Running self-check..."
& $RtuForgeExe --help | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "rtuforge --help self-check failed with exit code $LASTEXITCODE"
}
& $RtuForgeExe paths
if ($LASTEXITCODE -ne 0) {
    throw "rtuforge paths self-check failed with exit code $LASTEXITCODE"
}

Write-Host ""
Write-Host "Repository:    $RepoRoot"
Write-Host "Data/Home:     $DataDir"
Write-Host "Working dir:   $WorkingDir"
Write-Host "Tool bin:      $ToolBin"
Write-Host "Executable:    $RtuForgeExe"
Write-Host "RTUFORGE_HOME: $env:RTUFORGE_HOME"
Write-Host "Shortcut:      $ShortcutPath"
