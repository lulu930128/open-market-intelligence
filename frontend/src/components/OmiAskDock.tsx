"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useOmiAskStream, type OmiSseMessage } from "@/hooks/useOmiAskStream";

export type OmiAskTarget = {
  type:
    | "auto"
    | "market"
    | "data_freshness"
    | "tw_stock"
    | "tw_watchlist"
    | "tw_index"
    | "tw_futures"
    | "us_stock"
    | string;
  id?: string | null;
  label?: string | null;
  market?: string | null;
};

export type OmiAskDockContext = {
  market: string;
  label: string;
  target: OmiAskTarget;
  uiContext?: Record<string, unknown>;
};

type QuickQuestion = {
  label: string;
  intent: string;
  analysisHorizon: string;
  strategyProfile: string;
  question: string;
};

type SignalTone = "running" | "data" | "tool" | "done" | "error";

type DockSignal = {
  key: string;
  stage: string;
  label: string;
  message: string;
  tone: SignalTone;
  priority: number;
};
type SignalInput = {
  key?: unknown;
  signal_key?: unknown;
  dedupe_key?: unknown;
  stage: unknown;
  label?: unknown;
  stage_label?: unknown;
  message?: unknown;
  status?: unknown;
  phase?: unknown;
  tone?: SignalTone;
};

type StatusTone = "idle" | "asking" | "done" | "error";
type UnknownRecord = Record<string, unknown>;

const API_PROXY_PATH =
  process.env.NEXT_PUBLIC_API_PROXY_PATH?.trim() || "/omi-data";

const QUICK_QUESTIONS: QuickQuestion[] = [
  {
    label: "當沖",
    intent: "intraday",
    analysisHorizon: "intraday",
    strategyProfile: "short_term_momentum",
    question:
      "用當沖和盤中角度分析目前標的。請優先使用 OMI 可用的即時、今日、1分/5分、量價、技術指標、法人與市場資料；先給結論，再列出可觀察價位、進出風險與失效條件。若即時資料不足，直接用可用資料回答並標明限制。",
  },
  {
    label: "中線",
    intent: "swing",
    analysisHorizon: "swing",
    strategyProfile: "technical_swing",
    question:
      "用中線波段角度分析目前標的。請使用日K/週K、均線、動能、量能、籌碼、營收與相對市場資料；先給結論，再列出趨勢、支撐壓力、觀察條件與主要風險。",
  },
  {
    label: "長線",
    intent: "long",
    analysisHorizon: "long",
    strategyProfile: "fundamentals_growth",
    question:
      "用長線投資角度分析目前標的。請優先使用月K/週K、長期趨勢、營收、財務、產業脈絡、美股或台股市場影響與估值風險；先給結論，再說適合追蹤的長線條件與主要風險。",
  },
  {
    label: "風險",
    intent: "risk",
    analysisHorizon: "short",
    strategyProfile: "technical_swing",
    question:
      "用空方與避險角度分析目前標的。請優先檢查短線轉弱、跌破關鍵均線或支撐、量能失衡、反彈失敗、籌碼轉弱與市場逆風；先給風險結論，再列出可能的做空觀察條件、回補或停損條件，以及資料不足時不能判斷的部分。",
  },
];

const STAGE_LABELS: Record<string, string> = {
  queued: "準備送出",
  accepted: "收到問題",
  resolving: "確認目標",
  question_understanding: "理解問題",
  evidence_read: "讀取資料",
  score_model: "五因子評分",
  price_levels: "推導價位",
  intent: "辨識問題",
  market_session: "交易日判斷",
  risk_levels: "風控價位",
  decision_sources: "資料來源",
  position_math: "部位試算",
  decision_synthesis: "組合回答",
  answer_ready: "回答就緒",
  evidence: "資料護照",
  tool_run: "工具執行",
  delta: "回應串流",
  final: "渲染答案",
  done: "完成",
  stopped: "已停止",
  error: "錯誤",
};

function asRecord(value: unknown): UnknownRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as UnknownRecord)
    : {};
}

