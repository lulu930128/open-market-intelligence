# Optional KGI SuperPy setup

KGI SuperPy is an optional integration for selected Taiwan stock live quotes and explicitly requested read-only holdings sync. OMI does not expose order placement through this bridge.

## What the integration does

For the Taiwan stock currently open in the interface, OMI can request:

- live trades;
- five-level order-book data;
- pre-open trial matching.

The frontend creates a viewer lease with a time-to-live. The isolated KGI process starts and subscribes when the first viewer appears, then unsubscribes after the last viewer leaves.

Until KGI supplies a qualified event—or when the connection is stale or unavailable—the backend keeps its existing TWSE MIS or local snapshot path and exposes the fallback in the quote contract.

The same isolated runtime supports a user-triggered, read-only holdings sync:

- Taiwan: <code>Account.InventorySum</code>
- US: <code>SubAccount.StockPositionReport</code>

A successful sync replaces holdings only for the selected market. Provider, login, permission, or payload validation failures leave existing holdings unchanged. If the US interface does not provide cost, OMI stores it as <code>null</code> rather than substituting the current price.

## Before installation

Complete KGI’s official certificate component, certificate application, and API qualification process. Use the KGI certificate helper to confirm that the ActiveX and certificate environment checks pass.

If KGI reports <code>CheckCAComponent</code> or <code>CoCreateInstance</code> failures, repair the certificate support components before testing OMI.

KGI login uses <code>person_id</code>, <code>person_pwd</code>, and <code>simulation</code>. The Windows certificate environment is validated before the quote token and <code>Quote</code> service are created.

## Install the isolated runtime

The KGI SDK must run in an isolated 64-bit Python 3.12 environment. This keeps its large dependencies and trading objects out of the main backend process.

From the repository root:

~~~powershell
.\scripts\setup-kgi-superpy.ps1
~~~

The setup script looks for Python 3.12 through the Windows <code>py</code> launcher and rejects unsupported versions.

If <code>.venv-kgi</code> was created with another Python version, recreate it explicitly:

~~~powershell
.\scripts\setup-kgi-superpy.ps1 -Recreate
~~~

OMI does not disable TLS certificate verification to bypass certificate errors.

## Configure credentials locally

Add these values only to the untracked repository-root <code>.env</code>:

~~~dotenv
ENABLE_KGI_SUPERPY_QUOTE=true
KGI_SUPERPY_PERSON_ID=your_person_id
KGI_SUPERPY_PASSWORD=your_password
KGI_SUPERPY_SIMULATION=false
~~~

Never put real credentials in <code>.env.example</code>, <code>frontend\.env.local</code>, documentation, logs, or Git.

The default interpreter is:

~~~text
.venv-kgi\Scripts\python.exe
~~~

If you set <code>KGI_SUPERPY_PYTHON</code>, it must point to an isolated 64-bit Python 3.12 environment. Lease, freshness, timeout, and optional account-selection settings are documented in [<code>.env.example</code>](../../.env.example).

If login returns exactly one matching securities or sub-brokerage account, OMI selects it automatically. When multiple accounts are available, select one explicitly with:

- <code>KGI_SUPERPY_TW_ACCOUNT</code>
- <code>KGI_SUPERPY_US_ACCOUNT</code>

## Bounded KGI data request

KGI <code>Quote</code> and <code>Data</code> permissions are separate. OMI provides an explicit bounded endpoint:

~~~text
POST /api/market/kgi-data/{stock_id}/backfill
~~~

Its allowlist is limited to:

- intraday snapshot;
- same-day trades;
- historical minute bars;
- volume by price.

One request makes at most four provider requests. Each item returns at most 500 rows, and volume-by-price covers at most five days. Item status remains visible as <code>available</code>, <code>empty</code>, <code>plan_restricted</code>, or <code>failed</code>.

These responses are bounded raw records. They are not written to canonical historical market tables.

## Safety boundary

- The bridge accepts no order command.
- Credentials remain in the local backend environment.
- Provider or validation failure does not erase existing holdings.
- Missing cost remains missing.
- KGI failure does not masquerade as a successful live quote.
