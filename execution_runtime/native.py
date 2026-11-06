"""Explicit, OMI-local SDK login factory. Importing this module performs no IO.

Only the dedicated headless process calls this factory. The returned binding is
transferred to KgiSessionOwner; this module has no order or journal operations.
"""

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
import os
import struct
import sys

from execution.validation import require
from execution.contracts import ExecutionRejected
from .kgi import SessionBinding
from .storage import OwnerLease
from .us_contracts import UsAccountBinding


def taipei_day():
    return datetime.now(timezone(timedelta(hours=8))).date().isoformat()


def us_submission_day():
    # Local journal scope only. Never presented as the broker's business date.
    return datetime.now(timezone.utc).date().isoformat()


def _setting(environment, name):
    # Match the existing OMI bridge's outer whitespace/quote normalization.
    return str(environment.get(name) or "").strip().strip('"').strip("'")


@dataclass(frozen=True)
class NativeSettings:
    simulation: bool
    person_id: str = field(repr=False)
    password: str = field(repr=False)
    account: str = field(default="", repr=False)
    us_enabled: bool = False
    us_account: str = field(default="", repr=False)

    def __post_init__(self):
        require(type(self.us_enabled) is bool, "INVALID_US_ENABLE_SETTING")
        require(not self.us_enabled or not self.simulation, "US_SIMULATION_UNAVAILABLE")

    @classmethod
    def from_environment(cls, environment=None):
        # No dotenv/file/other-project fallback. Called only after explicit connect.
        env = os.environ if environment is None else environment
        mode = _setting(env, "KGI_SUPERPY_SIMULATION").lower()
        require(mode in {"true", "false", "1", "0", "yes", "no", "on", "off"},
                "KGI_SIMULATION_MUST_BE_EXPLICIT")
        person = _setting(env, "KGI_SUPERPY_PERSON_ID")
        password = _setting(env, "KGI_SUPERPY_PASSWORD")
        require(bool(person and password), "KGI_CREDENTIALS_MISSING")
        # Production reconnects both research markets on the same login so
        # persisted per-order US protection resumes after a process restart.
        # Keep an explicit legacy override and never bind US in simulation.
        simulation = mode in {"true", "1", "yes", "on"}
        us_mode = _setting(env, "KGI_SUPERPY_US_ENABLED").lower() or ("false" if simulation else "true")
        require(us_mode in {"true", "false", "1", "0", "yes", "no", "on", "off"}, "INVALID_US_ENABLE_SETTING")
        return cls(simulation, person, password,
                   _setting(env, "KGI_SUPERPY_TW_ACCOUNT"), us_mode in {"true", "1", "yes", "on"},
                   _setting(env, "KGI_SUPERPY_US_ACCOUNT"))


def select_account(accounts, configured, *, market="TW"):
    """Same selection semantics as OMI's quote/holdings bridge, without importing it."""
    require(type(accounts) is list, "KGI_ACCOUNT_DISCOVERY_INVALID")
    require(market in {"TW", "US"}, "UNSUPPORTED_ACCOUNT_MARKET")
    flag = "證券" if market == "TW" else "複委託"
    candidates = list(dict.fromkeys(
        str(item.get("account") or "").strip() for item in accounts
        if isinstance(item, dict) and flag in str(item.get("account_flag") or "")
        and str(item.get("account") or "").strip()))
    if configured:
        require(configured in candidates, "KGI_CONFIGURED_ACCOUNT_UNAVAILABLE")
        return configured
    require(bool(candidates), "KGI_ACCOUNT_UNAVAILABLE")
    require(len(candidates) == 1, "KGI_ACCOUNT_SELECTION_REQUIRED")
    return candidates[0]


def load_sdk():
    require(sys.platform == "win32" and sys.version_info[:2] == (3, 12)
            and struct.calcsize("P") == 8, "KGI_REQUIRES_WINDOWS_PY312_X64")
    # The only native import owner. No login, credentials or session at import.
    import kgisuperpy
    return kgisuperpy


def close_api(api):
    logout = getattr(api, "logout", None)
    if not callable(logout):
        # Same partial-login cleanup supported by the OMI quote bridge.
        logout = getattr(getattr(api, "_ObjOrder", None), "Logout", None)
    require(callable(logout), "KGI_SESSION_CLOSE_UNVERIFIED")
    logout()


