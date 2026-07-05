from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import re
import sys

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db.models import KRStockMaster, KRWatchlistGroup, KRWatchlistItem, utc_now  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.kr_market.sources import local_code_from_symbol, normalize_kr_symbol  # noqa: E402


ROOT_GROUP_NAME = "科技股"
ROOT_GROUP_LEGACY_NAMES = ("韓股科技股",)
SEED_SOURCE = "manual_watchlist_seed"
GROUP_NUMBER_PREFIX_PATTERN = re.compile(r"^\s*\d+(?:-\d+)?\.\s*")


@dataclass(frozen=True)
class StockSeed:
    name: str
    code: str
    suffix: str
    market_segment: str

    @property
    def symbol(self) -> str:
        return normalize_kr_symbol(f"{self.code}.{self.suffix}")


@dataclass(frozen=True)
class ThemeSeed:
    name: str
    stocks: tuple[StockSeed, ...]


@dataclass(frozen=True)
class ThemeGroupSeed:
    name: str
    children: tuple[ThemeSeed, ...]


KR_TECH_TREE: tuple[ThemeGroupSeed, ...] = (
    ThemeGroupSeed(
        name="1. 半導體主線",
        children=(
            ThemeSeed(
                name="1-1. 記憶體 / HBM / NAND / SSD",
                stocks=(
                    StockSeed("Samsung Electronics 三星電子", "005930", "KS", "KOSPI"),
                    StockSeed("SK hynix SK海力士", "000660", "KS", "KOSPI"),
                    StockSeed("Jeju Semiconductor 濟州半導體", "080220", "KQ", "KOSDAQ"),
                    StockSeed("SK Square", "402340", "KS", "KOSPI"),
                ),
            ),
            ThemeSeed(
                name="1-2. 晶圓代工 / 系統半導體 / Fabless",
                stocks=(
                    StockSeed("DB HiTek", "000990", "KS", "KOSPI"),
                    StockSeed("LX Semicon", "108320", "KQ", "KOSDAQ"),
                    StockSeed("Telechips", "054450", "KQ", "KOSDAQ"),
                    StockSeed("ABOV Semiconductor", "102120", "KQ", "KOSDAQ"),
                ),
            ),
            ThemeSeed(
                name="1-3. 半導體設備 / HBM封裝設備",
                stocks=(
                    StockSeed("Hanmi Semiconductor", "042700", "KS", "KOSPI"),
                    StockSeed("HPSP", "403870", "KQ", "KOSDAQ"),
                    StockSeed("Wonik IPS", "240810", "KQ", "KOSDAQ"),
                    StockSeed("Jusung Engineering", "036930", "KQ", "KOSDAQ"),
                    StockSeed("Eugene Technology", "084370", "KQ", "KOSDAQ"),
                    StockSeed("PSK", "319660", "KQ", "KOSDAQ"),
                    StockSeed("TES", "095610", "KQ", "KOSDAQ"),
                    StockSeed("EO Technics", "039030", "KQ", "KOSDAQ"),
                ),
            ),
            ThemeSeed(
                name="1-4. 半導體材料 / 光阻 / 特用氣體",
                stocks=(
                    StockSeed("Soulbrain", "357780", "KQ", "KOSDAQ"),
                    StockSeed("Dongjin Semichem", "005290", "KQ", "KOSDAQ"),
                    StockSeed("Wonik Materials", "104830", "KQ", "KOSDAQ"),
                    StockSeed("Hansol Chemical", "014680", "KS", "KOSPI"),
                    StockSeed("SK Inc.", "034730", "KS", "KOSPI"),
                ),
            ),
            ThemeSeed(
                name="1-5. 測試 / 探針 / Socket",
                stocks=(
                    StockSeed("ISC", "095340", "KQ", "KOSDAQ"),
                    StockSeed("Leeno Industrial", "058470", "KQ", "KOSDAQ"),
                    StockSeed("TSE", "131290", "KQ", "KOSDAQ"),
                ),
            ),
            ThemeSeed(
                name="1-6. PCB / 封裝基板 / AI Server板",
                stocks=(
                    StockSeed("Samsung Electro-Mechanics 三星電機", "009150", "KS", "KOSPI"),
                    StockSeed("Simmtech", "222800", "KQ", "KOSDAQ"),
                    StockSeed("ISU Petasys", "007660", "KS", "KOSPI"),
                    StockSeed("Korea Circuit", "007810", "KS", "KOSPI"),
                    StockSeed("Daeduck Electronics", "353200", "KS", "KOSPI"),
                ),
            ),
        ),
    ),
    ThemeGroupSeed(
        name="2. 顯示器 / OLED / 面板供應鏈",
        children=(
            ThemeSeed("2-1. 面板", (StockSeed("LG Display", "034220", "KS", "KOSPI"),)),
            ThemeSeed("2-2. 顯示驅動IC", (StockSeed("LX Semicon", "108320", "KQ", "KOSDAQ"),)),
            ThemeSeed("2-3. OLED材料", (StockSeed("Duk San Neolux", "213420", "KQ", "KOSDAQ"),)),
            ThemeSeed("2-4. 光學 / 相機模組 / 車用顯示零組件", (StockSeed("LG Innotek", "011070", "KS", "KOSPI"),)),
            ThemeSeed("2-5. 顯示器設備", (StockSeed("AP Systems", "265520", "KQ", "KOSDAQ"),)),
        ),
    ),
    ThemeGroupSeed(
        name="3. 二次電池 / EV / ESS",
        children=(
            ThemeSeed(
                name="3-1. 電池Cell",
                stocks=(
                    StockSeed("LG Energy Solution", "373220", "KS", "KOSPI"),
                    StockSeed("Samsung SDI", "006400", "KS", "KOSPI"),
                    StockSeed("SK Innovation", "096770", "KS", "KOSPI"),
                ),
            ),
            ThemeSeed(
                name="3-2. 正極材料 / 電池材料",
                stocks=(
                    StockSeed("LG Chem", "051910", "KS", "KOSPI"),
                    StockSeed("EcoPro BM", "247540", "KQ", "KOSDAQ"),
                    StockSeed("L&F", "066970", "KS", "KOSPI"),
                    StockSeed("POSCO Future M", "003670", "KS", "KOSPI"),
                ),
            ),
            ThemeSeed("3-3. 分離膜", (StockSeed("SK IE Technology", "361610", "KS", "KOSPI"),)),
            ThemeSeed("3-4. 電解液 / 添加劑", (StockSeed("Chunbo", "278280", "KQ", "KOSDAQ"),)),
        ),
    ),
    ThemeGroupSeed(
        name="4. 網路平台 / AI / 雲端 / 企業軟體",
        children=(
            ThemeSeed("4-1. 搜尋 / AI / 電商 / Fintech / Cloud", (StockSeed("NAVER", "035420", "KS", "KOSPI"),)),
            ThemeSeed("4-2. 通訊平台 / 內容 / 金融 / Mobility", (StockSeed("Kakao", "035720", "KS", "KOSPI"),)),
            ThemeSeed(
                name="4-3. 企業IT / Cloud / AI",
                stocks=(
                    StockSeed("Samsung SDS", "018260", "KS", "KOSPI"),
                    StockSeed("Douzone Bizon", "012510", "KS", "KOSPI"),
                ),
            ),
            ThemeSeed(
                name="4-4. 電信 / AI資料中心 / Cloud",
                stocks=(
                    StockSeed("SK Telecom", "017670", "KS", "KOSPI"),
                    StockSeed("KT", "030200", "KS", "KOSPI"),
                    StockSeed("LG Uplus", "032640", "KS", "KOSPI"),
                ),
            ),
        ),
    ),
    ThemeGroupSeed(
        name="5. 遊戲 / 內容科技",
        children=(
            ThemeSeed(
                name="5-1. 全球遊戲IP",
                stocks=(
                    StockSeed("KRAFTON", "259960", "KS", "KOSPI"),
                    StockSeed("Pearl Abyss", "263750", "KQ", "KOSDAQ"),
                ),
            ),
            ThemeSeed(
                name="5-2. MMORPG / 手遊",
                stocks=(
                    StockSeed("NCsoft", "036570", "KS", "KOSPI"),
                    StockSeed("Netmarble", "251270", "KS", "KOSPI"),
                    StockSeed("Kakao Games", "293490", "KQ", "KOSDAQ"),
                    StockSeed("Com2uS", "078340", "KQ", "KOSDAQ"),
                ),
            ),
            ThemeSeed("5-3. Blockchain Game / 題材型遊戲股", (StockSeed("Wemade", "112040", "KQ", "KOSDAQ"),)),
        ),
    ),
    ThemeGroupSeed(
        name="6. 機器人 / 自動化 / Physical AI",
        children=(
            ThemeSeed(
                name="6-1. 協作機器人",
                stocks=(
                    StockSeed("Doosan Robotics", "454910", "KS", "KOSPI"),
                    StockSeed("Neuromeka", "348340", "KQ", "KOSDAQ"),
                ),
            ),
            ThemeSeed("6-2. 機器人平台 / 雙足機器人", (StockSeed("Rainbow Robotics", "277810", "KQ", "KOSDAQ"),)),
            ThemeSeed("6-3. 工業機器人 / 自動化", (StockSeed("Robostar", "090360", "KQ", "KOSDAQ"),)),
            ThemeSeed(
                name="6-4. AI影像 / 無人系統 / 防務電子延伸",
                stocks=(
                    StockSeed("Hanwha Vision", "489790", "KS", "KOSPI"),
                    StockSeed("LIG Nex1", "079550", "KS", "KOSPI"),
                ),
            ),
        ),
    ),
    ThemeGroupSeed(
        name="7. 電子零組件 / 光學 / 智慧硬體 / 車用電子",
        children=(
            ThemeSeed("7-1. MLCC / 封裝基板 / 相機模組", (StockSeed("Samsung Electro-Mechanics", "009150", "KS", "KOSPI"),)),
            ThemeSeed("7-2. 相機模組 / 車用光學 / LiDAR延伸", (StockSeed("LG Innotek", "011070", "KS", "KOSPI"),)),
            ThemeSeed("7-3. 消費電子 / 車用零組件", (StockSeed("LG Electronics", "066570", "KS", "KOSPI"),)),
            ThemeSeed("7-4. 電力設備 / 智慧電網 / 自動化", (StockSeed("LS Electric", "010120", "KS", "KOSPI"),)),
            ThemeSeed("7-5. 車用軟體 / SI", (StockSeed("Hyundai AutoEver", "307950", "KS", "KOSPI"),)),
        ),
    ),
)


