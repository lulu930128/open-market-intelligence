"use client";

import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import { ApiError, fetchJson, requestJson } from "@/lib/api";
import type { Direction, NominationResult, NominationSnapshot, ProposalList, ProposalPromotion, ProposalRead,
  ResearchMonitor, RevisionList, SetupEvaluation } from "@/types/researchTrade";
import styles from "./ResearchCandidates.module.css";

const API = "/api/research/trade-proposals";
const origins: Record<string, string> = { USER_NOMINATION: "人工提名", AI_NOMINATION: "AI 提名", OMI_SCREEN: "盤後自動" };
const states: Record<string, string> = { WAITING_PRICE: "等待價格", WAITING_CONFIRMATION: "等待確認",
  DATA_UNKNOWN: "資料未知", DATA_BLOCKED: "資料阻擋", WAITING_RESEARCH: "等待研究",
  REVIEWABLE: "研究可評估", INVALIDATED: "已失效", EXPIRED: "已到期", proposed: "已保存", scheduled: "尚未生效" };
const show = (value: unknown) => value === null || value === undefined || value === "" ? "missing" : String(value);
function time(value?: string | null) {
  if (!value) return "missing";
  if (value.length === 10) return value;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : new Intl.DateTimeFormat("zh-TW", {
    timeZone: "Asia/Taipei", dateStyle: "short", timeStyle: "medium", hour12: false,
  }).format(parsed);
}
function snapshot(read: ProposalRead): NominationSnapshot {
  const item = read.proposal.evidence.items.find(item => item.source_ref === "research.stock_nomination.v1");
  try { return item ? JSON.parse(item.snapshot_json) as NominationSnapshot : {}; } catch { return {}; }
}
function errorText(error: unknown) {
  return error instanceof ApiError ? `${error.code ? `${error.code}：` : ""}${error.message}`
    : error instanceof Error ? error.message : "讀取失敗";
}
function Field({ label, children }: { label: string; children: ReactNode }) {
  return <div><dt>{label}</dt><dd>{children}</dd></div>;
}
function MathRead({ value }: { value: SetupEvaluation | null | undefined }) {
  return <dl className={styles.metrics}>
    <Field label="風險金額">{show(value?.gross_risk)}</Field>
    <Field label="淨停損情境">{show(value?.net_stop_loss)}</Field>
    {[0, 1].map(index => <Field key={index} label={`TP${index + 1} 毛 / 淨 R/R`}>
      {show(value?.target_scenarios?.[index]?.gross_rr)} / {show(value?.target_scenarios?.[index]?.net_rr)}
    </Field>)}
    <Field label="未知成本">{value?.missing_costs ? value.missing_costs.length ? value.missing_costs.join("、") : "無額外缺項" : "missing"}</Field>
    {value?.reason_codes?.length ? <Field label="計算限制">{value.reason_codes.join("、")}</Field> : null}
  </dl>;
}

