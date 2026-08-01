# Installer workspace

This folder builds the Windows download package for the Taiwan-first Open
Market Intelligence research workbench.

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

Users must extract the whole zip folder first. Running `Start-OMI-Launcher.cmd`
from the Windows zip preview opens only a temporary copy of the `.cmd` file, so
the adjacent `scripts/` runtime files will be missing.

The launcher starts the backend and frontend in the system tray, then opens:

```text
http://127.0.0.1:3000
```

## Build

From the repo root:

```powershell
.\Installer\package.ps1
```

The default version comes from the repository root `VERSION` file. To build a
prerelease or test package without changing that file, pass an explicit
`-Version` value.

The bundled Python runtime currently targets Python 3.13.9. Because the package
copies native backend wheels from `.venv`, that virtual environment must use the
same Python 3.13 ABI. The script checks this before copying dependencies and
fails with an actionable message instead of producing an unusable archive.

By default the package creates a lightweight seed database from the local
`data/open_market_intelligence.db`. The seed only includes `source_registry` and
`stock_master`, so first-run stock search and watchlist add flows can resolve
symbols such as `2330` without bundling the full local history database.

To build a package with no stock master seed:

```powershell
.\Installer\package.ps1 -SkipStockMasterSeed
```

To include the current local SQLite database as a full seed database:

```powershell
.\Installer\package.ps1 -IncludeSeedData
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
