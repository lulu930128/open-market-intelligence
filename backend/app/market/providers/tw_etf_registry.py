from __future__ import annotations

from collections.abc import Iterable

from app.market.providers.tw_etf_contracts import (
    TaiwanEtfInavProviderResource,
    TaiwanEtfInstrumentIdentity,
    TaiwanEtfPcfProviderResource,
    TaiwanEtfProviderBinding,
)
from app.market.providers.tw_etf_capital import (
    CAPITAL_INAV_PAGE_URL,
    CAPITAL_PROVIDER,
    fetch_capital_etf_inav,
)
from app.market.providers.tw_etf_cathay import (
    CATHAY_INAV_PAGE_URL,
    CATHAY_PCF_PAGE_URL,
    CATHAY_PROVIDER,
    fetch_cathay_etf_inav,
    fetch_cathay_etf_pcf,
)
from app.market.providers.tw_etf_fubon import (
    FUBON_INAV_URL,
    FUBON_PCF_URL_TEMPLATE,
    FUBON_PROVIDER,
    fetch_fubon_etf_inav,
    fetch_fubon_etf_pcf,
)
from app.market.providers.tw_etf_fuh_hwa import (
    FUH_HWA_INAV_URL,
    FUH_HWA_PROVIDER,
    fetch_fuh_hwa_etf_inav,
)
from app.market.providers.tw_etf_nomura import (
    NOMURA_INAV_PAGE_URL,
    NOMURA_PROVIDER,
    fetch_nomura_etf_inav,
)
from app.market.providers.tw_etf_upamc import (
    UPAMC_PCF_PAGE_URL,
    UPAMC_PROVIDER,
    fetch_upamc_etf_pcf,
)
from app.market.providers.tw_etf_yuanta import (
    YUANTA_ETF_API_URL,
    YUANTA_INAV_HTTP_REQUEST_COUNT,
    YUANTA_INAV_HUB_URL,
    YUANTA_PROVIDER,
    fetch_yuanta_etf_inav,
    fetch_yuanta_etf_pcf,
)


def _normalized_identity(value: str | None) -> str:
    return "".join(str(value or "").split()).casefold()


class TaiwanEtfProviderRegistryError(RuntimeError):
    pass


class TaiwanEtfProviderRegistry:
    def __init__(self, bindings: Iterable[TaiwanEtfProviderBinding]) -> None:
        self._bindings = tuple(bindings)
        provider_ids = [binding.provider for binding in self._bindings]
        if len(provider_ids) != len(set(provider_ids)):
            raise ValueError("ETF provider registry contains duplicate provider ids.")

    @property
    def bindings(self) -> tuple[TaiwanEtfProviderBinding, ...]:
        return self._bindings

    def get(self, provider: str) -> TaiwanEtfProviderBinding | None:
        normalized_provider = provider.strip().casefold()
        return next(
            (
                binding
                for binding in self._bindings
                if binding.provider.casefold() == normalized_provider
            ),
            None,
        )

    def resolve(
        self,
        identity: TaiwanEtfInstrumentIdentity,
    ) -> TaiwanEtfProviderBinding | None:
        normalized_code = _normalized_identity(identity.issuer_code)
        normalized_names = tuple(
            _normalized_identity(value) for value in identity.name_candidates()
        )
        matches: list[TaiwanEtfProviderBinding] = []
        for binding in self._bindings:
            if not binding.supports_market(identity.market):
                continue
            normalized_codes = {
                _normalized_identity(code) for code in binding.issuer_codes
            }
            normalized_aliases = tuple(
                _normalized_identity(alias) for alias in binding.issuer_aliases
            )
            code_matches = bool(
                normalized_code and normalized_code in normalized_codes
            )
            name_matches = any(
                candidate.startswith(alias)
                for candidate in normalized_names
                for alias in normalized_aliases
                if alias
            )
            if code_matches or name_matches:
                matches.append(binding)
        if len(matches) > 1:
            providers = ", ".join(binding.provider for binding in matches)
            raise TaiwanEtfProviderRegistryError(
                f"ETF issuer identity for stock_id={identity.stock_id} matched "
                f"multiple providers: {providers}."
            )
        return matches[0] if matches else None


YUANTA_ETF_PROVIDER_BINDING = TaiwanEtfProviderBinding(
    provider=YUANTA_PROVIDER,
    issuer_codes=frozenset({"A0005"}),
    issuer_aliases=("元大", "YUANTA"),
    markets=frozenset({"TWSE"}),
    pcf=TaiwanEtfPcfProviderResource(
        source_url=YUANTA_ETF_API_URL,
        request_count=1,
        fetch=fetch_yuanta_etf_pcf,
        includes_component_exposure=True,
        unit_nav_is_daily_nav=True,
    ),
    intraday_nav=TaiwanEtfInavProviderResource(
        source_url=YUANTA_INAV_HUB_URL,
        request_count=YUANTA_INAV_HTTP_REQUEST_COUNT,
        fetch=fetch_yuanta_etf_inav,
    ),
)

