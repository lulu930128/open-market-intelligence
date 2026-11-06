"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import Link from "next/link";
import { ApiError, fetchJson, requestJson } from "@/lib/api";
import type { Direction, NominationResult, NominationSnapshot, ProposalSummaryList, ProposalPromotion, ProposalRead,
  ProposalDeletion, ResearchMarket, ResearchMonitor, RevisionList, SetupEvaluation } from "@/types/researchTrade";
import { buildDashboardHref } from "@/components/market-dashboard/selection/dashboardRoutes";
import styles from "./ResearchCandidates.module.css";

const API = "/api/research/trade-proposals";
const MARKET_MISMATCH = "後端回傳的市場與目前選擇不符，已停止顯示。請確認後端已載入更新，再重新讀取。";
const origins: Record<string, string> = { USER_NOMINATION: "人工提名", AI_NOMINATION: "AI 提名", OMI_SCREEN: "盤後自動" };
const states: Record<string, string> = { WAITING_PRICE: "等待價格", WAITING_CONFIRMATION: "等待確認",
  DATA_UNKNOWN: "資料未知", DATA_BLOCKED: "資料阻擋", WAITING_RESEARCH: "等待研究",
  REVIEWABLE: "研究可評估", INVALIDATED: "已失效", EXPIRED: "已到期", proposed: "已保存", scheduled: "尚未生效",
  qualified: "通過研究篩選" };
const entryRules = { at_or_above: "達到或高於進場價", at_or_below: "達到或低於進場價", next_open: "下一次開盤" };
const costLabels: Record<string, string> = { commission_rate: "手續費率", minimum_commission: "最低手續費",
  sell_tax_rate: "賣出交易稅", entry_slippage_bps: "進場滑價", exit_slippage_bps: "出場滑價", paper_other_cost: "其他模擬成本", other_cost: "其他模擬成本", slippage_per_share: "每股滑價", short_borrow_per_share_session: "每股每日借券費" };
const show = (value: unknown) => value === null || value === undefined || value === "" ? "未提供" : String(value);
function time(value?: string | null) {
  if (!value) return "未提供";
  if (value.length === 10) return value;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : new Intl.DateTimeFormat("zh-TW", {
    timeZone: "Asia/Taipei", dateStyle: "short", timeStyle: "medium", hour12: false,
  }).format(parsed);
}
function snapshot(read: ProposalRead): NominationSnapshot {
  const item = read.proposal.evidence.items.find(item => ["research.stock_nomination.v1", "research.us_watchlist_nomination.v1"].includes(item.source_ref));
  try {
    const parsed: unknown = item ? JSON.parse(item.snapshot_json) : {};
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as NominationSnapshot : {};
  } catch { return {}; }
}
function originLabel(origin: string | undefined, market: ResearchMarket) {
  return market === "US" && origin === "OMI_SCREEN" ? "觀察名單掃描" : origins[origin ?? ""] ?? "來源未提供";
}
function stockName(read: ProposalRead) {
  if (read.proposal.market === "US") return read.proposal.symbol;
  const identity = snapshot(read).price_map?.payload;
  return identity?.stock_id === read.proposal.symbol && typeof identity.stock_name === "string" && identity.stock_name.trim()
    ? identity.stock_name.trim() : "名稱未提供";
}
function NumberValue({ value, digits = 2 }: { value: unknown; digits?: number }) {
  const numeric = (typeof value === "number" || (typeof value === "string" && value.trim())) ? Number(value) : NaN;
  return Number.isFinite(numeric)
    ? <span title={String(value)}>{new Intl.NumberFormat("zh-TW", { maximumFractionDigits: digits }).format(numeric)}</span>
    : <span className={styles.muted}>未提供</span>;
}
function Status({ value }: { value: string }) {
  const tone = ["DATA_BLOCKED", "INVALIDATED"].includes(value) ? "danger"
    : ["DATA_UNKNOWN", "WAITING_RESEARCH"].includes(value) ? "warning"
    : ["WAITING_PRICE", "WAITING_CONFIRMATION", "REVIEWABLE"].includes(value) ? "info" : "neutral";
  return <span className={styles.badge} data-tone={tone} title={value}>{states[value] ?? value}</span>;
}
function errorText(error: unknown) {
  if (isDeleted(error)) return "此提案已刪除，請從清單選擇其他提案。";
  return error instanceof ApiError ? `${error.code ? `${error.code}：` : ""}${error.message}`
    : error instanceof Error ? error.message : "讀取失敗";
}
function isDeleted(error: unknown) {
  return error instanceof ApiError && (error.code === "PROPOSAL_DELETED" || error.status === 410);
}
function Field({ label, children }: { label: string; children: ReactNode }) {
  return <div><dt>{label}</dt><dd>{children}</dd></div>;
}
function MathRead({ value }: { value: SetupEvaluation | null | undefined }) {
  return <dl className={styles.metrics}>
    <Field label="風險金額"><NumberValue value={value?.gross_risk} /></Field>
    <Field label="含成本停損情境"><NumberValue value={value?.net_stop_loss} /></Field>
    {[0, 1].map(index => <Field key={index} label={`目標 ${index + 1} 報酬風險比（毛／淨）`}>
      <NumberValue value={value?.target_scenarios?.[index]?.gross_rr} /> / <NumberValue value={value?.target_scenarios?.[index]?.net_rr} />
    </Field>)}
    <Field label="未知成本">{value?.missing_costs ? value.missing_costs.length ? <span title={value.missing_costs.join("、")}>{value.missing_costs.map(code => costLabels[code] ?? code).join("、")}</span> : "無額外缺項" : "未提供"}</Field>
    {value?.reason_codes?.length ? <Field label="計算限制">{value.reason_codes.join("、")}</Field> : null}
  </dl>;
}

