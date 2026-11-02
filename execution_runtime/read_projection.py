"""Typed, ephemeral broker read projections; no reducer, cache, ledger or IO."""
from dataclasses import dataclass

from .contracts import BrokerKey, QueryBatch, SourceRead, decimal


@dataclass(frozen=True)
class BrokerFact:
    source: str
    source_at: str
    received_at: str
    current_read: bool
    kind: str
    quantity_shares: int | None
    remaining_shares: int | None
    cumulative_shares: int | None
    price: str | None
    broker_status: str | None


@dataclass(frozen=True)
class BrokerFill:
    broker_key: BrokerKey
    fill_id: str
    execution_id: str | None
    ownership: str
    space_id: str
    symbol: str
    action: str
    condition: str
    lot: str
    quantity_shares: int | None
    price: str | None
    quality: str
    evidence: tuple[BrokerFact, ...]


@dataclass(frozen=True)
class BrokerOrder:
    broker_key: BrokerKey
    execution_id: str | None
    ownership: str
    space_id: str
    symbol: str | None
    action: str | None
    condition: str | None
    lot: str | None
    quantity_shares: int | None
    price: str | None
    broker_status: str | None
    execution_state: str | None
    known_filled_shares: int | None
    fill_history_complete: bool
    quality: str
    facts: tuple[BrokerFact, ...]


@dataclass(frozen=True)
class CashHolding:
    symbol: str
    reported_total_shares: int
    odd_shares: int
    holding_upper_bound_shares: int
    sellable_shares: int | None = None
    quality: str = "PARTIAL"


@dataclass(frozen=True)
class InventoryPart:
    quality: str
    source: str | None
    source_as_of: str | None
    queried_at: str | None
    received_at: str | None
    items: tuple[CashHolding, ...] | None
    complete: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class BrokerInventory:
    cash: InventoryPart
    margin: InventoryPart
    short_selling: InventoryPart


@dataclass(frozen=True)
class BrokerReadback:
    contract: str
    trade_date: str
    session_generation: int
    queried_at: str
    received_at: str
    quality: str
    sources: tuple[SourceRead, ...]
    reviews: tuple[dict, ...]
    broker_orders: tuple[BrokerOrder, ...]
    fills: tuple[BrokerFill, ...]
    fill_history_complete: bool
    inventory: BrokerInventory
    unparsed_reports: tuple[dict, ...]
    invalid_trade_count: int


def inventory_projection(value, *, error=None):
    unknown = InventoryPart("UNKNOWN", None, None, None, None, None, False,
                            ("SDK_FIELD_SEMANTICS_UNVERIFIED",))
    if value is None:
        cash = InventoryPart("UNKNOWN", "Account.InventorySum(B)", None, None, None, None,
                             False, (error or "CASH_INVENTORY_UNAVAILABLE",))
    else:
        reasons = ("SOURCE_AS_OF_UNKNOWN", "SELLABLE_SHARES_UNKNOWN", "REPORT_COMPLETENESS_UNKNOWN")
        if value.get("report_error"):
            reasons += (value["report_error"],)
        cash = InventoryPart("PARTIAL", value["source"], value["source_as_of"], value["queried_at"],
            value["received_at"], tuple(CashHolding(**row) for row in value["reported"]), False, reasons)
    return BrokerInventory(cash, unknown, unknown)


