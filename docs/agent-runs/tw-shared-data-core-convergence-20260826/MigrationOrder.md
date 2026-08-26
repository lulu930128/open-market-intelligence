# 台股長尾 Dataset Migration Order

## Current catalog baseline

- `PLATFORM_OWNED`：9
- `COMPATIBILITY`：7
- `LINEAGE_GAP`：12
- `COMPATIBILITY_DERIVED`：2

`tw.intraday.bars`、current index與current breadth已離開初始gap。兩個derived state已有component lineage，但transaction/producer仍包含compatibility ownership，因此不升格成platform-owned。

## Wave A — 高決策影響與現有refresh seam

1. `tw.chips.market.daily`：先補raw receipt與transaction owner；不得把missing universe補0。
2. `tw.chips.institutional.daily`、`tw.chips.margin.daily`：拆開legacy multi-category refresh owner，保留official trade-date semantics。
3. `tw.fundamentals.revenue.monthly`、`tw.fundamentals.financials.quarterly`：建立published-period eligibility與canonical raw receipts。
4. `tw.chips.broker_branch.daily`：保留Top15 censorship；absence維持unknown-not-ranked。

## Wave B — Profile / ownership / corporate events

1. `tw.company.profile`：reader seam已完成；下一步搬refresh transaction/raw receipt owner。
2. `tw.ownership.shareholding.weekly`：保存publication date與observation period，不用fetch date偽裝event date。
3. `tw.events.corporate`：建立event identity、revision與cancellation semantics後再advertise repairability。

## Wave C — ETF snapshots

依序：`tw.etf.profile` -> `tw.etf.nav.daily` -> `tw.etf.pcf.snapshot` -> `tw.etf.inav.snapshot`。

- NAV、PCF與iNAV不可合成單一lineage。
- snapshot需要event/received/fetched time與provider limitation。
- reference market與listed venue要顯式，不由consumer猜。

## Wave D — Futures / derivatives

依序：futures quote -> futures intraday bars -> futures daily bars -> option chain -> large trader -> term structure。

- quote、bar、chain與derived curve分typed contract。
- settlement/final與current observation分開。
- trading session、contract month、roll與expiry由market policy擁有。

## Anti-debt gates

- 新consumer不得direct provider import、direct market-truth SQL或自建fallback/quality table。
- 新refreshable capability必須有bounded operation、transaction owner、postcondition與raw lineage。
- lineage無法證明時維持gap；不得推測式mass backfill。
- provider adapter不commit；persist成功後mandatory repository reread。
- `unknown != 0`、censored absence不是交易分類。