class NativeSessionFactory:
    def __init__(self, settings, *, owner_lease, sdk_loader=load_sdk, current_day=taipei_day):
        require(type(owner_lease) is OwnerLease and owner_lease.held, "KGI_OWNER_LEASE_REQUIRED")
        self._owner_lease = owner_lease
        self.settings = settings
        self._sdk_loader = sdk_loader
        self.current_day = current_day
        self.trade_date = current_day()
        self._prepared = None
        self._selected_account = None
        self._selected_us_account = None
        self._us_requested = False
        self._failed = False

    def prepare(self):
        """Discover account once under the process lease, then hand off this session."""
        require(self._prepared is None and self._selected_account is None, "KGI_ALREADY_PREPARED")
        self._prepared = self._connect()
        return self._prepared

    def __call__(self):
        if self._prepared is not None:
            binding, self._prepared = self._prepared, None
            return binding
        return self._connect()

    def close_unclaimed(self):
        if self._prepared is not None:
            close_api(self._prepared.api)
            self._prepared = None

    def _bind_us(self, api, sdk, accounts):
        us_account = select_account(accounts, self.settings.us_account, market="US")
        require(self._selected_us_account in {None, us_account}, "KGI_US_RECONNECT_ACCOUNT_CHANGED")
        require(callable(getattr(api, "set_SubAccount", None)), "KGI_US_INTERFACE_UNAVAILABLE")
        api.set_SubAccount(us_account)
        sub, sub_account = getattr(api, "SubOrder", None), getattr(api, "SubAccount", None)
        require(all(callable(getattr(sub, name, None)) for name in
                    ("set_event", "create_order", "get_trades", "cancel_order", "contract"))
                and all(callable(getattr(sub_account, name, None)) for name in ("OrderReport", "ExecReport"))
                and all(hasattr(getattr(sdk, "Currency", None), name) for name in ("TWD", "MUT")),
                "KGI_US_INTERFACE_UNAVAILABLE")
        self._selected_us_account = us_account
        return UsAccountBinding(us_account, "PRODUCTION")

    def prepare_us_probe(self, binding):
        """Explicit read-only discovery inside the existing owner's SDK lane.

        No second login, settings change, effect admission or journal creation.
        Probe-only binding is not an operational US context and does not change
        the TW date-rollover policy.
        """
        require(self._owner_lease.held, "KGI_OWNER_LEASE_REQUIRED")
        require(not self.settings.simulation and binding.native_session, "US_PROBE_REQUIRES_NATIVE_PRODUCTION")
        require(binding.account_id == self._selected_account, "SESSION_BINDING_MISMATCH")
        return self._bind_us(binding.api, binding.sdk, binding.api.show_account())

    def prepare_us_execution(self, binding, probe_context=None):
        """Bind the requested manual market on the existing production login."""
        require(self._owner_lease.held, "KGI_OWNER_LEASE_REQUIRED")
        require(not self.settings.simulation and binding.native_session, "US_SIMULATION_UNAVAILABLE")
        require(binding.account_id == self._selected_account, "SESSION_BINDING_MISMATCH")
        context = probe_context or self._bind_us(binding.api, binding.sdk, binding.api.show_account())
        require(context.account_id == self._selected_us_account, "SESSION_BINDING_MISMATCH")
        self._us_requested = True
        return replace(context, trade_date=us_submission_day(), current_day=us_submission_day)

    def _connect(self):
        require(self._owner_lease.held, "KGI_OWNER_LEASE_REQUIRED")
        require(not self._failed, "KGI_FACTORY_FAILED_NO_RETRY")
        # A new binding gets today's TW date; existing intents keep their date.
        self.trade_date = self.current_day()
        api = None
        login_entered = False
        try:
            sdk = self._sdk_loader()
            login_entered = True
            api = sdk.login(self.settings.person_id, self.settings.password, self.settings.simulation)
            require(callable(getattr(api, "show_account", None))
                    and callable(getattr(api, "set_Account", None))
                    and callable(getattr(api, "logout", None))
                    and callable(getattr(api, "set_disconnect_cb", None)), "KGI_LOGIN_INCOMPLETE")
            accounts = api.show_account()
            selected = select_account(accounts, self.settings.account)
            require(self._selected_account in {None, selected}, "KGI_RECONNECT_ACCOUNT_CHANGED")
            api.set_Account(selected)
            order, account = getattr(api, "Order", None), getattr(api, "Account", None)
            require(all(callable(getattr(order, name, None)) for name in
                        ("set_event", "create_order", "get_trades", "cancel_order"))
                    and callable(getattr(account, "OrderReport", None))
                    and (callable(getattr(order, "ExecReport", None))
                         or callable(getattr(account, "ExecReport", None))), "KGI_ORDER_INTERFACE_UNAVAILABLE")
            for name, members in (("Action", ("Buy", "Sell")), ("TimeInForce", ("ROD",)),
                                  ("OrderCond", ("CASH",)), ("OddLot", ("Odd", "Common"))):
                require(all(hasattr(getattr(sdk, name, None), member) for member in members),
                        "KGI_CONSTANTS_UNAVAILABLE")
            self._selected_account = selected
            us, us_reason = None, "US_DISABLED"
            if self.settings.us_enabled or self._us_requested:
                try:
                    us = self._bind_us(api, sdk, accounts)
                    us = replace(us, trade_date=us_submission_day(), current_day=us_submission_day)
                    us_reason = None
                except Exception as exc:
                    us_reason = exc.code if isinstance(exc, ExecutionRejected) else "KGI_US_BINDING_FAILED"
            return SessionBinding(api, sdk, selected, self.trade_date, self.current_day,
                                  cash_inventory_required=True, us=us, us_reason=us_reason, native_session=True)
        except BaseException as exc:
            # Only explicit transport exceptions are retryable. SDK 2.1.0 can
            # return an incomplete facade for auth/CA errors without raising;
            # never guess that such a failure is transient or parse private text.
            self._failed = not isinstance(exc, (TimeoutError, ConnectionError))
            if login_entered and api is None:
                # SDK login is a constructor: an exception can leave native
                # resources alive without returning an object we can close.
                self._failed = True
                raise ExecutionRejected("KGI_LOGIN_OUTCOME_UNKNOWN") from None
            if api is not None:
                try:
                    close_api(api)
                except BaseException:
                    self._failed = True
                    raise ExecutionRejected("KGI_SESSION_CLOSE_UNVERIFIED") from None
            raise
