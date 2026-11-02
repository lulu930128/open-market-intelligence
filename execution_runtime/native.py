"""Explicit, OMI-local SDK login factory. Importing this module performs no IO.

Only the dedicated headless process calls this factory. The returned binding is
transferred to KgiSessionOwner; this module has no order or journal operations.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import os
import struct
import sys

from execution.validation import require
from .kgi import SessionBinding
from .storage import OwnerLease


def taipei_day():
    return datetime.now(timezone(timedelta(hours=8))).date().isoformat()


def _setting(environment, name):
    # Match the existing OMI bridge's outer whitespace/quote normalization.
    return str(environment.get(name) or "").strip().strip('"').strip("'")


@dataclass(frozen=True)
class NativeSettings:
    simulation: bool
    person_id: str = field(repr=False)
    password: str = field(repr=False)
    account: str = field(default="", repr=False)

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
        return cls(mode in {"true", "1", "yes", "on"}, person, password,
                   _setting(env, "KGI_SUPERPY_TW_ACCOUNT"))


def select_account(accounts, configured):
    """Same selection semantics as OMI's quote/holdings bridge, without importing it."""
    require(type(accounts) is list, "KGI_ACCOUNT_DISCOVERY_INVALID")
    candidates = list(dict.fromkeys(
        str(item.get("account") or "").strip() for item in accounts
        if isinstance(item, dict) and "證券" in str(item.get("account_flag") or "")
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

    def _connect(self):
        require(self._owner_lease.held, "KGI_OWNER_LEASE_REQUIRED")
        require(not self._failed, "KGI_FACTORY_FAILED_NO_RETRY")
        require(self.current_day() == self.trade_date, "SESSION_DATE_EXPIRED")
        api = None
        try:
            sdk = self._sdk_loader()
            api = sdk.login(self.settings.person_id, self.settings.password, self.settings.simulation)
            require(callable(getattr(api, "show_account", None))
                    and callable(getattr(api, "set_Account", None))
                    and callable(getattr(api, "logout", None)), "KGI_LOGIN_INCOMPLETE")
            selected = select_account(api.show_account(), self.settings.account)
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
            return SessionBinding(api, sdk, selected, self.trade_date, self.current_day,
                                  cash_inventory_required=True)
        except BaseException:
            # A failed/partially opened factory is never retried in this process.
            self._failed = True
            if api is not None:
                close_api(api)
            raise