def project(*, trade_date, generation, queried_at, received_at, batch: QueryBatch,
            observations, managed, reviews, inventory, inventory_error=None):
    """Exact broker keys only. SDK status/cumulative never manufacture a Deal.

    `observations` includes existing durable callback/report evidence and this
    read's normalized SDK rows. There is no persistence or economic matching.
    """
    grouped = {}
    for item, stamp, current in observations:
        if not item.key.order_id:
            continue
        grouped.setdefault(item.key, {})[item.event_id] = (item, stamp, current)
    orders, fills = [], []
    for key, values in grouped.items():
        records = sorted(values.values(), key=lambda row: (row[0].source_time, row[0].kind == "DEAL"))
        owned = managed.get(key)
        unit = owned["shares_per_unit"] if owned else (1000 if records[0][0].lot == "Common" else 1)
        space = owned["space_id"] if owned else "USER_SPACE"
        execution_id = owned["execution_id"] if owned else None
        ownership = "MANAGED" if owned else "EXTERNAL"
        identities = {(o.symbol, o.action, o.condition, o.lot) for o, _, _ in records}
        identity_conflict = len(identities) != 1 or bool(owned and identities != {owned["identity"]})

        def fact(row):
            item, stamp, current = row
            raw = item.source_time
            source_at = f"{item.key.trade_date}T{raw[:2]}:{raw[2:4]}:{raw[4:]}+08:00"
            return BrokerFact(item.source, source_at, stamp, current, item.kind,
                item.quantity * unit if item.quantity is not None else None,
                item.remaining * unit if item.remaining is not None else None,
                item.cumulative * unit if item.cumulative is not None else None,
                item.price, item.broker_status)

        deals = {}
        for row in records:
            item = row[0]
            if item.kind == "DEAL":
                deals.setdefault(item.seqno, []).append(row)
        known_total = 0
        conflict = identity_conflict
        for fill_id, rows in deals.items():
            first = rows[0][0]
            same = not identity_conflict and first.quantity is not None and first.quantity > 0 and decimal(first.price) > 0 and all(
                       (o.quantity, decimal(o.price), o.source_time, o.symbol, o.action, o.condition, o.lot) ==
                       (first.quantity, decimal(first.price), first.source_time, first.symbol, first.action,
                        first.condition, first.lot) for o, _, _ in rows)
            conflict |= not same
            if same:
                known_total += first.quantity * unit
            fills.append(BrokerFill(key, fill_id, execution_id, ownership, space, first.symbol, first.action,
                first.condition, first.lot, first.quantity * unit if same else None,
                first.price if same else None, "KNOWN" if same else "UNKNOWN", tuple(fact(row) for row in rows)))
        snapshots = [o for o, _, _ in records if o.kind == "SNAPSHOT"]
        order_facts = [o for o, _, _ in records if o.kind in {"ACCEPTED", "PENDING", "REJECTED", "SNAPSHOT"}]
        latest = (order_facts or [records[-1][0]])[-1]
        last = records[-1][0]
        # A Deal-only observation can identify an order, but not its total size.
        quantity = latest.quantity * unit if order_facts and not conflict else None
        orders.append(BrokerOrder(key, execution_id, ownership, space, latest.symbol, latest.action,
            latest.condition, latest.lot, quantity, latest.price,
            snapshots[-1].broker_status if snapshots else last.kind,
            owned["state"] if owned else None, None if conflict else known_total,
            batch.fill_history_complete, "UNKNOWN" if conflict else "PARTIAL", tuple(fact(row) for row in records)))
    for key in sorted(batch.cached_keys - grouped.keys(), key=lambda k: (k.trade_date, k.order_id)):
        # The cache can expose an ID without a dated/status-bearing snapshot.
        # Keep that fact visible, without inventing event time, size or fills.
        owned = managed.get(key)
        orders.append(BrokerOrder(key, owned["execution_id"] if owned else None,
            "MANAGED" if owned else "EXTERNAL", owned["space_id"] if owned else "USER_SPACE",
            None, None, None, None, None, None, None, owned["state"] if owned else None,
            None, False, "UNKNOWN", ()))
    inv = inventory_projection(inventory, error=inventory_error)
    quality = "PARTIAL" if inventory is not None or any(s.status != "UNAVAILABLE" for s in batch.sources) else "UNKNOWN"
    return BrokerReadback("omi.execution-desk.v1", trade_date, generation, queried_at, received_at,
        quality, batch.sources, tuple(reviews), tuple(orders), tuple(fills), batch.fill_history_complete,
        inv, tuple({"source": d.source, "row_index": d.row_index, "reason": d.reason,
                    "trade_date": d.trade_date, "fields": d.fields} for d in batch.diagnostics),
        batch.invalid_trade_count)