def _group_query(db: Session, *, parent_id: int | None, group_name: str):
    query = db.query(KRWatchlistGroup).filter(KRWatchlistGroup.group_name == group_name)
    if parent_id is None:
        return query.filter(KRWatchlistGroup.parent_id.is_(None))
    return query.filter(KRWatchlistGroup.parent_id == parent_id)


def display_group_name(group_name: str) -> str:
    return GROUP_NUMBER_PREFIX_PATTERN.sub("", group_name).strip()


def ensure_group(
    db: Session,
    *,
    parent_id: int | None,
    group_name: str,
    legacy_names: tuple[str, ...] = (),
    sort_order: int,
    description: str | None,
    stats: dict[str, int],
) -> KRWatchlistGroup:
    names = (group_name, *legacy_names)
    query = db.query(KRWatchlistGroup).filter(KRWatchlistGroup.group_name.in_(names))
    if parent_id is None:
        query = query.filter(KRWatchlistGroup.parent_id.is_(None))
    else:
        query = query.filter(KRWatchlistGroup.parent_id == parent_id)
    group = query.order_by(KRWatchlistGroup.id.asc()).first()
    if group is None:
        group = KRWatchlistGroup(
            parent_id=parent_id,
            group_name=group_name,
            description=description,
            sort_order=sort_order,
            is_active=True,
        )
        db.add(group)
        db.flush()
        stats["groups_created"] += 1
        return group

    changed = False
    if group.group_name != group_name:
        group.group_name = group_name
        changed = True
    if group.sort_order != sort_order:
        group.sort_order = sort_order
        changed = True
    if group.description != description:
        group.description = description
        changed = True
    if not group.is_active:
        group.is_active = True
        changed = True
    if changed:
        group.updated_at = utc_now()
        stats["groups_updated"] += 1
    else:
        stats["groups_unchanged"] += 1
    return group


