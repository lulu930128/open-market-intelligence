from __future__ import annotations

from collections import OrderedDict
from datetime import date

from sqlalchemy.orm import Session

from app.db.models import (
    MacroSeriesObservation,
    USCompanyProfile,
    USCorporateAction,
    USSecCompanyFact,
    USShortVolumeDaily,
    utc_now,
)
from app.us_market.sources import (
    MacroSeriesObservationRecord,
    USCompanyProfileRecord,
    USCorporateActionRecord,
    USSecFactRecord,
    USShortVolumeRecord,
    normalize_us_symbol,
)


SEC_FUNDAMENTAL_FORMS = ("10-K", "10-Q", "20-F", "40-F")
SEC_DOMESTIC_FILING_FORMS = ("10-K", "10-K/A", "10-Q", "10-Q/A")

def upsert_us_sec_fact_records(
    db: Session,
    records: list[USSecFactRecord],
) -> dict:
    inserted_count = 0
    updated_count = 0

    for record in records:
        existing = (
            db.query(USSecCompanyFact)
            .filter(USSecCompanyFact.fact_key == record.fact_key)
            .first()
        )

        if existing is None:
            db.add(
                USSecCompanyFact(
                    fact_key=record.fact_key,
                    cik=record.cik,
                    symbol=record.symbol,
                    entity_name=record.entity_name,
                    taxonomy=record.taxonomy,
                    tag=record.tag,
                    label=record.label,
                    description=record.description,
                    unit=record.unit,
                    fiscal_year=record.fiscal_year,
                    fiscal_period=record.fiscal_period,
                    form=record.form,
                    filed_date=record.filed_date,
                    period_start_date=record.period_start_date,
                    period_end_date=record.period_end_date,
                    accession_number=record.accession_number,
                    frame=record.frame,
                    value_numeric=record.value_numeric,
                    value_text=record.value_text,
                    source_url=record.source_url,
                    fetched_at=utc_now(),
                )
            )
            inserted_count += 1
            continue

        existing.symbol = record.symbol or existing.symbol
        existing.entity_name = record.entity_name or existing.entity_name
        existing.label = record.label
        existing.description = record.description
        existing.value_numeric = record.value_numeric
        existing.value_text = record.value_text
        existing.source_url = record.source_url
        existing.fetched_at = utc_now()
        existing.updated_at = utc_now()
        updated_count += 1

    db.commit()

    return {
        "inserted_count": inserted_count,
        "updated_count": updated_count,
    }


