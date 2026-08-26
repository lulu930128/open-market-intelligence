from __future__ import annotations

from app.market.tw_realtime_stream_platform import read_taiwan_realtime_market_stream
from app.market.tw_realtime_capabilities import KGI_QUOTE_SNAPSHOT_DESCRIPTOR


class FakeStreamPort:
    provider_key = "kgi_superpy"

    def __init__(self) -> None:
        self.calls: list[tuple[str, int, int, int, int]] = []

    def market_stream_snapshot(
        self,
        stock_id: str,
        *,
        recent_trade_limit: int,
        auction_limit: int,
        kbar_limit: int,
        diagnostic_limit: int,
    ) -> dict:
        self.calls.append(
            (
                stock_id,
                recent_trade_limit,
                auction_limit,
                kbar_limit,
                diagnostic_limit,
            )
        )
        return {
            "stock_id": stock_id,
            "provider": self.provider_key,
            "canonical_truth": True,
            "decision_usable": True,
            "research_usable": True,
        }


def test_stream_projection_selects_injected_descriptor_port_without_acquiring() -> None:
    port = FakeStreamPort()

    result = read_taiwan_realtime_market_stream(
        "2330",
        recent_trade_limit=10,
        auction_limit=20,
        kbar_limit=30,
        diagnostic_limit=0,
        descriptors=(KGI_QUOTE_SNAPSHOT_DESCRIPTOR,),
        ports={"kgi_superpy": port},
    )

    assert result == {
        "stock_id": "2330",
        "provider": "kgi_superpy",
        "projection_scope": "presentation_only",
        "canonical_truth": False,
        "decision_usable": False,
        "research_usable": False,
        "provider_specific": True,
    }
    assert port.calls == [("2330", 10, 20, 30, 0)]
