from app.db.models import SourceRegistry
from app.db.session import SessionLocal, init_db


DEFAULT_SOURCES = [
    {
        "source_name": "TWSE OpenAPI Daily Trading",
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