def list_us_sec_company_facts(
    db: Session,
    *,
    symbol: str,
    taxonomy: str | None = None,
    tag: str | None = None,
    form: str | None = None,
    fiscal_year: int | None = None,
    limit: int = 500,
    offset: int = 0,
) -> list[USSecCompanyFact]:
    normalized_symbol = normalize_us_symbol(symbol)
    query = db.query(USSecCompanyFact).filter(USSecCompanyFact.symbol == normalized_symbol)

    if taxonomy is not None:
        query = query.filter(USSecCompanyFact.taxonomy == taxonomy)

    if tag is not None:
        query = query.filter(USSecCompanyFact.tag == tag)

    if form is not None:
        query = query.filter(USSecCompanyFact.form == form)

    if fiscal_year is not None:
        query = query.filter(USSecCompanyFact.fiscal_year == fiscal_year)

    return (
        query.order_by(
            USSecCompanyFact.period_end_date.desc(),
            USSecCompanyFact.filed_date.desc(),
            USSecCompanyFact.id.desc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )


def latest_us_sec_filing_fact(
    db: Session,
    *,
    symbol: str,
) -> USSecCompanyFact | None:
    normalized_symbol = normalize_us_symbol(symbol)
    return (
        db.query(USSecCompanyFact)
        .filter(USSecCompanyFact.symbol == normalized_symbol)
        .filter(USSecCompanyFact.form.in_(SEC_DOMESTIC_FILING_FORMS))
        .filter(USSecCompanyFact.accession_number.isnot(None))
        .order_by(
            USSecCompanyFact.filed_date.desc(),
            USSecCompanyFact.accession_number.desc(),
            USSecCompanyFact.fetched_at.desc(),
            USSecCompanyFact.id.desc(),
        )
        .first()
    )

def _latest_us_sec_fact_for_tag(
    db: Session,
    *,
    symbol: str,
    tag: str,
) -> USSecCompanyFact | None:
    base_query = (
        db.query(USSecCompanyFact)
        .filter(USSecCompanyFact.symbol == symbol)
        .filter(USSecCompanyFact.tag == tag)
        .filter(USSecCompanyFact.value_numeric.isnot(None))
    )
    ordering = (
        USSecCompanyFact.period_end_date.desc(),
        USSecCompanyFact.filed_date.desc(),
        USSecCompanyFact.id.desc(),
    )
    preferred = (
        base_query.filter(USSecCompanyFact.form.in_(SEC_FUNDAMENTAL_FORMS))
        .order_by(*ordering)
        .first()
    )
    if preferred is not None:
        return preferred

    return base_query.order_by(*ordering).first()


def _latest_us_sec_fact_for_tags(
    db: Session,
    *,
    symbol: str,
    tags: tuple[str, ...],
) -> USSecCompanyFact | None:
    candidates = [
        fact
        for tag in tags
        if (fact := _latest_us_sec_fact_for_tag(db, symbol=symbol, tag=tag)) is not None
    ]
    if not candidates:
        return None

    tag_priority = {tag: index for index, tag in enumerate(tags)}

    return max(
        candidates,
        key=lambda fact: (
            fact.period_end_date or date.min,
            fact.filed_date or date.min,
            -tag_priority.get(fact.tag, len(tags)),
            fact.id,
        ),
    )


def _us_sec_metric_to_dict(metric: str, fact: USSecCompanyFact) -> dict:
    return {
        "metric": metric,
        "tag": fact.tag,
        "label": fact.label,
        "unit": fact.unit,
        "value_numeric": fact.value_numeric,
        "value_text": fact.value_text,
        "fiscal_year": fact.fiscal_year,
        "fiscal_period": fact.fiscal_period,
        "form": fact.form,
        "filed_date": fact.filed_date,
        "period_start_date": fact.period_start_date,
        "period_end_date": fact.period_end_date,
        "accession_number": fact.accession_number,
        "source_url": fact.source_url,
    }


def upsert_us_company_profile_records(
    db: Session,
    records: list[USCompanyProfileRecord],
) -> dict:
    inserted_count = 0
    updated_count = 0

    for record in records:
        existing = (
            db.query(USCompanyProfile)
            .filter(USCompanyProfile.provider == record.provider)
            .filter(USCompanyProfile.symbol == record.symbol)
            .first()
        )

        if existing is None:
            db.add(
                USCompanyProfile(
                    provider=record.provider,
                    symbol=record.symbol,
                    company_name=record.company_name,
                    description=record.description,
                    exchange=record.exchange,
                    sector=record.sector,
                    industry=record.industry,
                    country=record.country,
                    currency=record.currency,
                    market_cap=record.market_cap,
                    ebitda=record.ebitda,
                    pe_ratio=record.pe_ratio,
                    peg_ratio=record.peg_ratio,
                    beta=record.beta,
                    dividend_yield=record.dividend_yield,
                    eps=record.eps,
                    revenue_ttm=record.revenue_ttm,
                    profit_margin=record.profit_margin,
                    fiscal_year_end=record.fiscal_year_end,
                    latest_quarter=record.latest_quarter,
                    source_url=record.source_url,
                    raw_payload_hash=record.raw_payload_hash,
                    fetched_at=utc_now(),
                )
            )
            inserted_count += 1
            continue

        existing.company_name = record.company_name
        existing.description = record.description
        existing.exchange = record.exchange
        existing.sector = record.sector
        existing.industry = record.industry
        existing.country = record.country
        existing.currency = record.currency
        existing.market_cap = record.market_cap
        existing.ebitda = record.ebitda
        existing.pe_ratio = record.pe_ratio
        existing.peg_ratio = record.peg_ratio
        existing.beta = record.beta
        existing.dividend_yield = record.dividend_yield
        existing.eps = record.eps
        existing.revenue_ttm = record.revenue_ttm
        existing.profit_margin = record.profit_margin
        existing.fiscal_year_end = record.fiscal_year_end
        existing.latest_quarter = record.latest_quarter
        existing.source_url = record.source_url
        existing.raw_payload_hash = record.raw_payload_hash
        existing.fetched_at = utc_now()
        existing.updated_at = utc_now()
        updated_count += 1

    db.commit()

    return {
        "inserted_count": inserted_count,
        "updated_count": updated_count,
    }


def get_us_company_profile(
    db: Session,
    *,
    symbol: str,
    provider: str | None = None,
) -> USCompanyProfile | None:
    normalized_symbol = normalize_us_symbol(symbol)
    query = db.query(USCompanyProfile).filter(USCompanyProfile.symbol == normalized_symbol)

    if provider is not None:
        query = query.filter(USCompanyProfile.provider == provider)

    return query.order_by(USCompanyProfile.fetched_at.desc(), USCompanyProfile.id.desc()).first()


def list_us_company_profiles(
    db: Session,
    *,
    sector: str | None = None,
    industry: str | None = None,
    provider: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[USCompanyProfile]:
    query = db.query(USCompanyProfile)

    if sector is not None:
        query = query.filter(USCompanyProfile.sector == sector)

    if industry is not None:
        query = query.filter(USCompanyProfile.industry == industry)

    if provider is not None:
        query = query.filter(USCompanyProfile.provider == provider)

    return (
        query.order_by(USCompanyProfile.symbol.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def upsert_us_corporate_action_records(
    db: Session,
    records: list[USCorporateActionRecord],
) -> dict:
    inserted_count = 0
    updated_count = 0

    for record in records:
        existing = (
            db.query(USCorporateAction)
            .filter(USCorporateAction.provider == record.provider)
            .filter(USCorporateAction.symbol == record.symbol)
            .filter(USCorporateAction.action_type == record.action_type)
            .filter(USCorporateAction.event_date == record.event_date)
            .first()
        )

        if existing is None:
            db.add(
                USCorporateAction(
                    provider=record.provider,
                    symbol=record.symbol,
                    action_type=record.action_type,
                    event_date=record.event_date,
                    declaration_date=record.declaration_date,
                    record_date=record.record_date,
                    payment_date=record.payment_date,
                    amount=record.amount,
                    split_from=record.split_from,
                    split_to=record.split_to,
                    split_ratio=record.split_ratio,
                    source_url=record.source_url,
                    raw_payload_hash=record.raw_payload_hash,
                    fetched_at=utc_now(),
                )
            )
            inserted_count += 1
            continue

        existing.declaration_date = record.declaration_date
        existing.record_date = record.record_date
        existing.payment_date = record.payment_date
        existing.amount = record.amount
        existing.split_from = record.split_from
        existing.split_to = record.split_to
        existing.split_ratio = record.split_ratio
        existing.source_url = record.source_url
        existing.raw_payload_hash = record.raw_payload_hash
        existing.fetched_at = utc_now()
        existing.updated_at = utc_now()
        updated_count += 1

    db.commit()

    return {
        "inserted_count": inserted_count,
        "updated_count": updated_count,
    }


def list_us_corporate_actions(
    db: Session,
    *,
    symbol: str,
    action_type: str | None = None,
    provider: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = 500,
    offset: int = 0,
) -> list[USCorporateAction]:
    normalized_symbol = normalize_us_symbol(symbol)
    query = db.query(USCorporateAction).filter(USCorporateAction.symbol == normalized_symbol)

    if action_type is not None:
        query = query.filter(USCorporateAction.action_type == action_type)

    if provider is not None:
        query = query.filter(USCorporateAction.provider == provider)

    if from_date is not None:
        query = query.filter(USCorporateAction.event_date >= from_date)

    if to_date is not None:
        query = query.filter(USCorporateAction.event_date <= to_date)

    return (
        query.order_by(USCorporateAction.event_date.desc(), USCorporateAction.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def upsert_us_short_volume_records(
    db: Session,
    records: list[USShortVolumeRecord],
) -> dict:
    inserted_count = 0
    updated_count = 0
    deduped_records = list(
        OrderedDict(
            (
                (record.provider, record.symbol, record.trade_date, record.market_center),
                record,
            )
            for record in records
        ).values()
    )

    for record in deduped_records:
        existing = (
            db.query(USShortVolumeDaily)
            .filter(USShortVolumeDaily.provider == record.provider)
            .filter(USShortVolumeDaily.symbol == record.symbol)
            .filter(USShortVolumeDaily.trade_date == record.trade_date)
            .filter(USShortVolumeDaily.market_center == record.market_center)
            .first()
        )

        if existing is None:
            db.add(
                USShortVolumeDaily(
                    provider=record.provider,
                    symbol=record.symbol,
                    trade_date=record.trade_date,
                    market_center=record.market_center,
                    short_volume=record.short_volume,
                    short_exempt_volume=record.short_exempt_volume,
                    total_volume=record.total_volume,
                    short_ratio=record.short_ratio,
                    source_url=record.source_url,
                    raw_payload_hash=record.raw_payload_hash,
                    fetched_at=utc_now(),
                )
            )
            inserted_count += 1
            continue

        existing.short_volume = record.short_volume
        existing.short_exempt_volume = record.short_exempt_volume
        existing.total_volume = record.total_volume
        existing.short_ratio = record.short_ratio
        existing.source_url = record.source_url
        existing.raw_payload_hash = record.raw_payload_hash
        existing.fetched_at = utc_now()
        existing.updated_at = utc_now()
        updated_count += 1

    db.commit()

    return {
        "inserted_count": inserted_count,
        "updated_count": updated_count,
    }


def list_us_short_volumes(
    db: Session,
    *,
    symbol: str,
    provider: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = 500,
    offset: int = 0,
) -> list[USShortVolumeDaily]:
    normalized_symbol = normalize_us_symbol(symbol)
    query = db.query(USShortVolumeDaily).filter(USShortVolumeDaily.symbol == normalized_symbol)

    if provider is not None:
        query = query.filter(USShortVolumeDaily.provider == provider)

    if from_date is not None:
        query = query.filter(USShortVolumeDaily.trade_date >= from_date)

    if to_date is not None:
        query = query.filter(USShortVolumeDaily.trade_date <= to_date)

    return (
        query.order_by(USShortVolumeDaily.trade_date.desc(), USShortVolumeDaily.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def upsert_macro_series_observation_records(
    db: Session,
    records: list[MacroSeriesObservationRecord],
) -> dict:
    inserted_count = 0
    updated_count = 0

    for record in records:
        existing = (
            db.query(MacroSeriesObservation)
            .filter(MacroSeriesObservation.provider == record.provider)
            .filter(MacroSeriesObservation.series_id == record.series_id)
            .filter(MacroSeriesObservation.observation_date == record.observation_date)
            .first()
        )

        if existing is None:
            db.add(
                MacroSeriesObservation(
                    provider=record.provider,
                    series_id=record.series_id,
                    series_name=record.series_name,
                    observation_date=record.observation_date,
                    value=record.value,
                    unit=record.unit,
                    frequency=record.frequency,
                    source_url=record.source_url,
                    raw_payload_hash=record.raw_payload_hash,
                    fetched_at=utc_now(),
                )
            )
            inserted_count += 1
            continue

        existing.series_name = record.series_name or existing.series_name
        existing.value = record.value
        existing.unit = record.unit or existing.unit
        existing.frequency = record.frequency or existing.frequency
        existing.source_url = record.source_url
        existing.raw_payload_hash = record.raw_payload_hash
        existing.fetched_at = utc_now()
        existing.updated_at = utc_now()
        updated_count += 1

    db.commit()

    return {
        "inserted_count": inserted_count,
        "updated_count": updated_count,
    }


def list_macro_series_observations(
    db: Session,
    *,
    series_id: str,
    provider: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = 500,
    offset: int = 0,
) -> list[MacroSeriesObservation]:
    normalized_series_id = series_id.strip().upper()
    query = db.query(MacroSeriesObservation).filter(
        MacroSeriesObservation.series_id == normalized_series_id
    )

    if provider is not None:
        query = query.filter(MacroSeriesObservation.provider == provider)

    if from_date is not None:
        query = query.filter(MacroSeriesObservation.observation_date >= from_date)

    if to_date is not None:
        query = query.filter(MacroSeriesObservation.observation_date <= to_date)

    return (
        query.order_by(
            MacroSeriesObservation.observation_date.desc(),
            MacroSeriesObservation.id.desc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )
