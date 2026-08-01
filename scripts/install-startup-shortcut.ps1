$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$launcherScript = Join-Path $repoRoot "scripts\omi-launcher.ps1"
$iconPath = Join-Path $repoRoot "OMI.ico"
$startupFolder = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startupFolder "Open Market Intelligence Launcher.lnk"
$powershellPath = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"

if (-not (Test-Path -LiteralPath $launcherScript)) {
    throw "Launcher script not found: $launcherScript"
}

if (-not (Test-Path -LiteralPath $powershellPath)) {
    throw "PowerShell executable not found: $powershellPath"
}

if (-not (Test-Path -LiteralPath $startupFolder)) {
    New-Item -ItemType Directory -Force -Path $startupFolder | Out-Null
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $powershellPath
$shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -STA -WindowStyle Hidden -File `"$launcherScript`""
$shortcut.WorkingDirectory = $repoRoot
$shortcut.Description = "Start Open Market Intelligence launcher in the system tray."

if (Test-Path -LiteralPath $iconPath) {
    $shortcut.IconLocation = $iconPath
}

$shortcut.Save()

[PSCustomObject]@{
    Shortcut = $shortcutPath
    Target = $shortcut.TargetPath
    Arguments = $shortcut.Arguments
    WorkingDirectory = $shortcut.WorkingDirectory
}