FUBON_ETF_PROVIDER_BINDING = TaiwanEtfProviderBinding(
    provider=FUBON_PROVIDER,
    issuer_codes=frozenset({"A0010"}),
    issuer_aliases=("富邦", "FUBON", "FB"),
    markets=frozenset({"TWSE"}),
    pcf=TaiwanEtfPcfProviderResource(
        source_url=FUBON_PCF_URL_TEMPLATE,
        request_count=1,
        fetch=fetch_fubon_etf_pcf,
        includes_component_exposure=False,
        unit_nav_is_daily_nav=True,
    ),
    intraday_nav=TaiwanEtfInavProviderResource(
        source_url=FUBON_INAV_URL,
        request_count=1,
        fetch=fetch_fubon_etf_inav,
    ),
)

UPAMC_ETF_PROVIDER_BINDING = TaiwanEtfProviderBinding(
    provider=UPAMC_PROVIDER,
    issuer_codes=frozenset({"A0009"}),
    issuer_aliases=("統一", "UPAMC"),
    markets=frozenset({"TWSE"}),
    pcf=TaiwanEtfPcfProviderResource(
        source_url=UPAMC_PCF_PAGE_URL,
        request_count=2,
        fetch=fetch_upamc_etf_pcf,
        includes_component_exposure=False,
        unit_nav_is_daily_nav=True,
    ),
)

CAPITAL_ETF_PROVIDER_BINDING = TaiwanEtfProviderBinding(
    provider=CAPITAL_PROVIDER,
    issuer_codes=frozenset({"A0016"}),
    issuer_aliases=("群益", "CAPITAL"),
    markets=frozenset({"TWSE"}),
    intraday_nav=TaiwanEtfInavProviderResource(
        source_url=CAPITAL_INAV_PAGE_URL,
        request_count=1,
        fetch=fetch_capital_etf_inav,
    ),
)

FUH_HWA_ETF_PROVIDER_BINDING = TaiwanEtfProviderBinding(
    provider=FUH_HWA_PROVIDER,
    issuer_codes=frozenset({"A0022"}),
    issuer_aliases=("復華", "FHC"),
    markets=frozenset({"TWSE"}),
    intraday_nav=TaiwanEtfInavProviderResource(
        source_url=FUH_HWA_INAV_URL,
        request_count=1,
        fetch=fetch_fuh_hwa_etf_inav,
    ),
)

NOMURA_ETF_PROVIDER_BINDING = TaiwanEtfProviderBinding(
    provider=NOMURA_PROVIDER,
    issuer_codes=frozenset({"A0032"}),
    issuer_aliases=("野村", "NOMURA"),
    markets=frozenset({"TWSE"}),
    intraday_nav=TaiwanEtfInavProviderResource(
        source_url=NOMURA_INAV_PAGE_URL,
        request_count=1,
        fetch=fetch_nomura_etf_inav,
    ),
)

CATHAY_ETF_PROVIDER_BINDING = TaiwanEtfProviderBinding(
    provider=CATHAY_PROVIDER,
    issuer_codes=frozenset({"A0037"}),
    issuer_aliases=("國泰", "CATHAY"),
    markets=frozenset({"TWSE"}),
    pcf=TaiwanEtfPcfProviderResource(
        source_url=CATHAY_PCF_PAGE_URL,
        request_count=2,
        fetch=fetch_cathay_etf_pcf,
        includes_component_exposure=False,
        unit_nav_is_daily_nav=True,
    ),
    intraday_nav=TaiwanEtfInavProviderResource(
        source_url=CATHAY_INAV_PAGE_URL,
        request_count=2,
        fetch=fetch_cathay_etf_inav,
    ),
)

DEFAULT_TAIWAN_ETF_PROVIDER_REGISTRY = TaiwanEtfProviderRegistry(
    (
        YUANTA_ETF_PROVIDER_BINDING,
        FUBON_ETF_PROVIDER_BINDING,
        UPAMC_ETF_PROVIDER_BINDING,
        CAPITAL_ETF_PROVIDER_BINDING,
        FUH_HWA_ETF_PROVIDER_BINDING,
        NOMURA_ETF_PROVIDER_BINDING,
        CATHAY_ETF_PROVIDER_BINDING,
    )
)


__all__ = [
    "DEFAULT_TAIWAN_ETF_PROVIDER_REGISTRY",
    "CAPITAL_ETF_PROVIDER_BINDING",
    "CATHAY_ETF_PROVIDER_BINDING",
    "FUBON_ETF_PROVIDER_BINDING",
    "FUH_HWA_ETF_PROVIDER_BINDING",
    "NOMURA_ETF_PROVIDER_BINDING",
    "TaiwanEtfProviderRegistry",
    "TaiwanEtfProviderRegistryError",
    "UPAMC_ETF_PROVIDER_BINDING",
    "YUANTA_ETF_PROVIDER_BINDING",
]
