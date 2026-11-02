"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import type { DeskCommand, DeskSnapshot, Order, Review, Rules, Space, Strategy } from "@/lib/order-desk/contract";
import { commandDesk, openDemo, readDesk } from "@/lib/order-desk/transport";
import styles from "./OrderDesk.module.css";

const spaceName = (space: Space) => space === "USER_SPACE" ? "使用者" : "Agent";
const stepName: Record<string, string> = {
  entry_60: "注入 Entry 成交 60 / 100", stop_cancel40_exit60: "注入 480 停損：撤餘 40、退出 60",
  exit_60: "注入 Exit 成交 60", late_entry_15: "注入晚到 Entry 成交 15",
  exit_15: "注入補充 Exit 成交 15", cancel_final: "注入最終撤單與相符證據",
};
type Send = (command: DeskCommand) => Promise<void>;

function Badge({ children, warning = false }: { children: React.ReactNode; warning?: boolean }) {
  return <span className={warning ? styles.warningBadge : styles.badge}>{children}</span>;
}

function ReviewForm({ review, send, blocked }: { review: Review; send: Send; blocked: boolean }) {
  const command = review.draft.command;
  const [quantity, setQuantity] = useState(String(command.quantity));
  const [price, setPrice] = useState(command.price);
  const editable = review.state === "DRAFT" || review.state === "PREVIEW";
  const changed = quantity !== String(command.quantity) || price !== command.price;
  const selector = { review_id: review.review_id, expected_revision: review.review_revision };
  return <div className={styles.reviewActions}>
    <form onSubmit={event => {
      event.preventDefault();
      void send({ type: "revise", ...selector, draft: { ...review.draft,
        command: { ...command, quantity: Number(quantity), price } } });
    }}>
      <fieldset disabled={blocked || !editable}>
        <legend>修訂委託</legend>
        <div className={styles.formGrid}>
          <label>股數<input name="quantity" type="number" min="1" step="1" required value={quantity} onChange={e => setQuantity(e.target.value)} /></label>
          <label>限價<input name="price" type="text" inputMode="decimal" required value={price} onChange={e => setPrice(e.target.value)} /></label>
        </div>
        <button type="submit" disabled={!changed}>儲存修訂，重新預審</button>
      </fieldset>
    </form>
    {editable && <p className={styles.hint}>修改後須先儲存並取得新 Preview，再核對完整單據。尚未確認的提案不會送到 fake broker。</p>}
    <div className={styles.actions}>
      <button className={styles.primary} disabled={blocked || changed || review.state !== "PREVIEW" || !review.snapshot}
        onClick={() => review.snapshot && void send({ type: "confirm", ...selector, expected_digest: review.snapshot.digest })}>確認此版本</button>
      <button disabled={blocked || !editable} onClick={() => void send({ type: "reject", ...selector, reason: "USER_REJECTED" })}>拒絕提案</button>
      {review.state === "DRAFT" && <button disabled={blocked || changed} onClick={() => void send({ type: "preview", ...selector })}>取得 Preview</button>}
    </div>
    {review.state === "DRAFT" && <p className={styles.notice}>此版本尚無 Preview，確認已停用。</p>}
    {review.state === "EXECUTION" && <p className={styles.notice}>已核定的委託快照固定；實際成交與撤單以右側 Broker 證據為準。</p>}
    {review.state === "REJECTED" && <p className={styles.notice}>已拒絕，未建立 execution。請從其他提案繼續。</p>}
  </div>;
}