export default function ResearchCandidates() {
  const [stocks, setStocks] = useState("");
  const [direction, setDirection] = useState<Direction>("both");
  const [basis, setBasis] = useState("");
  const [cutoff, setCutoff] = useState("");
  const [horizon, setHorizon] = useState<10 | 15>(10);
  const [list, setList] = useState<ProposalList | null>(null);
  const [listError, setListError] = useState("");
  const [result, setResult] = useState<NominationResult | null>(null);
  const [submitError, setSubmitError] = useState("");
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [origin, setOrigin] = useState("");
  const [side, setSide] = useState("");
  const [page, setPage] = useState(0);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    setCutoff(new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Taipei", year: "numeric", month: "2-digit",
      day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date()).replace(" ", "T"));
    setSelected(new URLSearchParams(window.location.search).get("proposal_id"));
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setList(null); setListError("");
    fetchJson<ProposalList>(API, { limit: 20, offset: page * 20 }, { signal: controller.signal })
      .then(value => { if (!controller.signal.aborted) setList(value); })
      .catch(error => { if (!controller.signal.aborted) setListError(errorText(error)); });
    return () => controller.abort();
  }, [page, reload]);
  const visible = useMemo(() => (list?.items ?? []).filter(item => {
    const source = snapshot(item).request?.nomination_origin;
    return (!origin || source === origin) && (!side || (item.proposal.strategy.direction === 1 ? "long" : "short") === side);
  }), [list, origin, side]);
  useEffect(() => { if (!selected && visible.length) setSelected(visible[0].proposal.creation_id); }, [selected, visible]);
  async function nominate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setSubmitError(""); setResult(null);
    const ids = stocks.trim().split(/[\s,，]+/).filter(Boolean);
    if (ids.length < 1 || ids.length > 5) { setSubmitError("請輸入 1～5 個股票代號。"); return; }
    setBusy(true);
    try {
      const response = await requestJson<NominationResult>(`${API}/nominations`, { method: "POST", body: JSON.stringify({
        stock_ids: ids, direction, as_of_trade_date: basis, requested_at: new Date(`${cutoff}:00+08:00`).toISOString(),
        horizon_sessions: horizon, nomination_origin: "USER_NOMINATION",
      }) });
      setResult(response);
      const saved = response.scenarios.find(row => row.proposal)?.proposal;
      if (saved) { setOrigin(""); setSide(""); setSelected(saved.proposal.creation_id); setPage(0); setReload(n => n + 1); }
    } catch (error) { setSubmitError(errorText(error)); } finally { setBusy(false); }
  }
  return <main className={styles.page}>
    <header className={styles.header}><div><a href="/">返回 OMI 工作台</a><h1>台股研究候選</h1>
      <p>提名、比較與修訂條件式研究方案。研究可評估不代表已下單。</p></div>
      <button type="button" onClick={() => setReload(n => n + 1)}>重新讀取清單</button></header>
    <section className={styles.panel} aria-labelledby="nominate-title"><h2 id="nominate-title">指定股票研究</h2>
      <form onSubmit={nominate} className={styles.nomination}>
        <label>股票代號（1～5 檔）<input required value={stocks} onChange={e => setStocks(e.target.value)} placeholder="2337, 3481, 2891" /></label>
        <label>方向<select value={direction} onChange={e => setDirection(e.target.value as Direction)}>
          <option value="both">多空都評估</option><option value="long">做多</option><option value="short">做空</option></select></label>
        <label>已完成日 K 截止日期<input required type="date" value={basis} onChange={e => setBasis(e.target.value)} /></label>
        <label>知識截止時間（台北）<input required type="datetime-local" value={cutoff} onChange={e => setCutoff(e.target.value)} /></label>
        <label>持有交易日<select value={horizon} onChange={e => setHorizon(Number(e.target.value) as 10 | 15)}><option value={10}>10 sessions</option><option value={15}>15 sessions</option></select></label>
        <button disabled={busy} className={styles.primary}>{busy ? "研究與保存中…" : "研究並保存"}</button>
      </form>
      {submitError && <p role="alert" className={styles.error}>{submitError}</p>}
      {result && <div className={styles.result} aria-live="polite"><p>本次提名：{show(states[result.status] ?? result.status)}。缺資料的項目不會補造價位。</p>
        {result.scenarios.map((row, index) => <p key={`${row.stock_id}-${row.direction}-${index}`}>
          <strong>{row.stock_id} · {row.direction}</strong>　{states[row.status] ?? row.status}　{row.reason_codes.join("、")}
          {row.proposal && <button type="button" onClick={() => setSelected(row.proposal!.proposal.creation_id)}>查看提案</button>}
        </p>)}<details><summary>本次 coverage</summary><pre>{JSON.stringify(result.coverage, null, 2)}</pre></details></div>}
    </section>
    <div className={styles.workspace}>
      <section className={styles.panel} aria-labelledby="list-title"><h2 id="list-title">已保存候選</h2>
        <div className={styles.toolbar}><label>本頁來源<select value={origin} onChange={e => { setOrigin(e.target.value); setSelected(null); }}>
          <option value="">全部來源</option>{Object.entries(origins).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
          <label>本頁方向<select value={side} onChange={e => { setSide(e.target.value); setSelected(null); }}><option value="">多空</option><option value="long">做多</option><option value="short">做空</option></select></label></div>
        {listError ? <p role="alert" className={styles.error}>{listError}</p> : !list ? <p role="status">讀取候選中…</p> : <>
          <p className={styles.muted}>清單讀取：{time(list.as_of)}（台北）</p>
          {!visible.length ? <p>本頁沒有符合條件的已保存提案。</p> : <div className={styles.tableScroll}><table><thead><tr><th>股票／方向</th><th>來源／basis</th><th>價位／版本</th></tr></thead>
            <tbody>{visible.map(item => { const p = item.proposal; const source = snapshot(item); return <tr key={p.creation_id} data-selected={selected === p.creation_id}>
              <td><button type="button" aria-pressed={selected === p.creation_id} onClick={() => setSelected(p.creation_id)}>{p.symbol} · {p.strategy.direction === 1 ? "多" : "空"}</button>
                <small>{states[item.status] ?? item.status}</small></td>
              <td>{origins[source.request?.nomination_origin ?? ""] ?? "missing"}<small>{p.evidence.as_of_trade_date}</small><small>{show(source.assessment?.status)}</small></td>
              <td>{show(p.strategy.entry_price)} / {show(p.strategy.stop_price)}<small>v{p.revision} · TP {p.strategy.targets.map(t => show(t.price)).join(" / ")}</small>
                <small>TP1 毛／淨 R/R：{show(item.setup_evaluation?.target_scenarios?.[0]?.gross_rr)} / {show(item.setup_evaluation?.target_scenarios?.[0]?.net_rr)}</small></td>
            </tr>; })}</tbody></table></div>}
          <div className={styles.toolbar}><button type="button" disabled={page === 0} onClick={() => { setList(null); setSelected(null); setPage(n => n - 1); }}>上一頁</button>
            <span>第 {page + 1} 頁</span><button type="button" disabled={!list.has_more} onClick={() => { setList(null); setSelected(null); setPage(n => n + 1); }}>下一頁</button></div>
        </>}
      </section>
      {selected ? <ProposalDetail key={selected} id={selected} onSaved={() => { setPage(0); setReload(n => n + 1); }} />
        : <section className={styles.panel}><h2>研究內容</h2><p>選取已保存提案，查看價位、證據、歷史與監控。</p></section>}
    </div>
  </main>;
}