export default function ResearchCandidates({ initialMarket, initialSelected, initialCutoff }: {
  initialMarket: ResearchMarket; initialSelected: string | null; initialCutoff: string;
}) {
  const [market, setMarket] = useState<ResearchMarket>(initialMarket);
  const [stocks, setStocks] = useState("");
  const [direction, setDirection] = useState<Direction>("both");
  const [basis, setBasis] = useState("");
  const [cutoff, setCutoff] = useState(initialCutoff);
  const [horizon, setHorizon] = useState<10 | 15>(10);
  const [list, setList] = useState<ProposalSummaryList | null>(null);
  const [listError, setListError] = useState("");
  const [result, setResult] = useState<NominationResult | null>(null);
  const [submitError, setSubmitError] = useState("");
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<string | null>(initialSelected);
  const [origin, setOrigin] = useState("");
  const [side, setSide] = useState("");
  const [page, setPage] = useState(0);
  const [reload, setReload] = useState(0);
  const reloadList = useCallback(() => { setList(null); setListError(""); setReload(n => n + 1); }, []);
  useEffect(() => {
    const controller = new AbortController();
    fetchJson<ProposalSummaryList>(API, { view: "summary", limit: 20, offset: page * 20, market, ...(origin ? { origin } : {}), ...(side ? { direction: side } : {}) }, { signal: controller.signal })
      .then(value => {
        if (controller.signal.aborted) return;
        if (value.projection !== "research.proposal_list.summary.v1" || value.items.some(item => item.market !== market)) throw new Error(MARKET_MISMATCH);
        setList(value); setListError("");
      })
      .catch(error => { if (!controller.signal.aborted) { setList(null); setListError(errorText(error)); } });
    return () => controller.abort();
  }, [page, reload, market, origin, side]);
  const visible = list?.items ?? [];
  const selectedId = listError ? null : selected ?? visible[0]?.creation_id ?? null;
  async function nominate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setSubmitError(""); setResult(null);
    const ids = stocks.trim().split(/[\s,，]+/).filter(Boolean);
    if (ids.length < 1 || ids.length > 5) { setSubmitError("請輸入 1～5 個股票代號。"); return; }
    setBusy(true);
    try {
      const response = await requestJson<NominationResult>(`${API}/nominations`, { method: "POST", body: JSON.stringify({
        market, stock_ids: ids, direction, as_of_trade_date: basis, requested_at: new Date(`${cutoff}:00+08:00`).toISOString(),
        horizon_sessions: horizon, nomination_origin: "USER_NOMINATION",
      }) });
      setResult(response);
      const saved = response.scenarios.find(row => row.proposal)?.proposal;
      if (saved) { setOrigin(""); setSide(""); setSelected(saved.proposal.creation_id); setPage(0); setReload(n => n + 1); }
    } catch (error) { setSubmitError(errorText(error)); } finally { setBusy(false); }
  }
  return <main className={styles.page}>
    <header className={styles.header}><div><Link href="/" prefetch={false}>返回 OMI 工作台</Link><h1>股票研究候選</h1>
      <p>比較盤後篩選與手動提名的研究方案，追蹤條件與資料限制。</p></div>
      <button type="button" disabled={busy} onClick={reloadList}>重新讀取清單</button></header>
    <section className={`${styles.panel} ${styles.nominationPanel}`} aria-label="指定股票研究">
      <details><summary>指定股票研究<span className={styles.summaryHint}>手動提名 1～5 檔</span></summary>
      <p className={styles.muted}>目前市場：{market === "US" ? "美股 · 僅限啟用中的觀察名單，日期使用紐約交易日" : "台股"}</p>
      <form onSubmit={nominate} className={styles.nomination}>
        <label>股票代號（1～5 檔）<input required value={stocks} onChange={e => setStocks(e.target.value)} placeholder={market === "US" ? "AAPL, MSFT, NVDA（須在觀察名單）" : "2337, 3481, 2891"} /></label>
        <label>方向<select value={direction} onChange={e => setDirection(e.target.value as Direction)}>
          <option value="both">多空都評估</option><option value="long">做多</option><option value="short">做空</option></select></label>
        <label>已完成日 K 截止日期<input required type="date" value={basis} onChange={e => setBasis(e.target.value)} /></label>
        <label>知識截止時間（台北）<input required type="datetime-local" value={cutoff} onChange={e => setCutoff(e.target.value)} /></label>
        <label>持有交易日<select value={horizon} onChange={e => setHorizon(Number(e.target.value) as 10 | 15)}><option value={10}>10 個交易日</option><option value={15}>15 個交易日</option></select></label>
        <button disabled={busy} className={styles.primary}>{busy ? "研究與保存中…" : "研究並保存"}</button>
      </form>
      {submitError && <p role="alert" className={styles.error}>{submitError}</p>}
      {result && <div className={styles.result} aria-live="polite"><p>本次提名：{show(states[result.status] ?? result.status)}。缺資料的項目不會補造價位。</p>
        {result.scenarios.map((row, index) => <p key={`${row.stock_id}-${row.direction}-${index}`}>
          <strong>{row.proposal ? `${stockName(row.proposal)}（${row.stock_id}）` : row.stock_id} · {row.direction === "long" ? "做多" : row.direction === "short" ? "做空" : row.direction}</strong>　{states[row.status] ?? row.status}　{row.reason_codes.join("、")}
          {row.proposal && <button type="button" onClick={() => setSelected(row.proposal!.proposal.creation_id)}>查看提案</button>}
        </p>)}<details><summary>本次資料覆蓋</summary><pre>{JSON.stringify(result.coverage, null, 2)}</pre></details></div>}
      </details>
    </section>
    <div className={styles.workspace}>
      <section className={styles.panel} aria-labelledby="list-title"><h2 id="list-title">已保存候選</h2>
        <div className={styles.toolbar}><label>市場<select disabled={busy} value={market} onChange={e => { setMarket(e.target.value as ResearchMarket); setList(null); setSelected(null); setPage(0); setResult(null); setSubmitError(""); }}>
          <option value="TW">台股</option><option value="US">美股</option></select></label>
          <label>來源<select disabled={busy} value={origin} onChange={e => { setOrigin(e.target.value); setList(null); setSelected(null); setPage(0); }}>
          <option value="">全部來源</option>{Object.entries(origins).map(([key, label]) => <option key={key} value={key}>{market === "US" && key === "OMI_SCREEN" ? "觀察名單掃描" : label}</option>)}</select></label>
          <label>篩選方向<select disabled={busy} value={side} onChange={e => { setSide(e.target.value); setList(null); setSelected(null); setPage(0); }}><option value="">多空</option><option value="long">做多</option><option value="short">做空</option></select></label></div>
        {listError ? <p role="alert" className={styles.error}>{listError}</p> : !list ? <p role="status">讀取候選中…</p> : <>
          <p className={styles.muted}>清單讀取：{time(list.as_of)}（台北）</p>
          {!visible.length ? <p>沒有符合條件的已保存提案。</p> : <ul className={styles.candidateList} aria-label="已保存研究候選">
            {visible.map(item => { return <li key={item.creation_id}>
              <button type="button" disabled={busy} className={styles.candidate} aria-pressed={selectedId === item.creation_id} onClick={() => setSelected(item.creation_id)}>
                <span className={styles.candidateHeading}><strong>{item.market === "US" ? item.symbol : item.stock_name ?? "名稱未提供"}</strong><span className={styles.direction} data-direction={item.direction === "long" ? 1 : -1}>{item.direction === "long" ? "做多" : "做空"}</span></span>
                <span className={styles.candidateMeta}>{item.symbol} · {originLabel(item.workflow_origin ?? undefined, item.market)} · v{item.revision}</span>
                <span className={styles.candidateFooter}><Status value={item.status} /><span>日線 {item.as_of_trade_date}</span></span>
                {item.assessment_status && item.assessment_status !== "qualified" && <span className={styles.assessment}>篩選評估：{states[item.assessment_status] ?? item.assessment_status}</span>}
              </button>
            </li>; })}</ul>}
          <div className={styles.toolbar}><button type="button" disabled={busy || page === 0} onClick={() => { setList(null); setSelected(null); setPage(n => n - 1); }}>上一頁</button>
            <span>第 {page + 1} 頁</span><button type="button" disabled={busy || !list.has_more} onClick={() => { setList(null); setSelected(null); setPage(n => n + 1); }}>下一頁</button></div>
        </>}
      </section>
      {selectedId ? <ProposalDetail key={`${market}:${selectedId}`} id={selectedId} market={market}
        onBusyChange={setBusy} onSaved={() => { setPage(0); reloadList(); }}
        onDeleted={() => { setSelected(null); if (visible.length === 1 && page > 0) setPage(page - 1); reloadList(); }} />
        : <section className={styles.panel}><h2>研究內容</h2><p>選取已保存提案，查看價位、證據、歷史與監控。</p></section>}
    </div>
  </main>;
}

