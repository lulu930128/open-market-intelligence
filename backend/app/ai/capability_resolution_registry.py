from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping, Protocol

from app.ai import public_contract


RESOLUTION_MODES = frozenset(
    {
        "reader_fetch",
        "granular_fill",
        "composite_fill",
        "scheduler_cache",
        "cache_only",
        "derived",
        "private",
        "key_required",
        "provider_not_connected",
        "not_applicable",
        "deprecated",
    }
)
IMPLEMENTATION_STATUSES = frozenset(
    {
        "connected",
        "connected_private",
        "connected_key_required_for_refresh",
        "provider_not_connected",
        "deprecated",
    }
)


class CapabilityLike(Protocol):
    capability_id: str
    scopes: tuple[str, ...]
    default_limit: int
    deprecated: bool
    replacement_capabilities: tuple[str, ...]
    side_effect_policy: str

    def fill_operation_for_scope(self, scope_type: str) -> str | None: ...

    def refresh_strategy_for_scope(self, scope_type: str) -> str: ...

    def refresh_requires_market_open_for_scope(self, scope_type: str) -> bool: ...


@dataclass(frozen=True)
class CapabilityResolutionSpec:
    scope_type: str
    capability_id: str
    implementation_status: str
    resolution_mode: str
    operation: str | None
    produces: tuple[str, ...]
    depends_on: tuple[str, ...]
    provider_contract_ids: tuple[str, ...]
    freshness_owner: str
    side_effect_policy: str
    trust_requirement: str
    bounds: tuple[tuple[str, int], ...]
    market_session_policy: str
    backgroundable: bool
    blocking_reason: str | None
    next_fill: str | None
    deprecated: bool
    replacement_capabilities: tuple[str, ...]

    @property
    def key(self) -> tuple[str, str]:
        return self.scope_type, self.capability_id

    def as_public_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["bounds"] = dict(self.bounds)
        return payload


PUBLIC_SCOPE_TYPES = tuple(
    dict.fromkeys(spec.internal_scope for spec in public_contract.TARGET_SPECS)
)

# These operations already exist in the backend allowlist but were not part of
# the legacy granular fill-operation registry.  They are canonical owners for
# the scoped capabilities below; activation in fill planning is intentionally
# handled by the capability-contract facade rather than by consumers.
SCOPED_COMPOSITE_OPERATIONS: dict[tuple[str, str], str] = {
    ("stock", "cross_market.overnight"): "cross_market.refresh_context",
    ("stock", "cross_market.relations"): "cross_market.refresh_context",
    ("stock", "cross_market.parity"): "cross_market.refresh_context",
    ("watchlist", "watchlist.ranking"): "tw.refresh_watchlist_evidence",
    ("watchlist", "watchlist.radar"): "tw.refresh_watchlist_evidence",
    ("us_stock", "company.profile"): "us.refresh_company_profile",
    ("us_stock", "corporate.actions"): "us.refresh_corporate_actions",
}
COMPOSITE_OPERATION_PRODUCES: dict[str, tuple[str, ...]] = {
    "cross_market.refresh_context": (
        "cross_market.overnight",
        "cross_market.relations",
        "cross_market.parity",
    ),
    "tw.refresh_watchlist_evidence": (
        "watchlist.ranking",
        "watchlist.radar",
    ),
    "us.refresh_company_profile": ("company.profile",),
    "us.refresh_corporate_actions": ("corporate.actions",),
}
COMPOSITE_OPERATIONS_WRITING_CACHE = frozenset(
    COMPOSITE_OPERATION_PRODUCES
)

# These tools remain useful backend conveniences or compatibility aliases, but
# they must not become a second public owner for the same capability.
INTERNAL_ONLY_OPERATIONS: dict[str, str] = {
    "jp.read_intraday_trend": "Cache-only JP context reader; acquisition is owned by jp.refresh_intraday_trend.",
    "kr.read_stock_intraday_trend": (
        "Cache-only KR reader; kr.refresh_stock_intraday_trend owns intraday fill. "
        "KR service owns compatibility until consumer migration and runtime parity are accepted."
    ),
    "kr.read_index_intraday_trend": (
        "Cache-only KR reader; kr.refresh_index_intraday_trend owns intraday fill. "
        "KR service owns compatibility until consumer migration and runtime parity are accepted."
    ),
    "tw.refresh_stock_evidence": (
        "Composite Taiwan stock convenience tool; public fill planning prefers "
        "the signed granular actions for each selected capability."
    ),
    "us.read_sec_fundamentals": (
        "Local-cache compatibility reader; us.refresh_sec_facts is the canonical "
        "public owner for fundamentals.financials."
    ),
    "us.read_intraday_trend": (
        "Cache-only compatibility reader; us.refresh_quote and "
        "us.refresh_intraday_bars are the canonical fill owners."
    ),
}