function ProposalDetail({ id, onSaved }: { id: string; onSaved: () => void }) {
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
  useEffect(() => {
    const controller = new AbortController(); setRead(null); setHistory(null); setMonitor(null); setError(""); setHistoryError("");
    setPromotion(null); setPromotionError("");
    Promise.allSettled([
      fetchJson<ProposalRead>(`${API}/${id}`, undefined, { signal: controller.signal }),
      fetchJson<RevisionList>(`${API}/${id}/revisions`, undefined, { signal: controller.signal }),
    ]).then(([current, revisions]) => {
      if (controller.signal.aborted) return;
      if (revisions.status === "fulfilled" && revisions.value.revisions.length) {
        setRead(revisions.value.revisions[revisions.value.revisions.length - 1]);
      } else if (current.status === "fulfilled") setRead(current.value); else setError(errorText(current.reason));
      if (revisions.status === "fulfilled") setHistory(revisions.value); else setHistoryError(errorText(revisions.reason));
    });
    return () => controller.abort();
  }, [id, reload]);
  const revision = read?.status === "scheduled" ? undefined : read?.proposal.revision_id;
  useEffect(() => {
    if (!revision) { setMonitor(null); return; }
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
  if (error) return <section className={styles.panel}><p role="alert" className={styles.error}>{error}</p><button onClick={() => setReload(n => n + 1)}>重試</button></section>;
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
  return <section className={styles.panel} aria-labelledby="detail-title">
    <div className={styles.toolbar}><h2 id="detail-title">{p.symbol} · {p.strategy.direction === 1 ? "做多" : "做空"} · v{p.revision}</h2>
      <button onClick={() => setReload(n => n + 1)}>重新讀取提案</button><button onClick={() => setEditing(value => !value)}>{editing ? "關閉修改" : "修改提案"}</button></div>
    <p>{p.strategy.thesis}</p><p className={styles.muted}>研究假設與當前監控分開呈現；以下保存價位不代表已觸發或成交。</p>
    <div className={styles.toolbar}><button disabled={promoting || read.status === "scheduled"} onClick={promote}>
      {promoting ? "保存候選中…" : "採用為條件候選"}</button><span>採用目前 v{p.revision} 至 AGENT_SPACE；不代表可下單。</span></div>
    <p className={styles.muted}>候選僅以 TP1 作整筆停利；TP2 與原分段比例保留在來源備註，不啟用原生分段停利。未能映射的條件由 Backend 回報阻擋。</p>
    {p.strategy.mode === "confirmed" && <p className={styles.muted}>Confirmed 研究監控沿用完成日線 F01 確認；現有條件候選尚不能映射此確認語意，採用時會保留 Backend 回報的限制。</p>}
    {promotionError && <p role="alert" className={styles.error}>{promotionError}</p>}
    {promotion?.revision_id === p.revision_id && <div role="status">
      <p>{promotion.status === "DATA_BLOCKED" ? "DATA_BLOCKED：請修改研究方案或補齊證據。" :
        promotion.candidate?.created ? "已保存條件候選。" : "此版本已有候選，保留既有候選及手動修改。"}</p>
      {promotion.candidate && <p>候選 {promotion.candidate.id} · v{promotion.candidate.revision} · {promotion.candidate.lifecycle}<br />
        候選阻擋原因：{promotion.candidate.validation_reasons.join("、") || "Backend 未回報"}</p>}
      <p>{[...promotion.reason_codes, ...promotion.warnings].join("、")}</p>
    </div>}
    <dl className={styles.metrics}>
      <Field label="候選來源">{origins[source.request?.nomination_origin ?? ""] ?? "missing"}</Field>
      <Field label="資料品質">{show(source.assessment?.status)}</Field>
      <Field label="Basis / sessions">{p.evidence.as_of_trade_date} / {show(source.request?.horizon_sessions)}</Field>
      <Field label="知識截止（台北）">{time(p.evidence.cutoff)}</Field>
      <Field label="有效起訖">{show(read.valid_from_date)} ～ {show(read.valid_until_date)}</Field>
      <Field label="生效／紀錄時間（台北）">{time(p.effective_at)} / {time(p.recorded_at)}</Field>
      <Field label="進場帶">{zone ? `${show(zone.lower_bound)} ～ ${show(zone.upper_bound)}` : "missing"}</Field>
      <Field label="Entry / Stop">{show(p.strategy.entry_price)} / {show(p.strategy.stop_price)}</Field>
      <Field label="TP1 / TP2">{show(p.strategy.targets[0]?.price)} / {show(p.strategy.targets[1]?.price)}</Field>
      <Field label="股數／觸價規則">{p.strategy.shares} / {p.strategy.entry_rule}</Field>
      <Field label="研究模式">{p.strategy.mode}</Field>
      <Field label="掃描範圍／品質">{source.discovery ? `sample_only=${show(source.discovery.sample_only)} / research_sample_only=${show(source.discovery.research_sample_only)} / ${show(source.discovery.coverage?.quality_status)}` : "missing"}</Field>
    </dl>
    <h3>已保存方案 R/R</h3><MathRead value={read.setup_evaluation} />
    <p>反證／資料限制：{[...p.strategy.counter_evidence, ...(source.assessment?.reason_codes ?? [])].join("、") || "missing"}</p>
    {editing && <EditProposal key={p.revision_id} read={read} onSaved={() => { setEditing(false); setReload(n => n + 1); onSaved(); }} />}
    <section className={styles.monitor} aria-labelledby="monitor-title"><div className={styles.toolbar}><h3 id="monitor-title">當前研究監控</h3>
      <button disabled={monitorBusy || read.status === "scheduled"} onClick={() => setMonitorTick(n => n + 1)}>{monitorBusy ? "讀取中…" : "讀取監控"}</button>
      <label className={styles.check}><input type="checkbox" checked={poll} onChange={e => setPoll(e.target.checked)} />每 15 秒讀取</label></div>
      {monitorError && <p role="alert" className={styles.error}>{monitorError}</p>}
      {!monitor ? <p>{read.status === "scheduled" ? "此版本尚未生效；生效後可讀取該版本監控。" : monitorBusy ? "讀取監控證據中…" : "missing：尚無監控結果"}</p> : <>
        <p className={styles.status}>{states[monitor.status] ?? monitor.status} · 研究用途</p>
        <dl className={styles.metrics}><Field label="最後檢查（台北）">{time(monitor.checked_at)}</Field>
          <Field label="Quote date / time">{show(monitor.quote.trade_date)} / {time(monitor.quote.quote_time)}</Field>
          <Field label="當前證據價格">{show(monitor.quote.evidence?.value)}</Field>
          <Field label="價格語意／freshness">{show(monitor.quote.price_semantics)} / {show(monitor.quote.freshness?.status)}</Field>
          <Field label="Quote 來源">{show(monitor.quote.source)}</Field>
          <Field label="價位條件／確認">{monitor.price_condition} / {monitor.confirmation}（{monitor.confirmation_basis}）</Field></dl>
        <p>判定原因／資料限制：{monitor.reason_codes.length ? monitor.reason_codes.join("、") : "Backend 未回報額外限制"}</p>
        <h3>當前情境 R/R</h3><MathRead value={monitor.setup_evaluation} />
        <details><summary>當前事件／資格與監控限制</summary><pre>{JSON.stringify({ eligibility: monitor.eligibility, limitations: monitor.limitations }, null, 2)}</pre></details>
      </>}
    </section>
    <h3>版本歷史</h3>{historyError && <p role="alert" className={styles.error}>{historyError}</p>}
    {history ? history.revisions.map(item => <details key={item.proposal.revision_id}>
      <summary>v{item.proposal.revision} · {time(item.proposal.recorded_at)} · {item.proposal.change_reason}</summary>
      <p>Entry {show(item.proposal.strategy.entry_price)} / Stop {show(item.proposal.strategy.stop_price)} / TP {item.proposal.strategy.targets.map(t => show(t.price)).join(" / ")}</p>
      <MathRead value={item.setup_evaluation} /><pre>{JSON.stringify(item, null, 2)}</pre></details>) : <p>missing：歷史尚未讀取</p>}
    <div className={styles.toolbar}><button onClick={copy}>複製研究資料給 ChatGPT</button><a href={`/?stock_id=${encodeURIComponent(p.symbol)}`}>開啟既有個股圖表</a>
      <a href={`/research?proposal_id=${encodeURIComponent(id)}`}>此提案連結</a></div>
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
    <label>研究模式<select value={mode} onChange={e => setMode(e.target.value as typeof mode)}><option value="aggressive">aggressive · 觸價假設</option><option value="confirmed">confirmed · 完成日線確認</option></select></label>
    <label>觸價規則<select value={rule} onChange={e => setRule(e.target.value as typeof rule)}><option value="at_or_below">at_or_below</option><option value="at_or_above">at_or_above</option><option value="next_open">next_open（目前監控不支援）</option></select></label>
    <label>生效時間（台北，可留空）<input type="datetime-local" value={effective} onChange={e => setEffective(e.target.value)} /></label>
  </div><label>研究假設<textarea required value={thesis} onChange={e => setThesis(e.target.value)} /></label>
    <label>修改原因<input required value={reason} onChange={e => setReason(e.target.value)} /></label>
    <p className={styles.muted}>費用沿用目前版本；有效交易日起迄由原 Journal 依生效時間計算，保存後顯示。</p>
    {error && <p role="alert" className={styles.error}>{error}</p>}<button disabled={busy} className={styles.primary}>{busy ? "保存中…" : "保存新版本"}</button>
  </form>;
}