function ProposalDetail({ id, market, onSaved, onDeleted, onBusyChange }: {
  id: string; market: ResearchMarket; onSaved: () => void; onDeleted: () => void; onBusyChange: (busy: boolean) => void;
}) {
  const [read, setRead] = useState<ProposalRead | null>(null);
  const [history, setHistory] = useState<RevisionList | null>(null);
  const [error, setError] = useState("");
  const [historyError, setHistoryError] = useState("");
  const [monitor, setMonitor] = useState<ResearchMonitor | null>(null);
  const [monitorError, setMonitorError] = useState("");
  const [monitorBusy, setMonitorBusy] = useState(false);
  const [poll, setPoll] = useState(false);
  const [monitorTick, setMonitorTick] = useState(0);
  const [reload, setReload] = useState(0);
  const [editing, setEditing] = useState(false);
  const [copyMessage, setCopyMessage] = useState("");
  const [promotion, setPromotion] = useState<ProposalPromotion | null>(null);
  const [promoting, setPromoting] = useState(false);
  const [promotionError, setPromotionError] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const deleteInFlight = useRef(false);
  function reloadDetail() {
    setRead(null); setHistory(null); setMonitor(null); setError(""); setHistoryError("");
    setPromotion(null); setPromotionError(""); setReload(n => n + 1);
    setConfirmDelete(false); setDeleteError("");
  }
  useEffect(() => {
    const controller = new AbortController();
    Promise.allSettled([
      fetchJson<ProposalRead>(`${API}/${id}`, undefined, { signal: controller.signal }),
      fetchJson<RevisionList>(`${API}/${id}/revisions`, undefined, { signal: controller.signal }),
    ]).then(([current, revisions]) => {
      if (controller.signal.aborted) return;
      const deleted = [current, revisions].find(result => result.status === "rejected"
        && isDeleted(result.reason));
      if (deleted?.status === "rejected") {
        setRead(null); setHistory(null); setError(errorText(deleted.reason)); return;
      }
      if ((current.status === "fulfilled" && current.value.proposal.market !== market)
          || (revisions.status === "fulfilled" && revisions.value.revisions.some(item => item.proposal.market !== market))) {
        setRead(null); setHistory(null); setError(MARKET_MISMATCH); return;
      }
      if (revisions.status === "fulfilled" && revisions.value.revisions.length) {
        setRead(revisions.value.revisions[revisions.value.revisions.length - 1]);
      } else if (current.status === "fulfilled") setRead(current.value); else setError(errorText(current.reason));
      if (revisions.status === "fulfilled") setHistory(revisions.value); else setHistoryError(errorText(revisions.reason));
    });
    return () => controller.abort();
  }, [id, market, reload]);
  const revision = read?.status === "scheduled" ? undefined : read?.proposal.revision_id;
  useEffect(() => {
    if (!revision) return;
    const controller = new AbortController(); let timer: ReturnType<typeof setTimeout> | undefined;
    const load = async () => {
      setMonitorBusy(true); setMonitorError("");
      try {
        const value = await fetchJson<ResearchMonitor>(`${API}/${id}/monitor`, undefined, { signal: controller.signal });
        if (!controller.signal.aborted) {
          if (value.revision_id !== revision) { setMonitor(null); setMonitorError("提案版本已變更，請重新讀取提案。"); }
          else setMonitor(value);
        }
      } catch (failure) { if (!controller.signal.aborted) { setMonitor(null); setMonitorError(errorText(failure)); } }
      finally { if (!controller.signal.aborted) { setMonitorBusy(false); if (poll) timer = setTimeout(load, 15000); } }
    };
    void load(); return () => { controller.abort(); if (timer) clearTimeout(timer); };
  }, [id, revision, poll, monitorTick]);
  if (error) return <section className={styles.panel}><p role="alert" className={styles.error}>{error}</p><button onClick={reloadDetail}>重試</button></section>;
  if (!read) return <section className={styles.panel}><p role="status">讀取提案與歷史中…</p></section>;
  const p = read.proposal; const source = snapshot(read); const zone = source.selected_zones?.[0];
  async function copy() {
    try { await navigator.clipboard.writeText(JSON.stringify({ proposal: read, monitor }, null, 2)); setCopyMessage("已複製 Backend 研究資料，可貼到 ChatGPT。"); }
    catch { setCopyMessage("複製失敗，可從下方證據區選取原始資料。"); }
  }
  async function promote() {
    setPromoting(true); setPromotion(null); setPromotionError("");
    try {
      setPromotion(await requestJson<ProposalPromotion>(`${API}/${p.creation_id}/promote`, {
        method: "POST", body: JSON.stringify({ expected_revision_id: p.revision_id, owner_id: "omi-research-ui" }),
      }));
    } catch (failure) { setPromotionError(errorText(failure)); }
    finally { setPromoting(false); }
  }
  async function move() {
    setDeleting(true); onBusyChange(true); setDeleteError("");
    try {
      await requestJson<ProposalRead>(`${API}/${p.creation_id}/move`, {
        method: "POST", body: JSON.stringify({ expected_revision_id: p.revision_id,
          origin: read?.workflow_origin === "AI_NOMINATION" ? "OMI_SCREEN" : "AI_NOMINATION" }),
      });
      reloadDetail(); onSaved();
    } catch (failure) { setDeleteError(errorText(failure)); }
    finally { setDeleting(false); onBusyChange(false); }
  }
  async function remove() {
    if (!confirmDelete || deleteInFlight.current || deleteError) return;
    deleteInFlight.current = true;
    setDeleting(true); onBusyChange(true); setPoll(false);
    try {
      const receipt = await requestJson<ProposalDeletion>(`${API}/${p.creation_id}`, {
        method: "DELETE", body: JSON.stringify({ expected_revision_id: p.revision_id }),
      });
      if (receipt.status !== "deleted" || receipt.creation_id !== p.creation_id || !receipt.deleted_at) {
        throw new Error("刪除結果無法確認");
      }
      onDeleted();
    } catch (failure) {
      setDeleteError(`${errorText(failure)} 請重新讀取提案，確認目前狀態後再操作。`);
    } finally {
      deleteInFlight.current = false; setDeleting(false); onBusyChange(false);
    }
  }
  return <section className={styles.panel} aria-labelledby="detail-title">
    <div className={styles.detailHeading}><div><h2 id="detail-title">{stockName(read)} {p.market !== "US" && <span className={styles.symbol}>{p.symbol}</span>}</h2>
      <div className={styles.identityMeta}><span className={styles.direction} data-direction={p.strategy.direction}>{p.strategy.direction === 1 ? "做多" : "做空"}</span>
        <Status value={read.status} /><span>第 {p.revision} 版 · {originLabel(read.workflow_origin ?? source.request?.nomination_origin, p.market)}</span></div></div>
      <div className={styles.actions}>
      <button disabled={deleting} onClick={reloadDetail}>重新讀取提案</button><button disabled={deleting || confirmDelete} onClick={() => setEditing(value => !value)}>{editing ? "關閉修改" : "修改提案"}</button>
      <button disabled={deleting || editing || confirmDelete} onClick={() => void move()}>{read.workflow_origin === "AI_NOMINATION" ? "移回盤後自動" : "移至 AI 提名"}</button>
      <button disabled={deleting || editing || promoting || Boolean(deleteError)} className={styles.deleteButton} onClick={() => setConfirmDelete(true)}>刪除提案</button></div>
    </div>
    {confirmDelete && <div className={styles.deleteConfirmation} role="group" aria-label="確認刪除提案">
      <p>刪除「{stockName(read)}」這筆提案？已採用的條件候選不會一併取消。</p>
      <div className={styles.toolbar}><button disabled={deleting || Boolean(deleteError)} className={styles.deleteButton} onClick={() => void remove()}>{deleting ? "刪除中…" : "確認刪除"}</button>
        <button disabled={deleting} onClick={() => setConfirmDelete(false)}>取消</button></div>
    </div>}
    {deleteError && <p role="alert" className={styles.error}>{deleteError}</p>}
    <p className={styles.thesis}>{p.strategy.thesis}</p>
    {source.assessment?.status && source.assessment.status !== "qualified" && <p className={styles.caveat}>篩選評估：{states[source.assessment.status] ?? source.assessment.status}</p>}
    <p className={styles.muted}>以下是已保存的研究價位，不代表已觸發或成交。價格與風險金額：{p.market === "US" ? "USD 美元" : "TWD 新臺幣"}。</p>
    <dl className={styles.prices} aria-label="已保存研究價位">
      <div data-kind="entry"><dt>進場價</dt><dd><NumberValue value={p.strategy.entry_price} digits={4} /></dd></div>
      <div data-kind="stop"><dt>停損價</dt><dd><NumberValue value={p.strategy.stop_price} digits={4} /></dd></div>
      {[0, 1].map(index => <div key={index}><dt>目標 {index + 1} · TP{index + 1}</dt><dd><NumberValue value={p.strategy.targets[index]?.price} digits={4} /></dd></div>)}
    </dl>
    <div className={styles.planSummary}>
      <span>進場帶：{zone ? <><NumberValue value={zone.lower_bound} digits={4} /> ～ <NumberValue value={zone.upper_bound} digits={4} /></> : "未提供"}</span>
      <span>股數：<NumberValue value={p.strategy.shares} digits={0} /></span>
      <span>{entryRules[p.strategy.entry_rule] ?? p.strategy.entry_rule}</span>
    </div>
    <h3>風險與報酬</h3><MathRead value={read.setup_evaluation} />
    <p className={styles.muted}>報酬風險比（R/R）顯示至小數點後 2 位；未知成本不會視為 0。完整精度保留於原始資料與修訂欄位。</p>
    <div className={styles.caveat}><strong>反證與資料限制</strong><p>{[...p.strategy.counter_evidence, ...(source.assessment?.reason_codes ?? [])].join("、") || "未提供"}</p></div>
    {source.discovery?.scope === "enabled_us_watchlist" ? <p className={styles.muted}>掃描涵蓋：美股觀察名單，非全市場。</p> : source.discovery && <p className={styles.muted}>掃描涵蓋：{source.discovery.sample_only === true || source.discovery.research_sample_only === true ? "僅樣本，非完整市場研究" : "請核對下方原始範圍"} · 品質 {show(source.discovery.coverage?.quality_status)}</p>}
    <details><summary>研究設定與資料依據<span className={styles.summaryHint}>日期、篩選評估、掃描範圍</span></summary>
      <dl className={styles.metrics}>
        <Field label="篩選評估">{states[source.assessment?.status ?? ""] ?? show(source.assessment?.status)}</Field>
        <Field label="日線基準／持有交易日">{p.evidence.as_of_trade_date} / {show(source.request?.horizon_sessions)}</Field>
        <Field label="有效起訖">{show(read.valid_from_date)} ～ {show(read.valid_until_date)}</Field>
        <Field label="知識截止（台北）">{time(p.evidence.cutoff)}</Field>
        <Field label="生效／紀錄時間（台北）">{time(p.effective_at)} / {time(p.recorded_at)}</Field>
        <Field label="研究模式">{p.strategy.mode === "confirmed" ? "完成日線確認" : p.strategy.mode === "aggressive" ? "觸價假設" : p.strategy.mode}</Field>
        <Field label="掃描範圍／品質">{source.discovery ? `sample_only=${show(source.discovery.sample_only)} / research_sample_only=${show(source.discovery.research_sample_only)} / ${show(source.discovery.coverage?.quality_status)}` : "未提供"}</Field>
      </dl>
    </details>
    {editing && <EditProposal key={p.revision_id} read={read} onSaved={() => { setEditing(false); reloadDetail(); onSaved(); }} />}
    <section className={styles.adoption} aria-label="採用研究方案">
    <div className={styles.toolbar}><button disabled={p.market === "US" || promoting || confirmDelete || deleting || read.status === "scheduled"} onClick={promote}>
      {promoting ? "保存候選中…" : "採用為條件候選"}</button><span>{p.market === "US" ? "美股僅供研究，尚未支援採用為條件候選。" : `採用目前 v${p.revision} 至 AGENT_SPACE；不代表可下單。`}</span></div>
    {p.market !== "US" && <p className={styles.muted}>候選僅以 TP1 作整筆停利；TP2 與原分段比例保留在來源備註，不啟用原生分段停利。未能映射的條件由 Backend 回報阻擋。</p>}
    {p.strategy.mode === "confirmed" && <p className={styles.muted}>Confirmed 研究監控沿用完成日線 F01 確認；現有條件候選尚不能映射此確認語意，採用時會保留 Backend 回報的限制。</p>}
    {promotionError && <p role="alert" className={styles.error}>{promotionError}</p>}
    {promotion?.revision_id === p.revision_id && <div role="status">
      <p>{promotion.status === "DATA_BLOCKED" ? "DATA_BLOCKED：請修改研究方案或補齊證據。" :
        promotion.candidate?.created ? "已保存條件候選。" : "此版本已有候選，保留既有候選及手動修改。"}</p>
      {promotion.candidate && <p>候選 {promotion.candidate.id} · v{promotion.candidate.revision} · {promotion.candidate.lifecycle}<br />
        候選阻擋原因：{promotion.candidate.validation_reasons.join("、") || "Backend 未回報"}</p>}
      <p>{[...promotion.reason_codes, ...promotion.warnings].join("、")}</p>
    </div>}
    </section>
    <section className={styles.monitor} aria-labelledby="monitor-title"><div className={styles.toolbar}><h3 id="monitor-title">當前研究監控</h3>
      <button disabled={monitorBusy || read.status === "scheduled"} onClick={() => setMonitorTick(n => n + 1)}>{monitorBusy ? "讀取中…" : "讀取監控"}</button>
      <label className={styles.check}><input type="checkbox" checked={poll} onChange={e => setPoll(e.target.checked)} />每 15 秒讀取</label></div>
      {monitorError && <p role="alert" className={styles.error}>{monitorError}</p>}
      {!monitor ? <p>{read.status === "scheduled" ? "此版本尚未生效；生效後可讀取該版本監控。" : monitorBusy ? "讀取監控證據中…" : "尚無監控結果"}</p> : <>
        {p.market === "US" && <p className={styles.muted}>美股監控依最新已完成日線收盤評估，不代表盤中觸發。</p>}
        <p className={styles.status}><Status value={monitor.status} /> <span className={styles.muted}>研究用途</span></p>
        <dl className={styles.metrics}><Field label="最後檢查（台北）">{time(monitor.checked_at)}</Field>
          <Field label="報價日期／時間">{show(monitor.quote.trade_date)} / {time(monitor.quote.quote_time)}</Field>
          <Field label="當前證據價格"><NumberValue value={monitor.quote.evidence?.value} digits={4} /></Field>
          <Field label="價格語意／時效">{show(monitor.quote.price_semantics)} / {show(monitor.quote.freshness?.status)}</Field>
          <Field label="報價來源">{show(monitor.quote.source)}</Field>
          <Field label="價位條件／確認">{monitor.price_condition} / {monitor.confirmation}（{monitor.confirmation_basis}）</Field></dl>
        <p className={styles.caveat}>判定原因／資料限制：{monitor.reason_codes.length ? monitor.reason_codes.join("、") : "Backend 未回報額外限制"}</p>
        {!!monitor.setup_evaluation?.missing_costs?.length && <p className={styles.caveat}>當前情境未知成本：{monitor.setup_evaluation.missing_costs.map(code => costLabels[code] ?? code).join("、")}</p>}
        {!!monitor.setup_evaluation?.reason_codes?.length && <p className={styles.caveat}>當前情境計算限制：{monitor.setup_evaluation.reason_codes.join("、")}</p>}
        <details><summary>當前情境報酬風險比（R/R）</summary><MathRead value={monitor.setup_evaluation} /></details>
        <details><summary>當前事件／資格與監控限制</summary><pre>{JSON.stringify({ eligibility: monitor.eligibility, limitations: monitor.limitations }, null, 2)}</pre></details>
      </>}
    </section>
    <h3>版本歷史</h3>{historyError && <p role="alert" className={styles.error}>{historyError}</p>}
    {history ? history.revisions.map(item => <details key={item.proposal.revision_id}>
      <summary>v{item.proposal.revision} · {time(item.proposal.recorded_at)} · {item.proposal.change_reason}</summary>
      <p>進場價 {show(item.proposal.strategy.entry_price)} / 停損價 {show(item.proposal.strategy.stop_price)} / 目標價 {item.proposal.strategy.targets.map(t => show(t.price)).join(" / ")}</p>
      <MathRead value={item.setup_evaluation} /><pre>{JSON.stringify(item, null, 2)}</pre></details>) : <p>歷史尚未讀取</p>}
    <div className={styles.toolbar}><button onClick={copy}>複製研究資料給 ChatGPT</button><a href={buildDashboardHref(p.market === "US" ? { market: "us", symbol: p.symbol } : { market: "tw", stockId: p.symbol })}>開啟既有個股圖表</a>
      <a href={`/research?market=${p.market ?? "TW"}&proposal_id=${encodeURIComponent(id)}`}>此提案連結</a></div>
    {copyMessage && <p role="status">{copyMessage}</p>}
    <details><summary>已保存證據／來源與原始資料</summary><pre>{JSON.stringify(read, null, 2)}</pre></details>
  </section>;
}