function StrategyForm({ strategy, review, send, blocked }: { strategy?: Strategy; review: Review; send: Send; blocked: boolean }) {
  const [stop, setStop] = useState(strategy?.rules.stop_loss ?? "480");
  const [take, setTake] = useState(strategy?.rules.take_profit ?? "550");
  const [exitPrice, setExitPrice] = useState(strategy?.rules.exit_limit_price ?? "480");
  const rules: Rules = { stop_loss: stop || null, take_profit: take || null, exit_limit_price: exitPrice, protection_mode: "LOCAL_SYNTHETIC" };
  const eligible = review.state === "EXECUTION" && !!review.draft.command.strategy_id;
  return <section className={styles.strategy} aria-label="已核定策略">
    <div className={styles.sectionHeading}><h3>策略保護</h3><Badge warning>LOCAL_SYNTHETIC</Badge></div>
    <p className={styles.hint}>本機策略觀察價格後產生限價退出。券商原生停損未支援；本示範沒有持續行情，限價不保證成交。</p>
    {strategy ? <>
      <div className={styles.sectionHeading}><strong data-testid="strategy-state">{strategy.state}</strong><span>策略 revision {strategy.strategy_revision}</span></div>
      <dl className={styles.metrics}>
        <div><dt>Entry 已成交</dt><dd data-testid="entry-filled">{strategy.entry_filled}</dd></div>
        <div><dt>Entry 剩餘</dt><dd data-testid="entry-remaining">{strategy.entry_remaining ?? "UNKNOWN"}</dd></div>
        <div><dt>有效部位</dt><dd data-testid="effective-position">{strategy.effective_position}</dd></div>
        <div><dt>Exit 已成交</dt><dd data-testid="exit-filled">{strategy.exit_filled}</dd></div>
        <div><dt>退出保留量</dt><dd data-testid="reserved-exit">{strategy.reserved_exit_quantity}</dd></div>
        <div><dt>目標部位</dt><dd>{strategy.target_position ?? "尚未退出"}</dd></div>
      </dl>
      <p className={styles.hint}>保護參考量 {strategy.protected_quantity} 股，來自實際 fills。這是策略 lineage，並非切分真實帳戶持股。</p>
      <p className={styles.notice}>reconcile_required={String(strategy.reconcile_required)} · fill_history_complete={String(strategy.fill_history_complete)}</p>
      {strategy.unresolved_exit_claims.length > 0 && <p role="alert">未解 Exit claims：{strategy.unresolved_exit_claims.join("、")}</p>}
      {strategy.strategy_error && <p role="alert">策略錯誤：{strategy.strategy_error}</p>}
      <details><summary>策略來源與 consent</summary><p>{strategy.consent_policy}</p><p>{strategy.source_snapshot.source_id} · {strategy.source_snapshot.observed_at}</p><code>{strategy.source_snapshot.digest}</code><p>{strategy.price_input}</p></details>
    </> : <p className={styles.notice}>{eligible ? "委託已確認，尚未設定策略保護。" : "須先核對 Preview 並確認委託，才能建立策略。"}</p>}
    <form onSubmit={event => {
      event.preventDefault();
      const source = { source_id: "order-desk-fake-edit", observed_at: "2026-10-29T01:59:30+00:00", content: { mode: "FAKE_ONLY", intent: "SL_TP_REVISION" } };
      if (strategy) void send({ type: "revise_strategy", strategy_id: strategy.strategy_id, expected_revision: strategy.strategy_revision,
        request_id: crypto.randomUUID(), rules, source });
      else if (review.snapshot) void send({ type: "create_strategy", review_id: review.review_id, expected_digest: review.snapshot.digest, rules, source });
    }}>
      <fieldset disabled={blocked || !eligible}>
        <legend>{strategy ? `修訂策略 revision ${strategy.strategy_revision}` : "設定已確認 Entry 的 SL / TP"}</legend>
        <div className={styles.formGrid}>
          <label>停損價<input inputMode="decimal" value={stop} onChange={e => setStop(e.target.value)} /></label>
          <label>停利價<input inputMode="decimal" value={take} onChange={e => setTake(e.target.value)} /></label>
          <label>退出限價<input required inputMode="decimal" value={exitPrice} onChange={e => setExitPrice(e.target.value)} /></label>
        </div>
        <button type="submit">{strategy ? "套用 SL / TP 修訂" : "建立本機策略"}</button>
      </fieldset>
    </form>
    <p className={styles.hint}>此表單只修改未來退出規則。新增 Entry 或增加曝險須另走 Preview / Confirm。</p>
  </section>;
}

