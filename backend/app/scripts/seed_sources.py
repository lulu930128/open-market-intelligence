import json

from app.db.models import SourceRegistry
from app.db.session import SessionLocal, init_db
from app.sources.defaults import (
    TPEX_DAILY_QUOTES_SOURCE_NAME,
    TWSE_DAILY_TRADING_SOURCE_NAME,
)


DEFAULT_SOURCES = [
    {
        "source_name": TWSE_DAILY_TRADING_SOURCE_NAME,
        "source_type": "api",
        "category": "market_data",
        "endpoint_url": "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL",
        "enabled": True,
        "fetch_interval_minutes": 1440,
        "priority": 10,
        "parser_type": "twse_daily_trading",
        "auth_type": "none",
        "reliability_level": "official",
    },
    {
        "source_name": "TWSE Listed Company Profile",
        "source_type": "api",
        "category": "company_profile",
        "endpoint_url": "https://mopsfin.twse.com.tw/opendata/t187ap03_L.csv",
        "enabled": True,
        "fetch_interval_minutes": 43200,
        "priority": 20,
        "parser_type": "twse_company_profile",
        "auth_type": "none",
        "reliability_level": "official",
    },
    {
        "source_name": "TWSE Institutional Trading T86",
        "source_type": "api",
        "category": "institutional_trade",
        "endpoint_url": (
            "https://www.twse.com.tw/rwd/zh/fund/T86"
            "?response=json"
            "&date={latest_market_trade_date_yyyyMMdd}"
            "&selectType=ALL"
        ),
        "enabled": True,
        "fetch_interval_minutes": 1440,
        "priority": 30,
        "parser_type": "twse_institutional_trade",
        "auth_type": "none",
        "reliability_level": "official",
    },
    {
        "source_name": "TWSE Margin Trading MI_MARGN",
        "source_type": "api",
        "category": "margin_trading",
        "endpoint_url": (
            "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"
            "?response=json"
            "&date={latest_market_trade_date_yyyyMMdd}"
            "&selectType=STOCK"
        ),
        "enabled": True,
        "fetch_interval_minutes": 1440,
        "priority": 35,
        "parser_type": "twse_margin_trading",
        "auth_type": "none",
        "reliability_level": "official",
    },
    {
        "source_name": TPEX_DAILY_QUOTES_SOURCE_NAME,
        "source_type": "api",
        "category": "market_data",
        "endpoint_url": (
            "https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes"
            "?date={latest_market_trade_date_roc_yyy_mm_dd}"
            "&response=json"
        ),
        "enabled": True,
        "fetch_interval_minutes": 1440,
        "priority": 40,
        "parser_type": "tpex_daily_quotes",
        "auth_type": "none",
        "reliability_level": "official",
    },
    {
        "source_name": "TPEx Domestic Company Profile",
        "source_type": "api",
        "category": "company_profile",
        "endpoint_url": (
            "https://www.tpex.org.tw/www/zh-tw/company/otcSearch"
            "?type=stkType"
            "&stkType=%20"
            "&response=json"
        ),
        "enabled": True,
        "fetch_interval_minutes": 43200,
        "priority": 45,
        "parser_type": "tpex_company_profile",
        "auth_type": "none",
        "reliability_level": "official",
    },
    {
        "source_name": "TPEx Foreign Company Profile",
        "source_type": "api",
        "category": "company_profile",
        "endpoint_url": (
            "https://www.tpex.org.tw/www/zh-tw/company/otcSearch"
            "?type=stkType"
            "&stkType=RR"
            "&response=json"
        ),
        "enabled": True,
        "fetch_interval_minutes": 43200,
        "priority": 46,
        "parser_type": "tpex_company_profile",
        "auth_type": "none",
        "reliability_level": "official",
    },
    {
        "source_name": "TPEx Institutional Trading",
        "source_type": "api_bundle",
        "category": "institutional_trade",
        "endpoint_url": json.dumps(
            {
                "foreign_buy": (
                    "https://www.tpex.org.tw/www/zh-tw/insti/qfiiStat"
                    "?date={latest_market_trade_date_roc_yyy_mm_dd}"
                    "&type=Daily"
                    "&searchType=buy"
                    "&response=json"
                ),
                "foreign_sell": (
                    "https://www.tpex.org.tw/www/zh-tw/insti/qfiiStat"
                    "?date={latest_market_trade_date_roc_yyy_mm_dd}"
                    "&type=Daily"
                    "&searchType=sell"
                    "&response=json"
                ),
                "investment_trust_buy": (
                    "https://www.tpex.org.tw/www/zh-tw/insti/sitcStat"
                    "?date={latest_market_trade_date_roc_yyy_mm_dd}"
                    "&type=Daily"
                    "&searchType=buy"
                    "&response=json"
                ),
                "investment_trust_sell": (
                    "https://www.tpex.org.tw/www/zh-tw/insti/sitcStat"
                    "?date={latest_market_trade_date_roc_yyy_mm_dd}"
                    "&type=Daily"
                    "&searchType=sell"
                    "&response=json"
                ),
                "dealer_buy": (
                    "https://www.tpex.org.tw/www/zh-tw/insti/dealerStat"
                    "?date={latest_market_trade_date_roc_yyy_mm_dd}"
                    "&type=Daily"
                    "&stype=buy"
                    "&response=json"
                ),
                "dealer_sell": (
                    "https://www.tpex.org.tw/www/zh-tw/insti/dealerStat"
                    "?date={latest_market_trade_date_roc_yyy_mm_dd}"
                    "&type=Daily"
                    "&stype=sell"
                    "&response=json"
                ),
            },
            ensure_ascii=False,
        ),
        "enabled": True,
        "fetch_interval_minutes": 1440,
        "priority": 50,
        "parser_type": "tpex_institutional_trade",
        "auth_type": "none",
        "reliability_level": "official",
    },
    {
        "source_name": "TPEx Margin Trading Balance",
        "source_type": "api",
        "category": "margin_trading",
        "endpoint_url": (
            "https://www.tpex.org.tw/www/zh-tw/margin/balance"
            "?date={latest_market_trade_date_roc_yyy_mm_dd}"
            "&response=json"
        ),
        "enabled": True,
        "fetch_interval_minutes": 1440,
        "priority": 55,
        "parser_type": "tpex_margin_trading",
        "auth_type": "none",
        "reliability_level": "official",
    },
    {
        "source_name": "TDCC Shareholding Distribution",
        "source_type": "api",
        "category": "shareholding_distribution",
        "endpoint_url": "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5",
        "enabled": True,
        "fetch_interval_minutes": 10080,
        "priority": 60,
        "parser_type": "tdcc_shareholding_distribution",
        "auth_type": "none",
        "reliability_level": "official",
    },
    {
        "source_name": "TWSE Monthly Revenue",
        "source_type": "api",
        "category": "monthly_revenue",
        "endpoint_url": "https://openapi.twse.com.tw/v1/opendata/t187ap05_L",
        "enabled": True,
        "fetch_interval_minutes": 43200,
        "priority": 65,
        "parser_type": "monthly_revenue",
        "auth_type": "none",
        "reliability_level": "official",
    },
    {
        "source_name": "TPEx Monthly Revenue",
        "source_type": "api",
        "category": "monthly_revenue",
        "endpoint_url": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O",
        "enabled": True,
        "fetch_interval_minutes": 43200,
        "priority": 66,
        "parser_type": "monthly_revenue",
        "auth_type": "none",
        "reliability_level": "official",
    },
    {
        "source_name": "TWSE Financial Metrics",
        "source_type": "api_bundle",
        "category": "financial_metrics",
        "endpoint_url": json.dumps(
            {
                "income_basi": "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_basi",
                "income_bd": "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_bd",
                "income_ci": "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_ci",
                "income_fh": "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_fh",
                "income_ins": "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_ins",
                "income_mim": "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_mim",
                "balance_basi": "https://openapi.twse.com.tw/v1/opendata/t187ap07_L_basi",
                "balance_bd": "https://openapi.twse.com.tw/v1/opendata/t187ap07_L_bd",
                "balance_ci": "https://openapi.twse.com.tw/v1/opendata/t187ap07_L_ci",
                "balance_fh": "https://openapi.twse.com.tw/v1/opendata/t187ap07_L_fh",
                "balance_ins": "https://openapi.twse.com.tw/v1/opendata/t187ap07_L_ins",
                "balance_mim": "https://openapi.twse.com.tw/v1/opendata/t187ap07_L_mim",
            },
            ensure_ascii=False,
        ),
        "enabled": True,
        "fetch_interval_minutes": 43200,
        "priority": 70,
        "parser_type": "financial_metrics",
        "auth_type": "none",
        "reliability_level": "official",
    },
    {
        "source_name": "TPEx Financial Metrics",
        "source_type": "api_bundle",
        "category": "financial_metrics",
        "endpoint_url": json.dumps(
            {
                "income_basi": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap06_O_basi",
                "income_bd": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap06_O_bd",
                "income_ci": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap06_O_ci",
                "income_fh": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap06_O_fh",
                "income_ins": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap06_O_ins",
                "income_mim": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap06_O_mim",
                "balance_basi": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap07_O_basi",
                "balance_bd": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap07_O_bd",
                "balance_ci": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap07_O_ci",
                "balance_fh": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap07_O_fh",
                "balance_ins": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap07_O_ins",
                "balance_mim": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap07_O_mim",
            },
            ensure_ascii=False,
        ),
        "enabled": True,
        "fetch_interval_minutes": 43200,
        "priority": 71,
        "parser_type": "financial_metrics",
        "auth_type": "none",
        "reliability_level": "official",
    },
    {
        "source_name": "GDELT AI Semiconductor Events",
        "source_type": "api",
        "category": "international_event",
        "endpoint_url": (
            "https://api.gdeltproject.org/api/v2/doc/doc"
            "?query=semiconductor%20OR%20%22AI%20server%22%20OR%20NVIDIA"
            "&mode=ArtList"
            "&format=json"
            "&timespan=24h"
        ),
        "enabled": False,
        "fetch_interval_minutes": 180,
        "priority": 50,
        "parser_type": "gdelt_doc",
        "auth_type": "none",
        "reliability_level": "open_data",
    },
]


def upsert_source(payload: dict) -> tuple[str, SourceRegistry]:
    db = SessionLocal()

    try:
        source = (
            db.query(SourceRegistry)
            .filter(SourceRegistry.source_name == payload["source_name"])
            .first()
        )

        if source is None:
            source = SourceRegistry(**payload)
            db.add(source)
            db.commit()
            db.refresh(source)
            return "created", source

        for key, value in payload.items():
            setattr(source, key, value)

        db.commit()
        db.refresh(source)
        return "updated", source

    finally:
        db.close()


def main() -> None:
    init_db()

    print("Seeding default sources...")

    for payload in DEFAULT_SOURCES:
        action, source = upsert_source(payload)
        print(f"[{action}] id={source.id} name={source.source_name}")

    print("Seed completed.")


if __name__ == "__main__":
    main()
