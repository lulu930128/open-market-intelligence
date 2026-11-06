"""Public read-only lookup regression, with actual canonical receipt fixtures."""
import json
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, event
from app.db.models import Base, StockMaster
from app.db.session import SessionLocal, get_db
from app.market.daily_ohlcv_platform import refresh_taiwan_official_daily_venue
from app.market.daily_ohlcv_acquisition import TaiwanOfficialDailyAcquisitionExecutor
from app.routers.tw_market_dashboard import router
from test_tw_etf_daily_collection import DAY, NOW, payload
from test_tw_official_daily_platform import FakeResponse
from test_tw_early_regular_consumers import OfflineClient


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("mixed_venue")
    engine = create_engine(f"sqlite:///{tmp_path / 'consumer.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with SessionLocal(bind=engine) as db:
        db.add_all([StockMaster(stock_id=s, stock_name=s, market=v, instrument_type=t, is_active=a)
            for s,v,t,a in [("00679B","TPEx","ETF",True),("00687B","TPEx","ETF",True),
                ("2330","TWSE","stock",True),("0050","TWSE","ETF",True),("6182","TPEX","stock",True),
                ("00688B","TPEx","ETF",False),("073399","TPEx","warrant",True),("AAPL","NASDAQ","stock",True)]])
        db.commit()
        for venue, symbols in [("TWSE", ["2330", "0050"]), ("TPEX", ["6182", "00679B", "00687B"])]:
            resource = "MI_INDEX_ALLBUT0999" if venue == "TWSE" else "tpex_dated_daily_quotes"
            def fetch(route):
                assert route.resource_id == resource
                return FakeResponse(text=json.dumps(payload(resource, symbols), ensure_ascii=False))
            refresh_taiwan_official_daily_venue(db, venue=venue, trade_date=DAY, requested_at=NOW,
                refresh_published=False, route_state={} if venue == "TWSE" else {
                    "version":1,"venue":"TPEX","trade_date":DAY.isoformat(),
                    "attempted_resources":["tpex_mainboard_quotes","tpex_mainboard_daily_close_quotes"]},
                acquisition=TaiwanOfficialDailyAcquisitionExecutor(fetchers={resource:fetch}, clock=lambda:NOW))
        app = FastAPI(); app.include_router(router, prefix="/api/market/tw-dashboard")
        def dependency(): yield db
        app.dependency_overrides[get_db] = dependency
        statements = []
        def witness(_c,_cu,statement,*_args):
            if statement.lstrip().split(None,1)[0].upper() in {"INSERT","UPDATE","DELETE","REPLACE"}: statements.append(statement)
        event.listen(engine,"before_cursor_execute",witness)
        yield OfflineClient(app)
        event.remove(engine,"before_cursor_execute",witness)
        assert statements == []
    engine.dispose()


@pytest.mark.parametrize("symbol", ["00679B", "00687B"])
@pytest.mark.parametrize("path", ["search", "chart", "research"])
def test_public_tp_ex_etf_search_chart_research_keep_canonical_identity(client, symbol, path):
    url = "/api/market/tw-dashboard/"
    path_url = "symbols/search" if path == "search" else f"stocks/{symbol}/{path}"
    response = client.get(url + path_url, params={"keyword": symbol} if path == "search" else {"timeframe": "daily", "bars": 20})
    assert response.status_code == 200
    data = response.json()
    if path == "search":
        assert data["count"] == 1 and data["items"][0]["stock_id"] == symbol
    elif path == "chart":
        assert data["instrument_type"] == "etf" and data["market"].upper() == "TPEX"
        point = data["chart"]["points"][-1]
        assert point["source"] == "TPEx Dated Daily Quotes" and point["raw_receipt_id"].startswith("raw_fetch_result:")
    else:
        assert data["stock_id"] == data["technical"]["stock_id"] == symbol and data["cache_only"]


@pytest.mark.parametrize("symbol,eligible", [("2330",True),("0050",True),("6182",True),
    ("00688B",False),("073399",False),("AAPL",False)])
def test_existing_venue_active_and_instrument_gates_remain(client, symbol, eligible):
    root="/api/market/tw-dashboard/"
    search=client.get(root+"symbols/search", params={"keyword":symbol}).json()
    assert bool(search["items"]) is eligible
    for path in ["chart","research"]:
        response=client.get(root+f"stocks/{symbol}/{path}", params={"timeframe":"daily", "bars":20})
        assert response.status_code == (200 if eligible else 404)
