$ErrorActionPreference = "Stop"

$startupFolder = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startupFolder "Open Market Intelligence Launcher.lnk"

if (Test-Path -LiteralPath $shortcutPath) {
    Remove-Item -LiteralPath $shortcutPath -Force
    "Removed startup shortcut: $shortcutPath"
}
else {
    "Startup shortcut was not installed: $shortcutPath"
}
