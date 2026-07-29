# OMI 對外即時資料契約大修正

## 任務目標

依 `OMI_external_data_remediation_2026-07-27.txt` 重整 OMI backend 對外資料契約，讓 Backend HTTP、`omi.decision.v4`、repo MCP、Frontend 與 Kuro 對 freshness、session、cache、unsupported、partial coverage 與 provider limitation 使用同一份 backend 真相。

## 範圍

- P0：TAIEX 尾盤／正式收盤交接、TW／JP／KR 收盤後 freshness、required unsupported readiness、`tw_index` freshness projection、cache-only replay。
- P1：metadata 與 quality 端到端一致、JP／KR 1m→5m 真實聚合、五檔 projection、排行欄位、source-health relevance、指數量／值／VWAP 語意、固定時點個股與指數 replay。
- P2：JP／KR breadth coverage 誠實揭露、auction unmatched 與 order count 維持 `null + not_provided`。

## 非目標

- 不處理使用者已明確暫緩的「TAIEX 因 API 次數過多退回 Yahoo」問題。
- 不把 OMI 改成自動交易或猜漲跌系統。
- 不用 frontend、MCP 或 Kuro hardcode backend 市場邏輯。
- 不為了讓 quality 變綠而隱藏 stale、partial、missing 或 provider failure。
- 不以小樣本冒充 JP／KR 全市場 breadth。
- 不 commit 或 push；除非使用者之後明確要求。

## 硬性限制

- Backend 是 close resolution、freshness、capability readiness、cache policy 與 source-health relevance 的真相來源。
- `cache_only` 只讀已保存資料，不觸發外部 refresh；`prefer_live` 可 bounded refresh 後 fallback cache；`require_live` 不得把 completed-session cache 當 live。
- required unsupported 必須留下 provenance 並降低 readiness；optional unsupported 可保留 ready，但必須出現在 limitations。
- 正式收盤、last trade、intraday last point、high price 必須是不同語意。
- provider 未提供的委託筆數或 auction unmatched 不推算。
- 保留既有 public route 與欄位；本次契約採 additive、consumer-safe 變更。
- 保存並共存於現有 dirty worktree，不覆蓋或回退無關變更。

## 交付物

- 本任務的 `Prompt.md`、`Plan.md`、`Progress.md`、`CompletionMatrix.md`。
- Backend market／AI contract 修正與 targeted regression tests。
- 相關安全驗證、正式 launcher runtime、HTTP、frontend proxy 與 MCP protocol 證據。
- 明日盤中／尾盤驗收矩陣與尚待實盤驗證的限制。

## 完成定義

1. TAIEX 尾盤不同候選值可被保存、重播並解釋選擇理由。
2. official close 具 pending／confirmed 與來源證據。
3. TW／JP／KR 收盤後當日分 K 為 `latest_completed_session`。
4. required unsupported 不再得到 `analysis_ready=true` 或 `evidence_status=ready`。
5. `tw_index` 的 `data.freshness` 不再是空 semantic payload。
6. 已宣告的 volume／interval metadata 不再被 quality 誤判 missing。
7. JP／KR 5m 為 session-aware 真實 OHLCV 聚合。
8. `cache_only` 可跨 request／runtime restart 回放已落地 bars。
9. 五檔按 payload level 對外輸出，未提供的 order count 維持明確空值。
10. focused request 不被無關 background source-health 拉低 readiness。
11. targeted tests、安全 backend profile、正式 launcher HTTP／proxy／MCP smoke 全部通過。