function BrokerOrder({ order, account, role, send, blocked }: { order: Order; account: string; role: string; send: Send; blocked: boolean }) {
  const cancelDisabled = blocked || !order.broker_order_id || !!order.cancel_stage || ["FILLED", "CANCELLED", "REJECTED"].includes(order.state);
  return <article className={styles.order} aria-label={`${role} ${order.broker_order_id ?? "UNKNOWN"}`}>
    <div className={styles.sectionHeading}><strong>{role} · {order.broker_order_id ?? "未取得 Broker ID"}</strong><Badge warning={order.reconcile_required || order.state === "UNKNOWN"}>{order.state}</Badge></div>
    <p className={styles.fillTotal}>成交 <strong>{order.filled_shares}</strong> / {order.quantity} 股</p>
    <p>cancel_stage：{order.cancel_stage ?? "尚未要求"}</p>
    {order.cancel_stage && <p className={styles.notice}>{["FILLED", "CANCELLED", "REJECTED"].includes(order.state)
      ? `已取得 order state ${order.state}；cancel_stage 保留歷史 ACK，fills 與 reconciliation 另列。`
      : `CANCEL_ACK / ${order.cancel_stage} 僅表示撤單回覆；最終狀態與剩餘量仍待證據核對。`}</p>}
    <p className={styles.hint}>reconcile_required={String(order.reconcile_required)} · submit_stage={order.submit_stage}</p>
    <details><summary>精確撤單識別</summary><dl className={styles.identity}>
      <dt>account</dt><dd>{account}</dd><dt>date</dt><dd>{order.trade_date}</dd>
      <dt>order_id</dt><dd>{order.broker_order_id ?? "UNKNOWN"}</dd><dt>execution_id</dt><dd><code>{order.execution_id}</code></dd>
    </dl></details>
    <button className={styles.cancel} disabled={cancelDisabled} onClick={() => order.broker_order_id && void send({ type: "cancel", execution_id: order.execution_id,
      key: { account_id: account, trade_date: order.trade_date, order_id: order.broker_order_id } })}>立即精確撤單 {order.broker_order_id ?? ""}</button>
    {order.cancel_stage && <p className={styles.hint}>已有撤單 claim；重複派送已停用，可讀回狀態。</p>}
    {!order.broker_order_id && <p className={styles.notice}>UNKNOWN identity 無法撤單，不以價格或數量猜配。</p>}
    {order.fills.length ? <ul className={styles.fills} aria-label={`${role} 成交明細`}>{order.fills.map(fill => <li key={fill.fill_id}><strong>{fill.quantity} 股 @ {fill.price}</strong><span>{fill.source_time}</span><code>{fill.fill_id}</code></li>)}</ul>
      : <p className={styles.hint}>尚無已記錄成交，並不代表歷史已完整。</p>}
  </article>;
}