def ensure_stock(db: Session, seed: StockSeed, stats: dict[str, int]) -> KRStockMaster:
    symbol = seed.symbol
    stock = db.query(KRStockMaster).filter(KRStockMaster.symbol == symbol).first()
    now = utc_now()
    if stock is None:
        stock = KRStockMaster(
            symbol=symbol,
            local_code=local_code_from_symbol(symbol),
            security_name=seed.name,
            security_name_kr=None,
            exchange="Korea Exchange",
            market_segment=seed.market_segment,
            sector=None,
            industry=None,
            asset_type="stock",
            listing_source=SEED_SOURCE,
            currency="KRW",
            exchange_timezone_name="Asia/Seoul",
            is_active=True,
            first_seen_at=now,
            last_seen_at=now,
        )
        db.add(stock)
        stats["stocks_created"] += 1
        return stock

    changed = False
    fill_values = {
        "local_code": local_code_from_symbol(symbol),
        "security_name": seed.name,
        "exchange": "Korea Exchange",
        "market_segment": seed.market_segment,
        "asset_type": "stock",
        "currency": "KRW",
        "exchange_timezone_name": "Asia/Seoul",
    }
    for field_name, value in fill_values.items():
        if not getattr(stock, field_name):
            setattr(stock, field_name, value)
            changed = True
    if not stock.is_active:
        stock.is_active = True
        changed = True
    stock.last_seen_at = now
    if changed:
        stock.updated_at = now
        stats["stocks_updated"] += 1
    else:
        stats["stocks_unchanged"] += 1
    return stock


