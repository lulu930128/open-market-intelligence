# Roadmap

本 roadmap 只描述產品化方向與近期技術債收斂順序；不是承諾日期表。若任務和這裡衝突，先回到 `ProductVision.md`、`OperatingModel.md` 與 repo `AGENTS.md` 判斷。

## 北極星

OMI 要成為台股優先、本機優先、可驗證的市場研究工作台。AI decision core 應能基於可信 evidence 產出條件化決策輔助，並清楚揭露資料限制。

## 近期主線

1. 固定產品主線
   讓 README、AGENTS、`docs/product/` 與 agent-run 文件對齊：台股核心、其他市場 context layer、非自動交易、freshness/partial/missing 可見、backend 擁有市場邏輯。

2. 完成 market payload contract
   將 `market_data_params`、`payload_level`、slot envelope、slot status、consumer rules 與 backend projection 穩定化。MCP、Frontend、Kuro 都應只消費 backend contract，不自行補資料。

3. 強化 AI decision core
   確保回答包含情境、回測區、進場條件、失效條件、風險處理、反證與資料限制。缺資料時先補資料或明確回報缺口。

4. 收斂 frontend 資訊架構
   逐步把 dashboard 大元件中的純 helper、routing/state、slot rendering、market type 與 API contract 抽到 shared modules。保留台股為設計基準，避免每加一個市場就複製一套互不相容 UI。

5. 補齊跨市場 context layer
   以台股 contract 為基準，逐步讓 US/JP/KR/crypto 的 compact evidence、slots、freshness 與 payload trimming 對齊。市場特有資料要保留差異，但用共同 envelope 對外呈現。

## Milestone

### M1：產品基線可引用

- `docs/product/` 有非空且一致的產品方向。
- 架構變更前可用文件判斷是否偏離主線。
- 方向保護規則能明確反駁不穩定需求。

### M2：Payload Contract 可測

- Backend compact evidence 的 slot envelope 有 schema invariant tests。
- `payload_level` 對大型 payload 有明確裁切行為。
- Public slim result 能投影 slots，consumer 不需要讀 backend internals。

### M3：Frontend Shell 可維護

- 市場 routing/type/helper 不依附 sidebar 或 dashboard 大元件。
- Slot rendering 與資料 completeness 呈現有共用規則。
- Market dashboard 的新增市場成本下降，且不引入前端市場邏輯。

### M4：跨市場資料成熟

- US/JP/KR/crypto 至少具備可比較的 compact evidence 與 freshness。
- Planned/missing/not_applicable 能被 UI 與 external consumer 正確呈現。
- 重要 provider failure 有 source health 或 provider events 可追蹤。

## 暫緩項目

- 自動交易與下單。
- 把其他市場升級成與台股平等的主線產品。
- 全市場、無邊界、無 freshness policy 的大量 backfill。
- 未定義 trust/budget policy 的新聞、事件、付費資料或 AI memory 自動寫入。