export default function OrderDesk({ fakeConfigured }: { fakeConfigured: boolean }) {
  const [desk, setDesk] = useState<DeskSnapshot | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [space, setSpace] = useState<Space | "ALL">("ALL");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [receipt, setReceipt] = useState("");
  const [needsRead, setNeedsRead] = useState(false);
  const inFlight = useRef(false);
  const selected = desk?.reviews.find(review => review.review_id === selectedId);
  const strategy = desk?.strategies.find(value => value.review_id === selectedId);
  const visible = desk?.reviews.filter(review => space === "ALL" || review.draft.command.space_id === space) ?? [];
  const pending = (s: Space) => desk?.reviews.filter(r => r.draft.command.space_id === s && ["PREVIEW", "DRAFT"].includes(r.state)).length ?? 0;

  async function run(action: "open" | "read" | DeskCommand) {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true); setError(""); setReceipt("");
    try {
      const value = action === "open" ? await openDemo() : action === "read" && desk ? await readDesk(desk.session_id)
        : desk && typeof action === "object" ? await commandDesk(desk.session_id, action) : null;
      if (value) {
        setDesk(value); setNeedsRead(false);
        if (action === "open") setSelectedId(value.reviews.find(r => r.state === "PREVIEW")?.review_id ?? "");
        const label = typeof action === "string" ? action : action.type;
        setReceipt(`${label} 已回傳 · FAKE_ONLY · Broker snapshot ${value.broker_snapshot.status}。請核對下方狀態；命令回覆不等同成交或撤單完成。`);
      }
    } catch (issue) {
      setError(issue instanceof Error ? issue.message : "EXECUTION_REQUEST_FAILED");
      setNeedsRead(true);
    } finally { inFlight.current = false; setBusy(false); }
  }
  const send: Send = command => run(command);
  const blocked = busy || needsRead;
  const events = selected ? [...selected.audit, ...selected.execution_audit].sort((a, b) => b.seq - a.seq) : [];

  return <main className={styles.desk} aria-busy={busy}>
    <a className={styles.skip} href="#selected-proposal">跳至選定單據</a>
    <header className={styles.header}>
      <div><Link href="/" prefetch={false} className={styles.back}>OMI / 市場研究</Link><h1>Order Desk <span>預審與執行</span></h1></div>
      <div className={styles.environment}><Badge warning>FAKE ONLY</Badge><span>Live broker · 未部署</span><span>Native / Runtime Adoption / MCP · UNVERIFIED</span></div>
    </header>
    <div className={styles.modeBar}>
      <p>獨立 Source / Fake 驗收工作台。所有帳戶、委託與成交均為虛構；狀態由 canonical ExecutionRuntime 提供。</p>
      <button disabled={busy || !!desk || !fakeConfigured} onClick={() => void run("open")}>載入隔離 Fake session</button>
      <button disabled={!desk || busy} onClick={() => void run("read")}>讀回狀態</button>
      <button disabled={!desk || blocked} onClick={() => void send({ type: "query" })}>查詢 Fake broker 證據</button>
    </div>
    {!fakeConfigured && <p className={styles.notice} role="status">Live transport 尚未部署，Fake transport 尚未設定；操作已停用。預覽啟動方式見 Phase4-Acceptance。</p>}
    {desk && <div className={styles.context}><span>{desk.account_id} / {desk.trade_date}（固定 fixture 日期）</span><Badge warning={desk.broker_snapshot.status !== "AVAILABLE"}>Broker snapshot · {desk.broker_snapshot.status}</Badge><span>fill_history_complete={String(desk.broker_snapshot.fill_history_complete ?? false)}</span></div>}
    {desk?.broker_snapshot.status === "PARTIAL" && <p role="alert" className={styles.notice}>PARTIAL：{desk.broker_snapshot.invalid_report_count} 列 Broker 回報已隔離；有效列仍可讀取，不能視為完整或空帳戶。</p>}
    {desk?.broker_snapshot.status === "UNAVAILABLE" && <p role="alert" className={styles.notice}>UNAVAILABLE：目前無法取得完整 Broker snapshot，保留既有證據，仍需 reconciliation。</p>}
    {error && <div role="alert" className={styles.error}><strong>操作未確認 · {error}</strong><p>先「讀回狀態」取得目前 revision 與 Broker 證據，再決定後續操作。未自動重送。</p></div>}
    <p role="status" aria-live="polite" className={styles.receipt}>{busy ? "命令處理中，等待 canonical 回覆…" : receipt}</p>

    <div className={styles.workbench}>
      <aside className={styles.queue} aria-label="雙 Space 預審清單">
        <div className={styles.panelTitle}><h2>預審清單</h2><span>{pending("USER_SPACE") + pending("AGENT_SPACE")} 待審</span></div>
        <div className={styles.spaces}><span>USER_SPACE <strong>{pending("USER_SPACE")}</strong></span><span>AGENT_SPACE <strong>{pending("AGENT_SPACE")}</strong></span></div>
        <label className={styles.filter}>顯示 Space<select value={space} onChange={e => setSpace(e.target.value as typeof space)}><option value="ALL">雙 Space</option><option value="USER_SPACE">使用者 USER_SPACE</option><option value="AGENT_SPACE">Agent AGENT_SPACE</option></select></label>
        <ul className={styles.queueList}>{visible.map(review => <li key={review.review_id}><button disabled={busy} aria-pressed={selectedId === review.review_id} onClick={() => setSelectedId(review.review_id)}>
          <span className={styles.queueMeta}>{spaceName(review.draft.command.space_id)} · r{review.review_revision}<Badge>{review.state}</Badge></span>
          <strong>{review.draft.command.symbol} <span>{review.draft.command.action === "Buy" ? "買進" : "賣出"}</span></strong>
          <span>{review.draft.command.quantity} 股 · 限價 {review.draft.command.price}</span>
          <small>{review.draft.command.intent_id}</small>
        </button></li>)}</ul>
        {!visible.length && <p className={styles.empty}>{desk ? "此 Space 尚無提案；切換雙 Space 查看其他單據。" : "載入隔離 Fake session，查看雙 Space 預審與既有執行案例。"}</p>}
      </aside>

      <section id="selected-proposal" className={styles.proposal} aria-label="選定提案" tabIndex={-1}>
        <div className={styles.panelTitle}><h2>選定單據</h2>{selected && <Badge>{selected.state}</Badge>}</div>
        {selected ? <>
          <div className={styles.ticketTitle}><h3>{selected.draft.command.symbol}</h3><span>{selected.draft.command.action === "Buy" ? "買進" : "賣出"} · {selected.draft.command.quantity} 股 @ {selected.draft.command.price}</span></div>
          <dl className={styles.ticket}>
            <div><dt>Space / 來源</dt><dd>{selected.draft.command.space_id} / {selected.draft.source}</dd></div>
            <div><dt>帳戶 / 交易日</dt><dd>{selected.draft.command.account_id} / {selected.draft.command.trade_date}</dd></div>
            <div><dt>委託條件</dt><dd>{selected.draft.command.condition} · {selected.draft.command.lot} · {selected.snapshot?.order_semantics.order_kind ?? "LIMIT"} / {selected.snapshot?.order_semantics.time_in_force ?? "ROD"}</dd></div>
            <div><dt>股數單位 / Broker qty</dt><dd>shares / {selected.snapshot?.order_semantics.broker_quantity ?? "尚無 Preview"}</dd></div>
            <div><dt>Owner</dt><dd>{selected.draft.owner_id}</dd></div>
            <div><dt>Strategy / intent</dt><dd>{selected.draft.command.strategy_id ?? "無"} / {selected.draft.command.intent_id}</dd></div>
          </dl>
          <details className={styles.selectors}><summary>核對確認 selectors · review revision {selected.review_revision}</summary><dl className={styles.identity}><dt>review_id</dt><dd><code>{selected.review_id}</code></dd><dt>digest</dt><dd><code>{selected.snapshot?.digest ?? "尚無 Preview"}</code></dd><dt>revision</dt><dd>{selected.review_revision}</dd></dl></details>
          <ReviewForm key={`${selected.review_id}-${selected.review_revision}-${selected.state}`} review={selected} send={send} blocked={blocked} />
          <StrategyForm key={`${selected.review_id}-${strategy?.strategy_revision ?? 0}`} strategy={strategy} review={selected} send={send} blocked={blocked} />
        </> : <p className={styles.empty}>選取左側提案以核對委託。未選定時，確認、修訂與拒絕均不可操作。</p>}
      </section>

      <section className={styles.broker} aria-label="Broker orders 與成交">
        <div className={styles.panelTitle}><h2>Broker orders</h2><span>虛構證據</span></div>
        <p className={styles.hint}>精確撤單立即送出，不二次確認。ACK ≠ final；partial fills 與 UNKNOWN 持續保留。</p>
        {selected?.execution ? <>
          <BrokerOrder order={strategy?.entry ?? selected.execution} account={selected.draft.command.account_id} role="Entry" send={send} blocked={blocked} />
          {strategy?.exits.map((order, index) => <BrokerOrder key={order.execution_id} order={order} account={selected.draft.command.account_id} role={`Exit ${index + 1}`} send={send} blocked={blocked} />)}
        </> : <p className={styles.empty}>{selected ? "此提案尚無 execution；確認前沒有 Broker order。" : "選定單據後顯示其委託與 fills。"}</p>}
      </section>
    </div>

    <section className={styles.timeline} aria-label="事件時間軸">
      <div className={styles.panelTitle}><h2>事件時間軸</h2><span>Journal 序列 · 最新在前</span></div>
      {events.length ? <ol>{events.map(event => <li key={event.seq}><span className={styles.sequence}>#{event.seq}</span><time>{event.occurred_at}</time><strong>{event.kind}</strong><details><summary>事件內容</summary><pre>{JSON.stringify(event.payload, null, 2)}</pre></details></li>)}</ol> : <p className={styles.empty}>尚未選定有 Journal 證據的提案。</p>}
    </section>

    <section className={styles.demo} aria-label="Fake 驗收控制">
      <div><h2>Fake 情境注入</h2><p>100 → 60 成交 → stop／cancel40／exit60 → late fill15／exit15 → 證據相符才 CLOSED</p></div>
      <div className={styles.actions}>
        <button disabled={!desk || busy} onClick={() => { const review = desk?.reviews.find(r => r.draft.command.strategy_id === desk.scenario.strategy_id); if (review) { setSpace("ALL"); setSelectedId(review.review_id); } }}>查看 60 / 100 案例</button>
        <button disabled={!desk?.scenario.next_step || blocked} onClick={() => desk?.scenario.next_step && void send({ type: "fake_step", step: desk.scenario.next_step })}>{desk?.scenario.next_step ? stepName[desk.scenario.next_step] : desk ? "情境已走完" : "等待 Fake session"}</button>
      </div>
      <div className={styles.actions}>{(["PARTIAL", "UNAVAILABLE", "AVAILABLE"] as const).map(status => <button key={status} disabled={!desk || blocked} onClick={() => void send({ type: "fake_snapshot", status })}>注入 {status} snapshot</button>)}</div>
      <button className={styles.unknownControl} disabled={!desk || blocked} onClick={() => void send({ type: "fake_submit_unknown" })}>注入下次委託 UNKNOWN</button>
      <p className={styles.hint}>這些按鈕只注入 fabricated evidence；不代表真實 broker 回報或已部署的 live 服務。</p>
    </section>
  </main>;
}
