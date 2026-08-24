# 進度

## 目前狀態

第一版與第二階段均已完成：隔離 KGI runtime、selected-symbol lease、近期成交、試撮軌跡、1 分 K、五檔衍生值、snapshot／SSE contract，以及 Quote Depth 即時成交版面均已接入正式 launcher runtime。2026-08-18 已將 `.venv-kgi` 重建為 64-bit Python 3.12.3，排除 Python 3.13／OpenSSL 嚴格 X.509 驗證與 KGI 官網憑證鏈的相容問題。

正式 runtime 已用單一 `2330`、quote-only bounded smoke 證明登入、訂閱、callback、近期成交 buffer、五檔衍生值與 lease cleanup。當時為盤後，1 分 K callback 與試撮即時軌跡仍需下一個有效交易時段補做 live acceptance；在此之前只宣稱程式與測試已就緒，不宣稱盤中實測完成。

## 已確認決策

- KGI 僅服務使用者正在查看的個股，不做全市場常駐訂閱。
- 使用一個 `subscribe_all` topic 同時取得 Tick、五檔與 `simtrade`。
- KGI SDK 放在 `.venv-kgi` quote-only 子程序，主 backend venv 不直接依賴。
- Frontend 使用明確 lease API；quote GET 不負責建立新訂閱。
- KGI 只有在 event 合格後才升為 primary；其他情況保留既有來源。

## 驗證證據