function stringValue(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function arrayValue(value: unknown) {
  return Array.isArray(value) ? value : [];
}

function numberValue(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function textFromItem(item: unknown) {
  if (typeof item === "string") return stringValue(item);
  const record = asRecord(item);
  return (
    stringValue(record.text) ||
    stringValue(record.label) ||
    stringValue(record.value)
  );
}

function textItems(value: unknown, limit?: number) {
  const items: string[] = [];
  for (const item of arrayValue(value)) {
    const text = textFromItem(item);
    if (!text || items.includes(text)) continue;
    items.push(text);
    if (typeof limit === "number" && items.length >= limit) break;
  }
  return items;
}

function formatPrice(value: unknown) {
  const number = numberValue(value);
  if (number === null) return null;
  if (Math.abs(number) >= 100) {
    return number.toLocaleString("en-US", { maximumFractionDigits: 0 });
  }
  return number.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

function zoneText(zone: unknown) {
  const record = asRecord(zone);
  const low = formatPrice(record.low);
  const high = formatPrice(record.high);
  if (low && high) return low === high ? low : `${low}-${high}`;
  return low || high || null;
}

function priceText(value: unknown) {
  const record = asRecord(value);
  return formatPrice(record.price) || formatPrice(value);
}

function intentLabel(intent: unknown) {
  return (
    {
      entry_decision: "買入 / 回檔判斷",
      exit_decision: "續抱 / 出場判斷",
      risk_check: "風險檢查",
      position_risk_decision: "部位風控",
      trend_view: "走勢觀察",
    }[stringValue(intent) || ""] ||
    stringValue(intent) ||
    "一般分析"
  );
}

function sourceLabel(source: unknown) {
  return (
    {
      question_intent: "專業判斷",
      analysis_digest: "技術摘要",
      llm_report: "AI 報告",
    }[stringValue(source) || ""] ||
    stringValue(source) ||
    null
  );
}

function stageLabel(stage: unknown, fallback?: unknown) {
  const cleanStage = stringValue(stage);
  return (
    stringValue(fallback) ||
    (cleanStage ? STAGE_LABELS[cleanStage] : null) ||
    cleanStage ||
    "處理中"
  );
}

function signalDotClass(tone: SignalTone) {
  if (tone === "error") return "bg-red-600";
  if (tone === "done") return "bg-emerald-500";
  if (tone === "tool") return "bg-amber-500";
  if (tone === "data") return "bg-sky-500";
  return "bg-slate-400";
}

function statusDotClass(tone: StatusTone) {
  if (tone === "error") return "bg-red-400";
  if (tone === "asking") return "bg-blue-400";
  if (tone === "done") return "bg-emerald-400";
  return "bg-slate-500";
}

function consumerAnswer(response: UnknownRecord) {
  const analysis = asRecord(response.analysis);
  const direct = asRecord(analysis.human_answer);
  if (stringValue(direct.kind) === "consumer_market_answer" || stringValue(direct.headline)) {
    return direct;
  }

  const result = asRecord(response.result);
  const data = asRecord(result.data);
  const overview = asRecord(data.overview);
  const overviewHuman = asRecord(overview.human_answer);
  if (overviewHuman.text || overviewHuman.lines) {
    return {
      kind: "consumer_market_answer",
      headline:
        stringValue(overview.display) ||
        stringValue(overviewHuman.text) ||
        "OMI 已完成整理",
      stance_label: stringValue(overview.stance) || "未定",
      confidence_label: stringValue(overview.confidence) || "未定",
      summary: textItems(overviewHuman.lines, 3),
      detail: stringValue(overviewHuman.text) || textItems(overviewHuman.lines).join("\n"),
    };
  }

  return {};
}

function consumerIntent(consumer: UnknownRecord, response: UnknownRecord) {
  const analysis = asRecord(response.analysis);
  return stringValue(consumer.intent) || stringValue(analysis.question_intent);
}

function consumerSource(consumer: UnknownRecord, response: UnknownRecord) {
  const analysis = asRecord(response.analysis);
  return stringValue(consumer.source) || stringValue(analysis.source);
}

function decisionEvidence(consumer: UnknownRecord, response: UnknownRecord) {
  const analysis = asRecord(response.analysis);
  const direct = asRecord(consumer.decision_evidence);
  if (Object.keys(direct).length > 0) return direct;
  return asRecord(analysis.decision_evidence);
}

function technicalLevels(response: UnknownRecord) {
  return asRecord(asRecord(response.analysis).technical_levels);
}

function priceLevelItems(response: UnknownRecord) {
  const technical = technicalLevels(response);
  const levels = asRecord(technical.levels);
  const entry = asRecord(technical.entry);
  const risk = asRecord(technical.risk);
  const items: Array<{ label: string; value: string; tone: string }> = [];

  function add(label: string, value: string | null, tone: string) {
    if (!value) return;
    items.push({ label, value, tone });
  }

  add("現價", formatPrice(technical.latest_price) || formatPrice(levels.latest), "neutral");
  add("回檔觀察", zoneText(entry.preferred_zone), "entry");
  add("突破確認", priceText(entry.breakout_confirm_above), "breakout");
  add("追價上限", priceText(entry.do_not_chase_above), "warning");
  add("短線停損", priceText(risk.short_stop), "risk");
  add("技術失效", priceText(risk.technical_invalidation), "risk");

  return items;
}

function uniqueCount(values: Array<string | null>) {
  return new Set(values.map((value) => String(value || "").trim()).filter(Boolean)).size;
}

function responseSourceCount(response: UnknownRecord) {
  const refs = arrayValue(response.source_refs)
    .map((item) => stringValue(asRecord(item).name))
    .filter((value): value is string => Boolean(value));
  const analysis = asRecord(response.analysis);
  const humanAnswer = asRecord(analysis.human_answer);
  const evidence = decisionEvidence(humanAnswer, response);
  const dataQuality = asRecord(evidence.data_quality);
  const sourceNames = arrayValue(dataQuality.source_names)
    .map((item) => stringValue(item))
    .filter((value): value is string => Boolean(value));
  return uniqueCount(refs.concat(sourceNames));
}

function decisionModuleCount(response: UnknownRecord) {
  const analysis = asRecord(response.analysis);
  const humanAnswer = asRecord(analysis.human_answer);
  const evidence = decisionEvidence(humanAnswer, response);
  let count = 0;
  if (Object.keys(technicalLevels(response)).length > 0) count += 1;
  if (Object.keys(asRecord(evidence.market_session)).length > 0) count += 1;
  if (Object.keys(asRecord(evidence.recent_volatility)).length > 0) count += 1;
  if (Object.keys(asRecord(evidence.indicator_quality)).length > 0) count += 1;
  if (Object.keys(asRecord(evidence.fundamentals)).length > 0) count += 1;
  return count;
}

function sourceCount(evidence: UnknownRecord | null) {
  if (!evidence) return 0;
  const explicitCount = numberValue(evidence.source_count);
  if (explicitCount !== null) return explicitCount;

  const sources = arrayValue(evidence.sources);
  if (sources.length > 0) return sources.length;

  return arrayValue(evidence.datasets).length;
}

function fallbackAnswer(response: UnknownRecord) {
  const analysis = asRecord(response.analysis);
  const result = asRecord(response.result);
  const summary = asRecord(result.summary);
  const humanAnswer = asRecord(analysis.human_answer);
  const humanText = stringValue(humanAnswer.text);
  if (humanText) return humanText;

  const display = stringValue(analysis.display);
  if (display) return display;

  const message = stringValue(result.message);
  if (message) return message;

  const highlights = arrayValue(summary.highlights)
    .map((item) => String(item).trim())
    .filter(Boolean);
  if (highlights.length > 0) return highlights.join("\n");

  return "OMI 已完成資料檢查。";
}

function priceToneClass(tone: string) {
  if (tone === "entry") return "border-emerald-200 bg-emerald-50 text-emerald-950";
  if (tone === "breakout") return "border-blue-200 bg-blue-50 text-blue-950";
  if (tone === "warning") return "border-amber-200 bg-amber-50 text-amber-950";
  if (tone === "risk") return "border-red-200 bg-red-50 text-red-950";
  return "border-slate-200 bg-slate-50 text-slate-950";
}

function Pill({ label, value }: { label: string; value: string | null }) {
  if (!value) return null;

  return (
    <span className="inline-flex items-center gap-1 border border-slate-200 bg-slate-50 px-2 py-1 text-[11px] font-semibold text-slate-700">
      <span className="text-slate-400">{label}</span>
      <span className="text-slate-900">{value}</span>
    </span>
  );
}

function TextList({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;

  return (
    <section className="space-y-1">
      <div className="text-[11px] font-bold uppercase tracking-[0.18em] text-slate-400">
        {title}
      </div>
      <div className="space-y-1">
        {items.map((item) => (
          <div key={item} className="flex gap-2 text-sm leading-6 text-slate-800">
            <span className="mt-2 h-1.5 w-1.5 flex-none rounded-full bg-red-600" />
            <span>{item}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

function PriceLevels({ response }: { response: UnknownRecord }) {
  const items = priceLevelItems(response);
  if (items.length === 0) return null;

  return (
    <section className="space-y-1">
      <div className="text-[11px] font-bold uppercase tracking-[0.18em] text-slate-400">
        關鍵價位
      </div>
      <div className="grid grid-cols-2 gap-1.5">
        {items.map((item) => (
          <div key={item.label} className={`border px-2.5 py-2 ${priceToneClass(item.tone)}`}>
            <div className="text-[11px] font-bold text-slate-500">{item.label}</div>
            <div className="mt-0.5 text-sm font-black leading-5">{item.value}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

function ActionPlan({
  actions,
  title,
}: {
  actions: unknown;
  title: string;
}) {
  const cleanActions = arrayValue(actions)
    .map((item) => {
      const record = asRecord(item);
      return {
        label: stringValue(record.label) || "觀察",
        text: stringValue(record.text) || textFromItem(item),
      };
    })
    .filter((item): item is { label: string; text: string } => Boolean(item.text))
    .slice(0, 3);

  if (cleanActions.length === 0) return null;

  return (
    <section className="space-y-1">
      <div className="text-[11px] font-bold uppercase tracking-[0.18em] text-slate-400">
        {title}
      </div>
      <div className="grid gap-1.5">
        {cleanActions.map((item) => (
          <div key={`${item.label}:${item.text}`} className="border border-slate-200 bg-slate-50 px-2.5 py-2">
            <div className="text-xs font-bold text-slate-950">{item.label}</div>
            <div className="mt-0.5 text-sm leading-6 text-slate-700">{item.text}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

function StructuredAnswer({ response }: { response: UnknownRecord | null }) {
  if (!response) return null;

  const consumer = consumerAnswer(response);
  const headline = stringValue(consumer.headline);
  if (!headline) return null;

  const intent = consumerIntent(consumer, response);
  const source = consumerSource(consumer, response);
  const isEntryDecision = intent === "entry_decision";
  const detail = stringValue(consumer.detail) || stringValue(consumer.text);

  return (
    <div className="space-y-3">
      <div className="border-l-4 border-red-600 bg-slate-50 px-3 py-2">
        <div className="text-[11px] font-bold uppercase tracking-[0.18em] text-slate-400">
          {isEntryDecision ? "買入判斷" : "結論"}
        </div>
        <div className="mt-1 text-base font-black leading-6 text-slate-950">
          {headline}
        </div>
        <div className="mt-2 flex flex-wrap gap-1.5">
          <Pill label="類型" value={intentLabel(intent)} />
          <Pill label="方向" value={stringValue(consumer.stance_label)} />
          <Pill label="信心" value={stringValue(consumer.confidence_label)} />
          <Pill label="來源" value={sourceLabel(source)} />
        </div>
      </div>

      {isEntryDecision ? <PriceLevels response={response} /> : null}
      <TextList
        title={isEntryDecision ? "判斷依據" : "三個重點"}
        items={textItems(consumer.summary, 4)}
      />
      <ActionPlan
        title={isEntryDecision ? "操作條件" : "怎麼做"}
        actions={consumer.action_plan}
      />
      <ActionPlan title="情境劇本" actions={consumer.scenarios} />
      <TextList title="反證條件" items={textItems(consumer.counter_evidence, 2)} />
      <TextList title="風險" items={textItems(consumer.risks, 2)} />
      <TextList title="資料限制" items={textItems(consumer.data_limits, 3)} />

      {detail ? (
        <details className="border border-slate-200 bg-white px-3 py-2 text-sm leading-6 text-slate-700">
          <summary className="cursor-pointer text-xs font-bold text-slate-500">
            展開完整解讀
          </summary>
          <div className="mt-2 whitespace-pre-wrap text-slate-700">{detail}</div>
        </details>
      ) : null}
    </div>
  );
}

function AnswerPanel({
  answerText,
  finalResponse,
}: {
  answerText: string;
  finalResponse: UnknownRecord | null;
}) {
  const consumer = finalResponse ? consumerAnswer(finalResponse) : {};
  if (finalResponse && stringValue(consumer.headline)) {
    return <StructuredAnswer response={finalResponse} />;
  }

  if (answerText) return <div className="whitespace-pre-wrap">{answerText}</div>;

  return (
    <div className="border border-dashed border-slate-300 bg-slate-50 px-3 py-4 text-sm leading-6 text-slate-500">
      直接問 OMI 目前畫面上的標的或群組。系統會使用現有行情、技術、籌碼與基本面資料回答，這裡只保留短期上下文。
    </div>
  );
}

function signalPriority(raw: SignalInput) {
  const status = stringValue(raw.status)?.toLowerCase();
  const phase = stringValue(raw.phase)?.toLowerCase();
  if (status === "error" || status === "failed" || phase === "failed") return 50;
  if (raw.tone === "error") return 50;
  if (status === "success" || status === "completed" || phase === "completed") return 40;
  if (raw.tone === "done") return 40;
  if (status === "blocked" || phase === "blocked") return 30;
  if (status === "skipped" || phase === "skipped") return 20;
  if (status === "running" || phase === "running" || raw.tone === "running") return 10;
  return 0;
}

function buildSignal(raw: SignalInput) {
  const stage = stringValue(raw.stage) || "status";
  const label = stringValue(raw.label) || stageLabel(stage, raw.stage_label);
  const message = stringValue(raw.message) || label;
  const tone = raw.tone || "running";
  const key =
    stringValue(raw.key) ||
    stringValue(raw.signal_key) ||
    stringValue(raw.dedupe_key) ||
    `${stage}|${label}|${message}|${tone}`;
  return { key, stage, label, message, tone, priority: signalPriority(raw) };
}

function buildRequest({
  context,
  lastResolution,
  options,
  question,
}: {
  context: OmiAskDockContext;
  lastResolution: UnknownRecord | null;
  options: Partial<QuickQuestion>;
  question: string;
}) {
  const target = asRecord(context.target);
  const targetType = stringValue(target.type) || "auto";
  const analysisHorizon = stringValue(options.analysisHorizon) || "auto";
  const strategyProfile =
    stringValue(options.strategyProfile) || "short_term_momentum";
  const intent = stringValue(options.intent);

  return {
    question,
    target,
    mode: "auto",
    caller_profile: "kuro_readonly",
    allow_llm: true,
    allow_write: false,
    allow_external_fetch: true,
    tool_budget: {
      max_calls: targetType === "us_stock" ? 5 : 4,
      max_external_fetches: targetType === "us_stock" ? 3 : 2,
      max_total_seconds: 25,
    },
    refresh_policy: {
      mode: "stale_first",
      before_answer: true,
      fallback_to_cached: true,
    },
    strategy_profile: strategyProfile,
    analysis_horizon: analysisHorizon,
    conversation_context: {
      last_resolution: lastResolution,
      ui_context: {
        ...asRecord(context.uiContext),
        ask_intent: intent,
        analysis_horizon: analysisHorizon,
        strategy_profile: strategyProfile,
      },
    },
  };
}

function dataCountFromResponse(finalResponse: UnknownRecord | null, evidence: UnknownRecord | null) {
  if (finalResponse) return responseSourceCount(finalResponse);
  return sourceCount(evidence);
}

export default function OmiAskDock({ context }: { context: OmiAskDockContext }) {
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [askedQuestion, setAskedQuestion] = useState("");
  const [answerText, setAnswerText] = useState("");
  const [finalResponse, setFinalResponse] = useState<UnknownRecord | null>(null);
  const [evidence, setEvidence] = useState<UnknownRecord | null>(null);
  const [toolRuns, setToolRuns] = useState(0);
  const [signals, setSignals] = useState<DockSignal[]>([]);
  const [statusLabel, setStatusLabel] = useState("待命");
  const [statusTone, setStatusTone] = useState<StatusTone>("idle");
  const [signalsOpen, setSignalsOpen] = useState(false);
  const [lastResolution, setLastResolution] = useState<UnknownRecord | null>(null);
  const lastResolutionRef = useRef<UnknownRecord | null>(null);
  const hasDeltaRef = useRef(false);
  const responseSignalAddedRef = useRef(false);
  const streamPath = `${API_PROXY_PATH}/ai/ask/stream`;
  const { ask, isStreaming, stop } = useOmiAskStream(streamPath);
  const contextKey = useMemo(
    () => `${context.market}:${context.target.type}:${context.target.id ?? ""}:${context.label}`,
    [context.label, context.market, context.target.id, context.target.type]
  );
  const dataCount = dataCountFromResponse(finalResponse, evidence);

  const appendSignal = useCallback((signalInput: SignalInput) => {
    const signal = buildSignal(signalInput);
    setSignals((current) => {
      const existingIndex = current.findIndex((item) => item.key === signal.key);
      if (existingIndex >= 0) {
        const existing = current[existingIndex];
        if (signal.priority < existing.priority) return current;
        const next = [...current];
        next[existingIndex] = signal;
        return next.slice(-10);
      }
      const last = current[current.length - 1];
      if (last?.key === signal.key) return current;
      return [...current, signal].slice(-10);
    });
  }, []);

  const appendDecisionSignals = useCallback(
    (response: UnknownRecord) => {
      const consumer = consumerAnswer(response);
      const intent = consumerIntent(consumer, response);
      const evidenceRecord = decisionEvidence(consumer, response);
      const marketSession = asRecord(evidenceRecord.market_session);
      const levels = priceLevelItems(response);
      const sourceCountValue = responseSourceCount(response);
      const moduleCount = decisionModuleCount(response);

      if (intent && intent !== "general") {
        appendSignal({
          stage: "intent",
          label: "辨識問題",
          message: `已辨識為「${intentLabel(intent)}」，使用價位與風控版型回答。`,
          tone: "data",
        });
      }

      if (marketSession.is_trading_day === false) {
        appendSignal({
          stage: "market_session",
          label: "交易日判斷",
          message:
            stringValue(marketSession.summary) ||
            "目前不是台股交易日，改用最新日線資料判斷。",
          tone: "data",
        });
      }

      const entryLevel = levels.find((item) => item.label === "回檔觀察");
      const breakoutLevel = levels.find((item) => item.label === "突破確認");
      const chaseLevel = levels.find((item) => item.label === "追價上限");
      const priceParts = [
        entryLevel ? `回檔 ${entryLevel.value}` : null,
        breakoutLevel ? `突破 ${breakoutLevel.value}` : null,
        chaseLevel ? `追價上限 ${chaseLevel.value}` : null,
      ].filter((value): value is string => Boolean(value));

      if (priceParts.length > 0) {
        appendSignal({
          stage: "price_levels",
          label: "推導價位",
          message: `${priceParts.join("；")}。`,
          tone: "tool",
        });
      }

      const stopLevel = levels.find((item) => item.label === "短線停損");
      const invalidationLevel = levels.find((item) => item.label === "技術失效");
      const riskParts = [
        stopLevel ? `停損 ${stopLevel.value}` : null,
        invalidationLevel ? `失效 ${invalidationLevel.value}` : null,
      ].filter((value): value is string => Boolean(value));

      if (riskParts.length > 0) {
        appendSignal({
          stage: "risk_levels",
          label: "風控價位",
          message: `${riskParts.join("；")}。`,
          tone: "tool",
        });
      }

      if (sourceCountValue || moduleCount) {
        appendSignal({
          stage: "decision_sources",
          label: "資料來源",
          message: `已使用 ${sourceCountValue} 個資料來源與 ${moduleCount} 個判斷模組。`,
          tone: "data",
        });
      }
    },
    [appendSignal]
  );

  const resetForAsk = useCallback((nextQuestion: string) => {
    hasDeltaRef.current = false;
    responseSignalAddedRef.current = false;
    setAskedQuestion(nextQuestion);
    setAnswerText("");
    setFinalResponse(null);
    setEvidence(null);
    setToolRuns(0);
    setSignals([]);
    setStatusLabel("準備中");
    setStatusTone("asking");
    setSignalsOpen(false);
  }, []);

  const handleMessage = useCallback(
    (message: OmiSseMessage) => {
      const data = asRecord(message.data);

      if (message.event === "status") {
        const label = stageLabel(data.stage, data.stage_label);
        setStatusLabel(label);
        setStatusTone("asking");
        appendSignal({
          stage: stringValue(data.stage) || "status",
          label,
          message: stringValue(data.message) || label,
          tone: "running",
          key: data.signal_key || data.dedupe_key,
          status: data.status,
          phase: data.phase,
        });
        return;
      }

      if (message.event === "evidence") {
        setEvidence(data);
        appendSignal({
          stage: "evidence",
          label: "資料護照",
          message: `已取得 ${sourceCount(data)} 個資料來源，可信度 ${stringValue(data.trust_level) || "未標示"}。`,
          tone: "data",
        });
        return;
      }

      if (message.event === "tool_run") {
        const toolName = stringValue(data.tool) || stringValue(data.name) || "工具";
        const toolScope = stringValue(data.tool_scope) || "default";
        const toolLabel = stringValue(data.tool_label) || toolName;
        const status = stringValue(data.status) || "已回傳";
        setToolRuns((value) => value + 1);
        appendSignal({
          stage: "tool_run",
          label: "工具執行",
          message: stringValue(data.message) || `${toolLabel}：${status}`,
          tone: "tool",
          key: data.signal_key || `tool:${toolName}:${toolScope}`,
          status: data.status,
          phase: data.phase,
        });
        return;
      }

      if (message.event === "delta") {
        hasDeltaRef.current = true;
        if (!responseSignalAddedRef.current) {
          appendSignal({
            stage: "delta",
            label: "回應串流",
            message: "開始輸出回答內容。",
            tone: "running",
          });
          responseSignalAddedRef.current = true;
        }
        setAnswerText((value) => value + (stringValue(data.text) || ""));
        setStatusLabel("回應中");
        setStatusTone("asking");
        return;
      }

      if (message.event === "final") {
        const resolution = asRecord(data.resolution);
        if (Object.keys(resolution).length > 0) {
          lastResolutionRef.current = resolution;
          setLastResolution(resolution);
        }

        setFinalResponse(data);
        if (!stringValue(asRecord(asRecord(data.analysis).human_answer).headline) && !hasDeltaRef.current) {
          setAnswerText(fallbackAnswer(data));
        }
        appendDecisionSignals(data);
        appendSignal({
          stage: "final",
          label: "渲染答案",
          message: "已收到完整回答資料並更新面板。",
          tone: "done",
        });
        return;
      }

      if (message.event === "error") {
        const errorMessage =
          stringValue(data.error) || stringValue(data.message) || "OMI request failed.";
        appendSignal({
          stage: "error",
          label: "錯誤",
          message: errorMessage,
          tone: "error",
        });
        throw new Error(errorMessage);
      }

      if (message.event === "done") {
        const ok = data.ok !== false;
        setStatusLabel(ok ? "完成" : "未完成");
        setStatusTone(ok ? "done" : "error");
        appendSignal({
          stage: "done",
          label: ok ? "完成" : "未完成",
          message: ok ? "OMI 串流已完成。" : "OMI 串流未完成。",
          tone: ok ? "done" : "error",
        });
      }
    },
    [appendDecisionSignals, appendSignal]
  );

  const submitQuestion = useCallback(
    (rawQuestion: string, options: Partial<QuickQuestion> = {}) => {
      const nextQuestion = rawQuestion.trim();
      if (!nextQuestion) return;

      resetForAsk(nextQuestion);
      const request = buildRequest({
        context,
        lastResolution: lastResolutionRef.current,
        options,
        question: nextQuestion,
      });

      void ask(request, {
        onMessage: handleMessage,
        onError: (error) => {
          setStatusLabel("發生錯誤");
          setStatusTone("error");
          setAnswerText(error.message);
          appendSignal({
            stage: "error",
            label: "錯誤",
            message: error.message,
            tone: "error",
          });
        },
      });
    },
    [appendSignal, ask, context, handleMessage, resetForAsk]
  );

  const stopAsk = useCallback(() => {
    stop();
    setStatusLabel("已停止");
    setStatusTone("idle");
    appendSignal({
      stage: "stopped",
      label: "已停止",
      message: "使用者已停止這次 OMI 串流。",
      tone: "error",
    });
  }, [appendSignal, stop]);

  useEffect(() => {
    lastResolutionRef.current = lastResolution;
  }, [lastResolution]);

  return (
    <div className="fixed bottom-4 right-4 z-[2147483647]" data-omi-context-key={contextKey}>
      {!open ? (
        <button
          type="button"
          className="inline-flex h-11 items-center gap-2 border border-slate-900 bg-slate-950 px-3 text-sm font-black text-white shadow-lg transition hover:bg-red-700"
          aria-label="開啟 OMI 即時問答"
          onClick={() => setOpen(true)}
        >
          <span className="h-2 w-2 rounded-full bg-red-400" />
          <span>OMI 問答</span>
        </button>
      ) : (
        <aside className="flex max-h-[calc(100vh-2rem)] w-[390px] max-w-[calc(100vw-2rem)] flex-col border border-slate-300 bg-white shadow-2xl">
          <header className="flex items-center justify-between border-b border-slate-200 bg-slate-950 py-2 pl-3 pr-3 text-white">
            <div>
              <div className="text-[11px] font-semibold uppercase tracking-[0.22em] text-red-300">
                OMI
              </div>
              <div className="text-sm font-bold">即時問答</div>
            </div>
            <div className="flex items-center gap-2">
              <div className="relative">
                <button
                  type="button"
                  className="inline-flex max-w-[170px] items-center gap-1.5 text-xs text-slate-300 transition hover:text-white"
                  aria-label="查看 OMI 處理訊號"
                  onClick={() => setSignalsOpen((value) => !value)}
                >
                  <span className={`h-2 w-2 flex-none rounded-full ${statusDotClass(statusTone)}`} />
                  <span className="truncate">{statusLabel}</span>
                </button>
                {signalsOpen ? (
                  <div className="absolute right-0 top-7 z-10 w-72 max-w-[calc(100vw-2rem)] border border-slate-700 bg-slate-950 p-2 text-xs text-slate-200 shadow-2xl">
                    <div className="mb-1 text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
                      Signals
                    </div>
                    <div className="space-y-1.5">
                      {signals.length > 0 ? (
                        signals.map((signal) => (
                          <div key={signal.key} className="flex gap-2 text-xs leading-5 text-slate-300">
                            <span className={`mt-1.5 h-2 w-2 flex-none rounded-full ${signalDotClass(signal.tone)}`} />
                            <div className="min-w-0 flex-1">
                              <div className="font-bold text-slate-100">{signal.label}</div>
                              <div className="break-words text-slate-400">{signal.message}</div>
                            </div>
                          </div>
                        ))
                      ) : (
                        <div className="text-slate-500">尚無處理訊號。</div>
                      )}
                    </div>
                  </div>
                ) : null}
              </div>
              <button
                type="button"
                className="grid h-7 w-7 place-items-center border border-slate-600 text-sm font-bold text-slate-200 hover:border-white hover:text-white"
                aria-label="收起 OMI 即時問答"
                onClick={() => {
                  setSignalsOpen(false);
                  setOpen(false);
                }}
              >
                -
              </button>
            </div>
          </header>

          <div className="border-b border-slate-200 bg-slate-50 px-3 py-2">
            <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
              目前標的
            </div>
            <div className="mt-0.5 truncate text-sm font-bold text-slate-950">
              {context.label || "目前標的"}
            </div>
          </div>

          <div className="min-h-[220px] flex-1 overflow-y-auto px-3 py-3">
            {askedQuestion ? (
              <section className="mb-3">
                <div className="mb-1 text-[11px] font-bold uppercase tracking-[0.18em] text-slate-400">
                  Question
                </div>
                <div className="border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-bold leading-6 text-slate-900">
                  {askedQuestion}
                </div>
              </section>
            ) : null}
            <section>
              <div className="mb-1 text-[11px] font-bold uppercase tracking-[0.18em] text-slate-400">
                Answer
              </div>
              <div className="border border-slate-200 bg-white p-2 text-sm leading-6 text-slate-800">
                <AnswerPanel answerText={answerText} finalResponse={finalResponse} />
              </div>
            </section>
          </div>

          <div className="border-t border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-500">
            資料 {dataCount} / 工具 {toolRuns}
          </div>

          <div className="border-t border-slate-200 bg-slate-50 px-3 py-3">
            <div className="mb-2 flex flex-wrap gap-1.5">
              {QUICK_QUESTIONS.map((item) => (
                <button
                  key={item.label}
                  type="button"
                  disabled={isStreaming}
                  className="border border-slate-300 bg-white px-3 py-1.5 text-sm font-semibold text-slate-700 hover:border-slate-950 disabled:cursor-not-allowed disabled:opacity-50"
                  onClick={() => submitQuestion(item.question, item)}
                >
                  {item.label}
                </button>
              ))}
            </div>
            <form
              className="flex items-end gap-2"
              onSubmit={(event) => {
                event.preventDefault();
                submitQuestion(question);
              }}
            >
              <textarea
                rows={2}
                value={question}
                disabled={isStreaming}
                placeholder="輸入問題..."
                className="min-h-[44px] flex-1 resize-none border border-slate-300 bg-white px-3 py-2 text-sm text-slate-950 outline-none transition placeholder:text-slate-400 focus:border-slate-950 disabled:bg-slate-100"
                onChange={(event) => setQuestion(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key !== "Enter" || event.shiftKey) return;
                  event.preventDefault();
                  submitQuestion(question);
                }}
              />
              {isStreaming ? (
                <button
                  type="button"
                  className="h-11 border border-slate-900 bg-white px-4 text-sm font-bold text-slate-950 hover:bg-slate-100"
                  onClick={stopAsk}
                >
                  Stop
                </button>
              ) : null}
              <button
                type="submit"
                disabled={isStreaming || !question.trim()}
                className="h-11 bg-red-700 px-4 text-sm font-bold text-white hover:bg-slate-950 disabled:bg-slate-300"
              >
                送出
              </button>
            </form>
          </div>
        </aside>
      )}
    </div>
  );
}
