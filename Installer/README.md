# Installer workspace

This folder builds the first Windows download package for the Taiwan market
watchstation edition of Open Market Intelligence.

The installer workspace is not the application install directory. It is only a
build area. Generated runtime files, staging files, and zip outputs are ignored
by git.

## Output

`package.ps1` creates:

```text
Installer/output/OpenMarketIntelligence-TW-v<version>-win-x64.zip
```

The zip is intended for users who do not have Python, Node.js, or npm installed.
After extraction they run:

```text
Start-OMI-Launcher.cmd
```

The launcher starts the backend and frontend in the system tray, then opens:

```text
http://127.0.0.1:3000
```

## Build

From the repo root:

```powershell
.\Installer\package.ps1 -Version 1.0.0
```

To include the current local SQLite database as a seed database:

```powershell
.\Installer\package.ps1 -Version 1.0.0 -IncludeSeedData
```

`-IncludeSeedData` can make the zip very large and may include local watchlists.
Use it only for packages that are safe to share.

## Runtime layout

Inside the generated package:

```text
OpenMarketIntelligence-TW-v<version>-win-x64/
  backend/
  frontend/
  runtime/
    python/
    node/
  scripts/
  Start-OMI-Launcher.cmd
  release-manifest.json
```

Writable user data and logs are stored outside the package:

```text
%LOCALAPPDATA%\Open Market Intelligence
```

This keeps the extracted application folder read-only and avoids permission
issues under protected Windows folders.
