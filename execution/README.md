# Manual Trading Execution v1：M1

此目錄是 **純離線、synthetic-only、stdlib-only** 的 execution domain。沒有服務、API、CLI、SDK、券商 adapter、production caller 或實盤啟用設定。

從 repo root 執行：

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s execution/tests -t . -v
.\.venv\Scripts\python.exe -B scripts/check-architecture.py --constraints architecture/execution-constraints.toml --debt architecture/execution-debt.toml
```

需要 Python 3.11+；套件和 domain 測試只使用 stdlib。Repo architecture CI 亦透過新增的 `backend/tests/architecture/test_manual_execution_boundaries.py` 發現本套測試與獨立 manifest。

- `contracts.py`：不可變草稿、證據、預覽、確認、模擬結果、事件。
- `validation.py`：純 `assess` preflight；資料缺漏、過期、不支援、identity、tick、lot、權限及資源驗證。
- `state_machine.py`：純 `transition`；timeout／unknown／reconciliation／cancel／late-event。
- `service.py`：單一 owner、序列呼叫的 in-memory 預覽／確認／收據冪等與 audit。
- `tests/fixtures.py`：明確虛構的價格單位、tick、lot、帳戶與權限範例；不是交易所或券商規則。

完整合約、信任邊界、未實作項目與 future gates 見 [ManualTradingExecutionV1](../docs/architecture/ManualTradingExecutionV1.md)。

## 離線呼叫範例

以下只示範 fixture 驗證，不提供 executable runtime entrypoint：

```python
from execution.tests.fixtures import NOW, confirmation, fixture, service
from execution.contracts import EventKind, SimulationEvent

domain = service()
draft, evidence = fixture()
preview = domain.preview(draft, evidence, now=NOW)
# 測試明示人工確認動作；不是使用者身分驗證，也不是 2FA。
receipt = domain.confirm(preview, confirmation(preview), now=NOW)
result = domain.apply(
    SimulationEvent("fixture-accepted", preview.preview_id, EventKind.ACCEPTED, NOW, 1),
    now=NOW,
)
assert result.simulated and not result.durable
```

In-memory object 消失即失去冪等與 audit 歷史；不同 object／process 不共享鎖、額度或記錄。不得把此程式接上實盤或當成安全認證邊界。