DERIVED_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "target.identity": (),
    "technical.structure": (
        "quote.snapshot",
        "daily.ohlcv",
        "intraday.bars",
    ),
    "technical.indicators": ("daily.ohlcv",),
    "technical.swings": ("daily.ohlcv",),
    "technical.fibonacci": ("technical.swings",),
    "technical.divergence": ("technical.indicators", "technical.swings"),
    "technical.breakout": ("technical.indicators", "daily.ohlcv"),
    "technical.volume_profile": ("daily.ohlcv",),
    "technical.anchored_vwap": ("technical.swings", "daily.ohlcv"),
    "technical.relative_strength": ("daily.ohlcv", "market.indices"),
    "technical.price_map": (
        "daily.ohlcv",
        "technical.indicators",
        "corporate.actions",
    ),
    "market.volume_state": ("intraday.bars", "market.breadth"),
    "watchlist.coverage": ("watchlist.ranking", "watchlist.radar"),
    "portfolio.summary": ("portfolio.holdings", "portfolio.valuation"),
    "portfolio.valuation": ("portfolio.holdings", "quote.snapshot"),
    "data.freshness": ("diagnostics.source_health",),
}


# US research is computed from completed Daily bars by the shared technical
# engine. The generic structure vocabulary also supports intraday/TW evidence;
# it must not expand a US daily technical fill into quote/intraday acquisition.
SCOPED_DERIVED_DEPENDENCIES: dict[tuple[str, str], tuple[str, ...]] = {
    ("us_stock", "technical.structure"): ("daily.ohlcv",),
}


def capability_dependencies(
    capability_id: str, *, scope_type: str = ""
) -> tuple[str, ...]:
    return SCOPED_DERIVED_DEPENDENCIES.get(
        (scope_type, capability_id), DERIVED_DEPENDENCIES.get(capability_id, ())
    )


def capability_dependency_closure(
    capability_ids: Iterable[str],
    *,
    scope_type: str = "",
) -> frozenset[str]:
    """Return requested capabilities plus their transitive registry dependencies."""

    resolved = {
        str(capability_id)
        for capability_id in capability_ids
        if str(capability_id)
    }
    pending = list(resolved)
    while pending:
        capability_id = pending.pop()
        for dependency in capability_dependencies(capability_id, scope_type=scope_type):
            if dependency not in resolved:
                resolved.add(dependency)
                pending.append(dependency)
    return frozenset(resolved)


def materialized_capability_dependencies(
    capability_ids: Iterable[str], *, scope_type: str
) -> frozenset[str]:
    """Resolve derived capabilities to their materialized upstream fill owners."""
    return frozenset(
        capability_id
        for capability_id in capability_dependency_closure(
            capability_ids, scope_type=scope_type
        )
        if capability_id not in DERIVED_DEPENDENCIES
        and (scope_type, capability_id) not in SCOPED_DERIVED_DEPENDENCIES
    )


@dataclass(frozen=True)
class CapabilityReadNode:
    """Read ownership, deliberately independent of acquisition operations."""

    node_id: str
    depends_on: tuple[str, ...] = ()
    timeout_seconds: float = 8.0


TW_STOCK_READ_NODES = {
    node.node_id: node for node in (
        CapabilityReadNode("identity"),
        CapabilityReadNode("calendar"),
        CapabilityReadNode("company_profile", ("identity",)),
        CapabilityReadNode("latest_daily", ("identity", "calendar")),
        CapabilityReadNode("institutional", ("identity",)),
        CapabilityReadNode("margin", ("identity",)),
        CapabilityReadNode("shareholding", ("identity",)),
        CapabilityReadNode("revenue", ("identity",)),
        CapabilityReadNode("financials", ("identity", "latest_daily", "revenue")),
        CapabilityReadNode("daily", ("identity",)),
        CapabilityReadNode("broker_branch", ("identity",)),
        CapabilityReadNode("technical_reports", ("daily", "latest_daily"), 12.0),
        CapabilityReadNode("overnight", ("identity",), 10.0),
        CapabilityReadNode("source_health", ("identity",), 10.0),
        CapabilityReadNode("selected_freshness", ("identity",)),
        CapabilityReadNode("disposition", ("identity",)),
        CapabilityReadNode("quote", ("latest_daily", "disposition")),
        CapabilityReadNode("events", ("identity",)),
        CapabilityReadNode("intraday", ("identity", "calendar"), 15.0),
        CapabilityReadNode("corporate_history", ("identity",)),
        CapabilityReadNode("technical_evidence", ("daily", "corporate_history", "calendar"), 15.0),
        CapabilityReadNode("price_map", ("identity",), 15.0),
    )
}

