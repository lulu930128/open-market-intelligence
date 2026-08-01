from __future__ import annotations

import argparse
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db.migrations import get_database_revision, get_head_revision  # noqa: E402
from app.market.financial_contract import (  # noqa: E402
    build_database_financial_contract,
)


def _database_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def _decimal(value: str) -> Decimal:
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError(f"invalid decimal value: {value!r}") from exc


def _datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"invalid ISO-8601 datetime: {value!r}"
        ) from exc
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("datetime must include a timezone offset")
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Read and verify the backend-owned Taiwan financial contract. "
            "This command never refreshes providers or writes the database."
        )
    )
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--stock-id", required=True)
    parser.add_argument(
        "--mode",
        choices=("current_comparable", "as_reported_as_of"),
        default="current_comparable",
    )
    parser.add_argument("--as-of", type=_datetime)
    parser.add_argument("--price", type=_decimal)
    parser.add_argument("--price-as-of", type=_datetime)
    parser.add_argument("--price-basis", default="explicit_input")
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON audit output. Existing files are never overwritten.",
    )
    args = parser.parse_args()

    database_path = args.database.expanduser().resolve()
    if not database_path.is_file():
        parser.error(f"database does not exist: {database_path}")
    if (args.price is None) != (args.price_as_of is None):
        parser.error("--price and --price-as-of must be provided together")
    if args.mode == "as_reported_as_of" and args.as_of is None:
        parser.error("--as-of is required for as_reported_as_of mode")
    output_path = args.output.expanduser().resolve() if args.output else None
    if output_path is not None:
        if output_path.exists():
            parser.error(f"refusing to overwrite existing output: {output_path}")
        if not output_path.parent.is_dir():
            parser.error(f"output directory does not exist: {output_path.parent}")

    database_url = _database_url(database_path)
    current_revision = get_database_revision(database_url)
    head_revision = get_head_revision()
    if current_revision != head_revision:
        parser.error(
            f"database revision {current_revision!r} is not head {head_revision!r}"
        )

    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    session_factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )
    db = session_factory()
    try:
        contract = build_database_financial_contract(
            db,
            stock_id=args.stock_id,
            mode=args.mode,
            as_of=args.as_of,
            price=args.price,
            price_as_of=args.price_as_of,
            price_basis=args.price_basis,
        )
        payload = {
            "database": str(database_path),
            "database_revision": current_revision,
            "stock_id": args.stock_id,
            "mode": args.mode,
            "contract_version": contract.get("contract_version"),
            "normalized": contract.get("normalized"),
            "derived": contract.get("derived"),
            "valuation": contract.get("valuation"),
            "basis_assessment": contract.get("basis_assessment"),
            "quality": contract.get("quality"),
            "source_refs": contract.get("source_refs"),
        }
        rendered = json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=str,
        )
        if output_path is not None:
            output_path.write_text(rendered + "\n", encoding="utf-8")
        print(rendered)
    finally:
        db.close()
        engine.dispose()


if __name__ == "__main__":
    main()