def ensure_item(
    db: Session,
    *,
    group_id: int,
    stock: StockSeed,
    priority: int,
    note: str,
    tags: str,
    stats: dict[str, int],
) -> None:
    symbol = stock.symbol
    item = (
        db.query(KRWatchlistItem)
        .filter(KRWatchlistItem.group_id == group_id)
        .filter(KRWatchlistItem.symbol == symbol)
        .first()
    )
    if item is None:
        db.add(
            KRWatchlistItem(
                group_id=group_id,
                symbol=symbol,
                note=note,
                priority=priority,
                tags=tags,
                enabled=True,
            )
        )
        stats["items_created"] += 1
        return

    changed = False
    if item.note != note:
        item.note = note
        changed = True
    if item.priority != priority:
        item.priority = priority
        changed = True
    if item.tags != tags:
        item.tags = tags
        changed = True
    if changed:
        item.updated_at = utc_now()
        stats["items_updated"] += 1
    else:
        stats["items_unchanged"] += 1


def seed_kr_tech_watchlist(db: Session) -> dict[str, int]:
    stats = {
        "groups_created": 0,
        "groups_updated": 0,
        "groups_unchanged": 0,
        "stocks_created": 0,
        "stocks_updated": 0,
        "stocks_unchanged": 0,
        "items_created": 0,
        "items_updated": 0,
        "items_unchanged": 0,
    }

    root = ensure_group(
        db,
        parent_id=None,
        group_name=ROOT_GROUP_NAME,
        legacy_names=ROOT_GROUP_LEGACY_NAMES,
        sort_order=100,
        description="科技股主題標的清單。",
        stats=stats,
    )

    for group_index, group_seed in enumerate(KR_TECH_TREE, start=1):
        parent_name = display_group_name(group_seed.name)
        parent = ensure_group(
            db,
            parent_id=root.id,
            group_name=parent_name,
            legacy_names=(group_seed.name,) if parent_name != group_seed.name else (),
            sort_order=group_index * 100,
            description=f"{ROOT_GROUP_NAME} / {parent_name}",
            stats=stats,
        )
        for child_index, child_seed in enumerate(group_seed.children, start=1):
            child_name = display_group_name(child_seed.name)
            child = ensure_group(
                db,
                parent_id=parent.id,
                group_name=child_name,
                legacy_names=(child_seed.name,) if child_name != child_seed.name else (),
                sort_order=group_index * 100 + child_index * 10,
                description=f"{ROOT_GROUP_NAME} / {parent_name} / {child_name}",
                stats=stats,
            )
            note = f"{parent_name} > {child_name}"
            tags = ",".join((ROOT_GROUP_NAME, parent_name, child_name))
            for stock_index, stock_seed in enumerate(child_seed.stocks, start=1):
                ensure_stock(db, stock_seed, stats)
                ensure_item(
                    db,
                    group_id=child.id,
                    stock=stock_seed,
                    priority=stock_index * 10,
                    note=note,
                    tags=tags,
                    stats=stats,
                )

    return stats