# Dependencies here describe executable read groups, including trust metadata.
# DERIVED_DEPENDENCIES remains the acquisition/quality dependency vocabulary;
# e.g. data.freshness does not require a full diagnostics.source_health scan.
TW_CAPABILITY_READ_NODES: dict[str, tuple[str, ...]] = {
    "target.identity": ("identity",),
    "data.freshness": ("selected_freshness",),
    "company.profile": ("company_profile",),
    "daily.ohlcv": ("daily",),
    "quote.snapshot": ("quote",),
    "quote.last_trade": ("quote",),
    "quote.order_book": ("quote",),
    "quote.auction": ("quote",),
    "quote.session_close": ("quote",),
    "quote.official_close": ("latest_daily",),
    "intraday.bars": ("intraday",),
    "chips.institutional": ("institutional",),
    "chips.margin": ("margin",),
    "ownership.distribution": ("shareholding",),
    "broker_branch.summary": ("broker_branch",),
    "fundamentals.revenue": ("revenue",),
    "fundamentals.financials": ("financials",),
    # Completed daily structure consumes no live quote/intraday input. Those
    # remain independently selectable; acquisition dependencies are broader.
    "technical.structure": ("technical_reports", "technical_evidence"),
    "technical.indicators": ("technical_evidence",),
    "technical.swings": ("technical_evidence",),
    "technical.fibonacci": ("technical_evidence",),
    "technical.divergence": ("technical_evidence",),
    "technical.breakout": ("technical_evidence",),
    "technical.volume_profile": ("technical_evidence",),
    "technical.anchored_vwap": ("technical_evidence",),
    "technical.relative_strength": ("technical_evidence",),
    "technical.price_map": ("price_map",),
    "events.upcoming": ("events",),
    "events.calendar": ("events",),
    "events.history": ("events",),
    "corporate.actions": ("events",),
    "regulation.disposition": ("events",),
    "regulation.trading_restrictions": ("events",),
    "cross_market.overnight": ("overnight",),
    "cross_market.relations": ("overnight",),
    "cross_market.parity": ("overnight",),
    "diagnostics.source_health": ("source_health",),
}


def compile_tw_stock_read_plan(capability_ids: Iterable[str]) -> tuple[str, ...]:
    """Deterministic dependency closure; each canonical read group runs once."""
    ordered: list[str] = []
    visiting: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in ordered:
            return
        if node_id in visiting:
            raise ValueError(f"Cyclic Taiwan read dependency: {node_id}")
        visiting.add(node_id)
        for dependency in TW_STOCK_READ_NODES[node_id].depends_on:
            visit(dependency)
        visiting.remove(node_id)
        ordered.append(node_id)

    for capability_id in sorted(set(capability_ids) | {"target.identity", "data.freshness"}):
        for node_id in TW_CAPABILITY_READ_NODES.get(capability_id, ()):
            visit(node_id)
    # Registry declaration order is the stable topological execution order.
    return tuple(node_id for node_id in TW_STOCK_READ_NODES if node_id in ordered)


SCHEDULER_OWNED_CAPABILITIES = frozenset(
    {
        "market.sectors",
        "market.institutional_flow",
        "market.margin_short",
        "market.chips",
        "screening.intraday",
        "screening.price_map",
        "market.hot_groups",
        "derivatives.positioning",
        "derivatives.structure",
        "watchlist.radar",
    }
)
PRIVATE_SCOPES = frozenset({"portfolio"})
KEY_REQUIRED_RESOLUTIONS = frozenset({("us_macro", "macro.observations")})
READER_FETCH_OVERRIDES: frozenset[tuple[str, str]] = frozenset()


