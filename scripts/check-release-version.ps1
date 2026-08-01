param(
    [string]$RepoRoot = ""
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
}
else {
    $RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
}

$version = (Get-Content -LiteralPath (Join-Path $RepoRoot "VERSION") -Raw -Encoding UTF8).Trim()
if ($version -notmatch '^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$') {
    throw "VERSION is not valid semantic version text: $version"
}

$packagePath = Join-Path $RepoRoot "frontend\package.json"
$packageLockPath = Join-Path $RepoRoot "frontend\package-lock.json"
$packageVersion = (& node -e "const fs=require('fs'); console.log(JSON.parse(fs.readFileSync(process.argv[1], 'utf8')).version);" $packagePath).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Could not read frontend package version."
}

$packageLockVersions = @(& node -e "const fs=require('fs'); const lock=JSON.parse(fs.readFileSync(process.argv[1], 'utf8')); console.log(lock.version); console.log(lock.packages[''].version);" $packageLockPath)
if ($LASTEXITCODE -ne 0 -or $packageLockVersions.Count -ne 2) {
    throw "Could not read frontend package-lock versions."
}

$versions = [ordered]@{
    VERSION = $version
    package_json = $packageVersion
    package_lock = $packageLockVersions[0].Trim()
    package_lock_root = $packageLockVersions[1].Trim()
}

$mismatches = @($versions.GetEnumerator() | Where-Object { $_.Value -ne $version })
if ($mismatches.Count -gt 0) {
    $detail = $mismatches | ForEach-Object { "$($_.Key)=$($_.Value)" }
    throw "Release version mismatch. expected=$version actual=$($detail -join ', ')"
}

Write-Host "Release version is consistent: $version"