function EditProposal({ read, onSaved }: { read: ProposalRead; onSaved: () => void }) {
  const p = read.proposal; const s = p.strategy;
  const [entry, setEntry] = useState(String(s.entry_price)); const [stop, setStop] = useState(String(s.stop_price));
  const [tp1, setTp1] = useState(String(s.targets[0]?.price ?? "")); const [tp2, setTp2] = useState(String(s.targets[1]?.price ?? ""));
  const [fraction1, setFraction1] = useState(String(s.targets[0]?.fraction ?? "")); const [fraction2, setFraction2] = useState(String(s.targets[1]?.fraction ?? ""));
  const [quantity, setQuantity] = useState(String(s.shares)); const [thesis, setThesis] = useState(s.thesis);
  const [mode, setMode] = useState(s.mode); const [rule, setRule] = useState(s.entry_rule);
  const [reason, setReason] = useState(""); const [effective, setEffective] = useState("");
  const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError(""); setBusy(true);
    try {
      const targets = [{ price: Number(tp1), fraction: Number(fraction1) }];
      if (tp2) targets.push({ price: Number(tp2), fraction: Number(fraction2) });
      targets.push(...s.targets.slice(2));
      await requestJson<ProposalRead>(`${API}/${p.creation_id}/revisions`, { method: "POST", body: JSON.stringify({
        expected_revision_id: p.revision_id, strategy: { ...s, entry_price: Number(entry), stop_price: Number(stop),
          targets, shares: Number(quantity), thesis, mode, entry_rule: rule }, costs: p.costs, change_reason: reason,
        ...(effective ? { effective_at: new Date(`${effective}:00+08:00`).toISOString() } : {}),
      }) }); onSaved();
    } catch (failure) { setError(errorText(failure)); } finally { setBusy(false); }
  }
  return <form onSubmit={save} className={styles.editor}><h3>修訂 v{p.revision}，保留歷史</h3><div className={styles.editGrid}>
    <label>Entry<input required type="number" step="any" value={entry} onChange={e => setEntry(e.target.value)} /></label>
    <label>Stop<input required type="number" step="any" value={stop} onChange={e => setStop(e.target.value)} /></label>
    <label>TP1<input required type="number" step="any" value={tp1} onChange={e => setTp1(e.target.value)} /></label>
    <label>TP1 比例（0～1）<input required type="number" step="any" value={fraction1} onChange={e => setFraction1(e.target.value)} /></label>
    <label>TP2（可留空）<input type="number" step="any" value={tp2} onChange={e => setTp2(e.target.value)} /></label>
    <label>TP2 比例（0～1）<input required={Boolean(tp2)} type="number" step="any" value={fraction2} onChange={e => setFraction2(e.target.value)} /></label>
    <label>股數<input required type="number" step="1" value={quantity} onChange={e => setQuantity(e.target.value)} /></label>
    <label>研究模式<select value={mode} onChange={e => setMode(e.target.value as typeof mode)}><option value="aggressive">aggressive · 觸價假設</option>{p.market !== "US" && <option value="confirmed">confirmed · 完成日線確認</option>}</select></label>
    <label>觸價規則<select value={rule} onChange={e => setRule(e.target.value as typeof rule)}><option value="at_or_below">at_or_below</option><option value="at_or_above">at_or_above</option><option value="next_open">next_open（目前監控不支援）</option></select></label>
    <label>生效時間（台北，可留空）<input type="datetime-local" value={effective} onChange={e => setEffective(e.target.value)} /></label>
  </div><label>研究假設<textarea required value={thesis} onChange={e => setThesis(e.target.value)} /></label>
    <label>修改原因<input required value={reason} onChange={e => setReason(e.target.value)} /></label>
    <p className={styles.muted}>費用沿用目前版本；有效交易日起迄由原 Journal 依生效時間計算，保存後顯示。</p>
    {error && <p role="alert" className={styles.error}>{error}</p>}<button disabled={busy} className={styles.primary}>{busy ? "保存中…" : "保存新版本"}</button>
  </form>;
}