PROVIDER_CONTRACTS_BY_SCOPE_CAPABILITY: dict[
    tuple[str, str], tuple[str, ...]
] = {
    ("us_stock", "ownership.insider_transactions"): ("sec_edgar_form4",),
    ("market", "market.breadth"): ("tw_full_market_breadth",),
    ("market", "market.chips"): ("tw_market_chips_rankings",),
    ("tw_futures", "derivatives.positioning"): (
        "tw_futures_institutional_oi_pcr",
        "tw_large_trader_positions",
    ),
    ("tw_futures", "derivatives.structure"): (
        "tw_options_chain_iv_greeks",
        "tw_futures_basis_term_structure",
    ),
    ("kr_stock", "quote.snapshot"): ("kr_intraday",),
    ("kr_stock", "intraday.bars"): ("kr_intraday",),
    ("kr_index", "quote.snapshot"): ("kr_intraday",),
    ("kr_index", "intraday.bars"): ("kr_intraday",),
    ("resource_asset", "quote.snapshot"): ("resource_quotes_ohlcv",),
    ("resource_asset", "intraday.bars"): ("resource_quotes_ohlcv",),
    ("resource_asset", "daily.ohlcv"): ("resource_quotes_ohlcv",),
    ("portfolio", "portfolio.summary"): ("portfolio_context",),
    ("portfolio", "portfolio.holdings"): ("portfolio_context",),
    ("portfolio", "portfolio.valuation"): ("portfolio_context",),
    ("us_macro", "macro.series"): ("fred_macro",),
    ("us_macro", "macro.observations"): ("fred_macro",),
    ("stock", "news.events"): ("news_events",),
    ("stock", "news.company_documents"): ("company_news_documents",),
    ("us_stock", "news.events"): ("news_events",),
    ("market", "news.events"): ("news_events",),
}


def canonical_operation_produces(
    legacy_operation_produces: Mapping[str, tuple[str, ...]],
) -> dict[str, tuple[str, ...]]:
    merged = {
        str(operation): tuple(str(item) for item in capabilities)
        for operation, capabilities in legacy_operation_produces.items()
    }
    for operation, capabilities in COMPOSITE_OPERATION_PRODUCES.items():
        existing = merged.get(operation)
        if existing is not None and existing != capabilities:
            raise ValueError(
                f"Conflicting produced-capability mapping for {operation}."
            )
        merged[operation] = capabilities
    return merged


def _applicable_scopes(spec: CapabilityLike) -> tuple[str, ...]:
    if "*" in spec.scopes:
        return PUBLIC_SCOPE_TYPES
    return tuple(dict.fromkeys(str(scope) for scope in spec.scopes))


def _implementation_status(
    *,
    spec: CapabilityLike,
    scope_type: str,
) -> str:
    if spec.deprecated:
        return "deprecated"
    if scope_type in PRIVATE_SCOPES:
        return "connected_private"
    if scope_type == "us_macro":
        return "connected_key_required_for_refresh"
    return "connected"


def _resolution_mode(
    *,
    spec: CapabilityLike,
    scope_type: str,
    operation: str | None,
) -> str:
    if spec.deprecated:
        return "deprecated"
    if scope_type in PRIVATE_SCOPES:
        return "private"
    if (scope_type, spec.capability_id) in KEY_REQUIRED_RESOLUTIONS:
        return "key_required"
    if operation:
        if (scope_type, spec.capability_id) in SCOPED_COMPOSITE_OPERATIONS:
            return "composite_fill"
        return "granular_fill"
    if (
        spec.refresh_strategy_for_scope(scope_type) == "reader_fetch"
        or (scope_type, spec.capability_id) in READER_FETCH_OVERRIDES
    ):
        return "reader_fetch"
    if (
        spec.capability_id in SCHEDULER_OWNED_CAPABILITIES
        or "scheduler_owned" in spec.side_effect_policy
    ):
        return "scheduler_cache"
    if spec.capability_id in DERIVED_DEPENDENCIES:
        return "derived"
    return "cache_only"


def _freshness_owner(resolution_mode: str) -> str:
    return {
        "reader_fetch": "bounded_reader",
        "granular_fill": "tool_operation",
        "composite_fill": "tool_operation",
        "scheduler_cache": "scheduler_and_cache",
        "cache_only": "local_cache_or_context_reader",
        "derived": "capability_projection_dependencies",
        "private": "trusted_local_store",
        "key_required": "provider_cache_and_key_gated_refresh",
        "provider_not_connected": "provider_contract",
        "not_applicable": "target_applicability",
        "deprecated": "replacement_capability",
    }[resolution_mode]


def _trust_requirement(resolution_mode: str) -> str:
    if resolution_mode == "private":
        return "server_trusted"
    if resolution_mode == "key_required":
        return "server_trusted_and_configured_key"
    if resolution_mode in {
        "reader_fetch",
        "granular_fill",
        "composite_fill",
    }:
        return "server_external_fetch_policy"
    return "read_only"


