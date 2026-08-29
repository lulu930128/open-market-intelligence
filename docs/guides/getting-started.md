# Getting started

This guide covers the two supported ways to run Open Market Intelligence on Windows. Use the packaged release if you want to try OMI. Use a source checkout if you plan to develop or inspect the code.

## Option 1: packaged Windows release

The packaged release includes compatible Python and Node.js runtimes. You do not need to install them separately.

1. Download <code>OpenMarketIntelligence-TW-v&lt;version&gt;-win-x64.zip</code> from [Releases](https://github.com/lulu930128/open-market-intelligence/releases).
2. Extract the entire folder to a writable location.
3. Open the extracted folder and run <code>Start-OMI-Launcher.cmd</code>.
4. Use the OMI tray menu to open the dashboard or API health page.

Do not run the launcher from Windows zip preview. Preview mode copies only the command file to a temporary folder, so the adjacent runtime files will be missing.

The packaged application keeps writable data and logs outside the extracted application folder:

~~~text
%LOCALAPPDATA%\Open Market Intelligence
~~~

## Option 2: source checkout

### Requirements

- Windows PowerShell
- Python 3.11 or later
- Node.js 20.9 or later
- npm 10 or later

### Install the backend

Run these commands from the repository root:

~~~powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt

if (-not (Test-Path .env)) {
  Copy-Item .env.example .env
}

$env:PYTHONPATH = (Resolve-Path backend).Path
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m app.scripts.seed_sources
~~~

The default SQLite database is stored at <code>data\open_market_intelligence.db</code>. Do not copy another user’s database into a new installation.

### Install the frontend

~~~powershell
Set-Location frontend
npm install

if (-not (Test-Path .env.local)) {
  Copy-Item .env.example .env.local
}

Set-Location ..
~~~

### Start OMI

From the repository root:

~~~powershell
.\Start-OMI-Launcher.cmd
~~~

The launcher starts the tray application, backend, and frontend. Its preferred ports are:

- backend: <code>8400</code>
- frontend: <code>3000</code>

These are preferences, not fixed promises. If a port is occupied or reserved by Windows, the launcher selects another bindable port and passes the selected value to the runtime.

Use the tray menu to open the actual dashboard or health page. You can also inspect:

~~~text
logs\launcher\<date>\launcher.log
~~~

Look for <code>selected=</code> rather than assuming the preferred port was used.

## First launch

On an empty installation, OMI enqueues one bounded Taiwan symbol bootstrap job using official TWSE and TPEx sources. The application can open while this job is running.

If a provider is temporarily unavailable:

- OMI still starts;
- the failed or incomplete state remains visible in job and source records;
- missing values are not silently replaced with a successful result.

The repository and packaged release do not contain the developer’s personal SQLite database, watchlists, credentials, or stock-master seed.

## Configuration and secrets

Backend settings belong in the repository-root <code>.env</code>. Browser-visible frontend settings belong in <code>frontend\.env.local</code>.

Never commit:

- API tokens, passwords, account identifiers, or certificates;
- personal watchlists or portfolio data;
- SQLite databases, logs, caches, or generated reports.

The tracked examples document the available settings:

- [backend environment example](../../.env.example)
- [frontend environment example](../../frontend/.env.example)

For optional KGI live quotes and read-only holdings sync, use the separate [KGI SuperPy guide](kgi-superpy.md).

## Common checks

### The launcher window appears and closes

Open the latest file under <code>logs\launcher\&lt;date&gt;\</code>. A port conflict, missing runtime, or failed migration should be recorded there.

### The usual URL does not open

Use **Open Dashboard** from the tray menu. The launcher may have selected a different frontend port.

### The dashboard opens but has little data

Check the update status and source disclosure in OMI. A new installation may still be importing the Taiwan symbol list, or a provider may be temporarily unavailable.

### You are setting up a development environment

Continue with the [development guide](development.md).