- KGI 官方文件確認 `login(person_id, person_pwd, simulation)`。
- KGI 2.1.0 wheel 確認 `set_cb_all`、`subscribe_all`、`get_subscriptions`、`unsubscribe` 與 event callback 實際存在。
- KGI All event 確認含 OHLC、close、volume、total_volume、五檔、`simtrade`、`suspend`。
- `kgisuperpy==2.1.0` 已安裝在 `.venv-kgi`，未修改主 backend `.venv`。
- Quote bridge `ready -> status -> shutdown` smoke 通過，未呼叫登入。
- Backend targeted regression：92 passed，另有既有 pytest cache 權限 warning。
- Safe backend profile：compileall、targeted pytest、`git diff --check` 通過。
- Safe frontend profile：ESLint、TypeScript no-emit、`git diff --check` 通過。
- 真實 bounded smoke：單一 `2330`、最多 40 秒、quote-only；KGI native login 回報 `CheckCAComponent`／`CoCreateInstance` 失敗，`FIsLogon=false`、無 quote token、無 `Quote` façade，cleanup 已執行。
- 使用者完成憑證申請／查詢畫面的主機端與客戶端有效狀態後再次 smoke；root `.env` 已正確載入，但 SDK 仍無法初始化 quote service，bridge 保持 `ready`、active subscriptions 為空。憑證有效不等於「系統環境檢測」的 ActiveX／COM 可用，需完成該頁檢測後再試；為避免連續登入失敗觸發 KGI 異常流量限制，本輪停止追加重試。
- Bridge 已補登入初始化失敗分類與半初始化 Logout；新增 regression 後為 28 passed、10 subtests passed。
- 測試產生的 5 個 KGI SDK log 與臨時 smoke 腳本已移除，`.env.example` 的誤填 credentials 已清空。
- 2026-08-18 18:47（Asia/Taipei）再次執行單一 `2330`、一次登入的 quote-only smoke；root `.env` 四個 KGI 設定已正確載入，`simulation=false`，但 bridge 仍在訂閱前回報 quote service 未初始化，active subscriptions 為空，cleanup 與 Logout 完成，未讀取帳戶、持倉或下單功能。
- 64-bit `KGICGCAPIATL.CGCAPI` COM 可直接建立，排除當日仍是 `CoCreateInstance` 失敗；本次 KGI SDK 非空 log 只有 2 個，未出現帳密錯誤、權限拒絕或 `OnLogonResponse`，而是 `CERTIFICATE_VERIFY_FAILED`、`Missing Subject Key Identifier` 與 `Max retries exceeded`。
- 對 `https://superpy.kgieworld.com.tw/` 的無帳密驗證：目前 `.venv-kgi` Python 3.13.9／OpenSSL 3.0.18 失敗；Windows `Invoke-WebRequest` 與本機 Python 3.12.3 均通過 TLS 並回 HTTP 200。根因是 Python 3.13 預設嚴格 X.509 驗證與 KGI 目前憑證鏈的相容性，不應以 `verify=false` 關閉 TLS 驗證。
- 因 KGI 對異常登入／流量有保護，本輪只做一次登入，不再追加重試。
- `setup-kgi-superpy.ps1` 現在只接受 64-bit Python 3.12，透過 `-Recreate` 明確重建舊 runtime，並在刪除前驗證目標是 repo 內非 reparse-point 的 `.venv-kgi`；主 backend `.venv` 不受影響。
- Quote bridge 在 import KGI SDK 或登入前檢查 runtime，Python 3.13／32-bit 會回傳 safe fatal response；ready envelope 會揭露實際 Python patch version。
- `.venv-kgi` 已重建為 Python 3.12.3／64-bit／`kgisuperpy 2.1.0`；對 KGI 官方 HTTPS endpoint 的 TLS 驗證通過並回 HTTP 200，bridge `ready -> status -> shutdown` protocol smoke 通過。
- 2026-08-18 約 19:24（Asia/Taipei）執行唯一一次正式環境 `2330` quote-only smoke：`subscription_requested`、bridge `connected`、active symbols 僅 `2330`、收到原始行情 callback，最後事件為 `EVENT_SUBSCRIBE_OK`，cleanup 正常。測試在盤後，只證明登入／訂閱／callback 鏈路，不將該筆 callback 宣稱為正常盤中的 freshness 驗收。
- Python targeted regression：KGI provider 與台股 quote-depth 共 29 passed；safe backend profile 的 compileall、pytest 與 `git diff --check` 通過。
- 本輪產生的 6 個可再生 KGI SDK log／錯誤表與臨時 smoke 腳本已移除，未保留含身分識別風險的 SDK 檔名或內容。
- 第二階段 targeted backend regression：43 passed、70 subtests passed，涵蓋 KBar callback allowlist、KBar degraded warning、正式成交／試撮分流、dedupe、buffer 上限、KBar upsert、schema 與 API inventory。
- Safe backend profile 通過：compileall、targeted pytest、`git diff --check`；log 位於 `.tmp/validation/20260818-195925`。
- Safe frontend profile 通過：完整 ESLint、TypeScript no-emit、`git diff --check`；log 位於 `.tmp/validation/20260818-195939`。
- Quote Depth 的控制列固定為「即時成交／試撮」；右欄依選擇顯示成交流或「時間／買進／賣出／試撮價／試撮量」明細，試撮結束後沿用同一欄顯示保存快照。
- 重複的成交量摘要已從 Quote Depth 移除，成交單量與累計量直接留在即時成交表內；主內容只保留五檔與目前明細兩個區塊。
- 版面修正後 Quote Depth targeted browser E2E 為 3 passed，涵蓋即時成交流、保存試撮快照與 live auction callback；safe frontend profile 的完整 ESLint、TypeScript no-emit 與 `git diff --check` 均通過，log 位於 `.tmp/validation/20260818-231339`。
- 五檔／明細的桌面比例由 36／64 收斂為約 44／56；兩欄內容區固定同高，五檔列與成交流／試撮明細在各自區塊內填滿或捲動。
- 44／56 與同高修正後，Quote Depth targeted browser E2E 再次為 3 passed；safe frontend profile 的 lint、TypeScript no-emit 與 diff check 通過，log 位於 `.tmp/validation/20260818-232615`。
- 試撮 replay 不再只挑一個早盤快照：所有 backend 標記為試撮的保存快照（早盤、尾盤、延後撮合）都在同一格依時間倒序顯示；左側五檔使用當日最後一個試撮快照。
- KGI bridge 新增四資源白名單 Data fetch；public API 為 `POST /api/market/kgi-data/{stock_id}/backfill`，最多 4 requests、每項 500 records、分價量 5 天，且不在一般 GET/SSE 隱性觸發。
- 2026-08-18 以單一 `2330` 做四項 bounded Data smoke：`批次取得個股盤中行情-含興櫃(tick含試搓)` 成功回傳 1 列；當日成交明細、歷史分 K、分價量均由 KGI 回 `D403`。API 將其標成 `plan_restricted`，不宣稱可用。
- 2026-08-19 由既有 OMI backend runner 精準重建 backend child tree；正式 `127.0.0.1:8400` health 為 `ok`，live OpenAPI 已採用 `POST /api/market/kgi-data/{stock_id}/backfill`。再以單一 `2330`、單一 `market_snapshot`、limit 5 做 1-request API smoke，回應為 `tw-kgi-data-v1 / available / returned_count=1 / none_raw_bounded_response`。
- 本輪 targeted backend 為 26 passed、60 subtests passed；TypeScript、ESLint 與 Quote Depth 三個瀏覽器情境均通過，其中 replay fixture 同時包含早盤與尾盤兩筆試撮快照。
- 正式 launcher 已重新啟動並確認 `API OK; UI OK`；backend 實際使用 `127.0.0.1:8400`，frontend 使用 `127.0.0.1:3000`。
- 正式 runtime 的單一 `2330` bounded smoke 收到 1 筆 KGI callback：recent trades 1、depth metrics available、active lease 1；finally 釋放後 active leases、recent trades、KBars 均歸零。
- Frontend production build 未在本輪執行，因目前 dev runtime 正在持有 `.next`；已以完整 lint、typecheck 與 targeted browser E2E 取代，避免干擾使用者現有 runtime。
- 既有「快速切換選股忽略舊回應」E2E fixture 在 quote assertion 前即找不到 `2303` ranking link；此失敗與本次 Quote Depth 版面無關，保留為既有測試資料流待查，不列入本次通過項目。

## 後續啟用

- KGI quote bridge 已固定為本機 64-bit Python 3.12；不要停用 TLS 憑證驗證，也不要改回主 backend 的 Python 3.13 runtime。
- 保留 KGI 官方前置準備：CA 憑證、API 資格與憑證小幫手環境檢測均需維持有效。
- 在 repo root `.env` 填入 `KGI_SUPERPY_PERSON_ID`、`KGI_SUPERPY_PASSWORD`，並設定 `ENABLE_KGI_SUPERPY_QUOTE=true`；不要填入 tracked `.env.example`。
- 重新啟動 OMI，於台股交易時段選取單一個股，驗證來源標籤、五檔、成交與試撮 event。
- 真實 smoke 若遇到 CA 或行情權限問題，保留 MIS fallback 並依 lease / quote contract 狀態診斷。