def _market_session_policy(
    *,
    spec: CapabilityLike,
    scope_type: str,
    resolution_mode: str,
) -> str:
    if spec.refresh_requires_market_open_for_scope(scope_type):
        return "market_open_required"
    if resolution_mode == "scheduler_cache":
        return "scheduler_owned_calendar_aware"
    if resolution_mode == "derived":
        return "dependency_defined"
    return "capability_defined"


def build_capability_resolution_registry(
    capability_specs: Iterable[CapabilityLike],
    *,
    operation_produced_capabilities: Mapping[str, tuple[str, ...]],
    operations_writing_cache: frozenset[str] | set[str],
) -> dict[tuple[str, str], CapabilityResolutionSpec]:
    canonical_produces = canonical_operation_produces(
        operation_produced_capabilities
    )
    registry: dict[tuple[str, str], CapabilityResolutionSpec] = {}

    for spec in capability_specs:
        for scope_type in _applicable_scopes(spec):
            if scope_type not in PUBLIC_SCOPE_TYPES:
                raise ValueError(
                    f"Capability {spec.capability_id} uses unknown scope {scope_type}."
                )
            operation = spec.fill_operation_for_scope(scope_type)
            if operation is None:
                operation = SCOPED_COMPOSITE_OPERATIONS.get(
                    (scope_type, spec.capability_id)
                )
            resolution_mode = _resolution_mode(
                spec=spec,
                scope_type=scope_type,
                operation=operation,
            )
            produces = (
                canonical_produces.get(operation, ()) if operation else ()
            )
            if operation and spec.capability_id not in produces:
                raise ValueError(
                    f"Operation {operation} does not produce {spec.capability_id}."
                )

            implementation_status = _implementation_status(
                spec=spec,
                scope_type=scope_type,
            )
            blocking_reason: str | None = None
            next_fill: str | None = None
            if resolution_mode == "key_required":
                blocking_reason = (
                    "External refresh requires configured provider credentials; "
                    "the existing local cache remains readable."
                )
                next_fill = (
                    "Configure the backend provider key and re-run the bounded "
                    "refresh action."
                )

            side_effect_policy = spec.side_effect_policy
            if operation in (
                set(operations_writing_cache)
                | set(COMPOSITE_OPERATIONS_WRITING_CACHE)
            ):
                side_effect_policy = "bounded_cache_write"

            entry = CapabilityResolutionSpec(
                scope_type=scope_type,
                capability_id=spec.capability_id,
                implementation_status=implementation_status,
                resolution_mode=resolution_mode,
                operation=operation,
                produces=produces,
                depends_on=capability_dependencies(
                    spec.capability_id,
                    scope_type=scope_type,
                ),
                provider_contract_ids=(
                    PROVIDER_CONTRACTS_BY_SCOPE_CAPABILITY.get(
                        (scope_type, spec.capability_id),
                        (),
                    )
                ),
                freshness_owner=_freshness_owner(resolution_mode),
                side_effect_policy=side_effect_policy,
                trust_requirement=_trust_requirement(resolution_mode),
                bounds=(("default_item_limit", int(spec.default_limit)),),
                market_session_policy=_market_session_policy(
                    spec=spec,
                    scope_type=scope_type,
                    resolution_mode=resolution_mode,
                ),
                backgroundable=resolution_mode
                in {"granular_fill", "composite_fill"},
                blocking_reason=blocking_reason,
                next_fill=next_fill,
                deprecated=bool(spec.deprecated),
                replacement_capabilities=tuple(
                    str(item) for item in spec.replacement_capabilities
                ),
            )
            if entry.implementation_status not in IMPLEMENTATION_STATUSES:
                raise ValueError(
                    f"Invalid implementation status: {entry.implementation_status}."
                )
            if entry.resolution_mode not in RESOLUTION_MODES:
                raise ValueError(
                    f"Invalid resolution mode: {entry.resolution_mode}."
                )
            if entry.key in registry:
                raise ValueError(
                    f"Duplicate capability resolution key: {entry.key}."
                )
            registry[entry.key] = entry

    return registry


def resolution_catalog(
    registry: Mapping[tuple[str, str], CapabilityResolutionSpec],
    *,
    scope_type: str | None = None,
    capability_id: str | None = None,
) -> list[dict[str, Any]]:
    return [
        entry.as_public_dict()
        for key, entry in sorted(registry.items())
        if scope_type is None or key[0] == scope_type
        if capability_id is None or key[1] == capability_id
    ]
