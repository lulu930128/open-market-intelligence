# CP6 Taiwan Dataset Platform Contract

## Gate result

CP6的source/platform gate已通過。這代表所有已盤點的台股production dataset family都能由同一份market-owned catalog回答owner、payload、storage、read/projection/health operation、expected-state policy、eligibility、refreshability、bounded operation、postcondition、lineage狀態與convergence狀態；不代表production DB中每個family目前資料都完整或fresh。

## Stable read surface

- `GET /api/market/data-core/datasets`：列出typed lifecycle contracts。
- `GET /api/market/data-core/operations`：只描述可執行的bounded mutation operations，不直接執行refresh。
- `GET /api/market/data-core/datasets/{dataset_id}/health?target=...`：cache-only讀取實際storage與lineage evidence。

共同平台刻意不提供「refresh all」mega-endpoint。Mutation仍必須走對應dataset的explicit route/job，由原本transaction owner或已遷移platform owner執行，且public consumer不能自行提高call、symbol、range、timeout或provider budget。

## Enforced invariants

- Catalog現有28個dataset contract、18個bounded operation；每個read、projection、health與refresh callable都由test實際resolve。
- `advertised=true`必須有真實projection callable。
- `refreshable=true`必須有market-owned executable operation、hard bounds與postcondition；non-refreshable dataset不可攜帶假refresh metadata。
- Router、AI與KGI module不得成為dataset mutation owner。
- `lineage_gap` dataset不得advertise repairable；`platform_owned`只允許canonical raw receipt或derived component lineage。
- Health probe只描述actual storage與lineage evidence，不製造跨dataset的假freshness verdict；expected date、release window、eligibility與stale rule仍由dataset-specific policy擁有。
- Dataset-specific tables與typed payload保留，不改造成generic blob。

## Actual production evidence

Production SQLite以read-only URI盤點，未執行migration、provider IO或DB write。快照當時為27個dataset：9個observed、1個missing、15個lineage incomplete、2個lineage limited、0個schema unavailable。quote與official index因production仍在Alembic 0066而如實回報缺少0068/0067 lineage schema；ETF、events、futures與derivatives有實際row時仍保留lineage gap，沒有被catalog名稱掩飾成canonical。

`tw.technical.daily`於CP7加入成第28個dataset。它不重複persist indicators，而是由resolved `tw.daily.ohlcv`加上backend algorithm/version/parameter contract產生，health probe以component storage為證據，並標記為non-refreshable derived projection。

## Provider and usage boundary

TWSE/TPEx official daily/index與TWSE MIS public last-trade各自保留provider/resource identity。Public MIS只允許single-symbol、bounded、personal-research best effort；沒有正式SLA，也沒有原始或加值資料向外轉播授權的推定。Catalog只記錄可用能力與限制，不會把provider availability、dataset completeness與resolved evidence health混成同一盞燈。

## Remaining debt after CP6

- Lineage-gap family仍須在各自vertical slice補transaction/raw receipt/component lineage；登錄與health可見性不是canonical migration完成。
- Production DB尚未套用0067/0068，因此新index/quote repository尚未被running runtime採用。
- Existing index dashboard、legacy refresh orchestration與部分live/intraday compatibility path留在CP7/CP8切換與移除。