def summarize_seeded_watchlist(db: Session) -> dict[str, int | str | None]:
    root = (
        db.query(KRWatchlistGroup)
        .filter(KRWatchlistGroup.parent_id.is_(None))
        .filter(KRWatchlistGroup.group_name == ROOT_GROUP_NAME)
        .order_by(KRWatchlistGroup.id.asc())
        .first()
    )
    if root is None:
        return {
            "root_group_id": None,
            "root_group_name": None,
            "group_count": 0,
            "item_count": 0,
            "unique_symbol_count": 0,
        }

    all_groups = db.query(KRWatchlistGroup).all()
    children_by_parent: dict[int | None, list[int]] = {}
    for group in all_groups:
        children_by_parent.setdefault(group.parent_id, []).append(group.id)

    group_ids: list[int] = []
    stack = [root.id]
    while stack:
        group_id = stack.pop()
        group_ids.append(group_id)
        stack.extend(children_by_parent.get(group_id, []))

    item_count = (
        db.query(KRWatchlistItem)
        .filter(KRWatchlistItem.group_id.in_(group_ids))
        .count()
    )
    unique_symbol_count = (
        db.query(KRWatchlistItem.symbol)
        .filter(KRWatchlistItem.group_id.in_(group_ids))
        .distinct()
        .count()
    )
    return {
        "root_group_id": root.id,
        "root_group_name": root.group_name,
        "group_count": len(group_ids),
        "item_count": item_count,
        "unique_symbol_count": unique_symbol_count,
    }


def validate_kr_tables(db: Session) -> None:
    try:
        db.query(KRWatchlistGroup).limit(1).all()
        db.query(KRWatchlistItem).limit(1).all()
        db.query(KRStockMaster).limit(1).all()
    except OperationalError as exc:
        raise RuntimeError(
            "KR market tables are missing. Run the KR Alembic migration before seeding."
        ) from exc


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the Korean tech stock watchlist.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build the seed changes and roll them back instead of writing to the database.",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print the current seeded Korean tech watchlist summary without writing.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        validate_kr_tables(db)
        if args.summary:
            print({"mode": "summary", **summarize_seeded_watchlist(db)})
            return
        stats = seed_kr_tech_watchlist(db)
        if args.dry_run:
            db.rollback()
            mode = "dry_run"
        else:
            db.commit()
            mode = "applied"
        print({"mode": mode, **stats})
    finally:
        db.close()


if __name__ == "__main__":
    main()
