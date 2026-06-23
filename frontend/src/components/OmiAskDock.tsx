"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useOmiAskStream, type OmiSseMessage } from "@/hooks/useOmiAskStream";
import { useI18n, useT, type AppLocale, type TranslationFunction } from "@/i18n";

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
    | "jp_stock"
    | "jp_index"
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
  labelKey: string;
  promptKey: string;
  intent: string;
  analysisHorizon: string;
  strategyProfile: string;
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
type PriceLevelKey =
  | "latest"
  | "pullback"
  | "breakout"
  | "chaseLimit"
  | "shortStop"
  | "invalidation";
type PriceLevelItem = {
  key: PriceLevelKey;
  label: string;
  value: string;
  tone: string;
};

const API_PROXY_PATH =
  process.env.NEXT_PUBLIC_API_PROXY_PATH?.trim() || "/omi-data";
const SETTINGS_COLOR_STORAGE_KEY = "omi:settings:color";

const QUICK_QUESTIONS: QuickQuestion[] = [
  {
    labelKey: "intraday",
    promptKey: "intraday",
    intent: "intraday",
    analysisHorizon: "intraday",
    strategyProfile: "short_term_momentum",
  },
  {
    labelKey: "swing",
    promptKey: "swing",
    intent: "swing",
    analysisHorizon: "swing",
    strategyProfile: "technical_swing",
  },
  {
    labelKey: "long",
    promptKey: "long",
    intent: "long",
    analysisHorizon: "long",
    strategyProfile: "fundamentals_growth",
  },
  {
    labelKey: "risk",
    promptKey: "risk",
    intent: "risk",
    analysisHorizon: "short",
    strategyProfile: "technical_swing",
  },
];

const STAGE_LABEL_KEYS = new Set([
  "queued",
  "accepted",
  "resolving",
  "question_understanding",
  "evidence_read",
  "score_model",
  "price_levels",
  "intent",
  "market_session",
  "risk_levels",
  "decision_sources",
  "position_math",
  "decision_synthesis",
  "answer_ready",
  "evidence",
  "tool_run",
  "delta",
  "final",
  "done",
  "stopped",
  "error",
]);

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

function currentThemePreference() {
  if (typeof document !== "undefined") {
    const theme = document.documentElement.dataset.theme;
    if (theme === "light" || theme === "dark") return theme;
    if (theme === "high-contrast") return "dark";
  }

  if (typeof window !== "undefined") {
    try {
      const theme = window.localStorage.getItem(SETTINGS_COLOR_STORAGE_KEY);
      if (theme === "light" || theme === "dark") return theme;
      if (theme === "high-contrast") return "dark";
    } catch {
      // Local preference access can fail in restricted browser contexts.
    }
  }

  return null;
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

function intentLabel(intent: unknown, t: TranslationFunction) {
  const cleanIntent = stringValue(intent);
  if (
    cleanIntent === "entry_decision" ||
    cleanIntent === "exit_decision" ||
    cleanIntent === "risk_check" ||
    cleanIntent === "position_risk_decision" ||
    cleanIntent === "trend_view"
  ) {
    return t(`ask.intents.${cleanIntent}`);
  }

  return cleanIntent || t("ask.intents.general");
}

function sourceLabel(source: unknown, t: TranslationFunction) {
  const cleanSource = stringValue(source);
  if (
    cleanSource === "question_intent" ||
    cleanSource === "analysis_digest" ||
    cleanSource === "llm_report"
  ) {
    return t(`ask.sources.${cleanSource}`);
  }

  return cleanSource || null;
}

function stageLabel(stage: unknown, t: TranslationFunction, fallback?: unknown) {
  const cleanStage = stringValue(stage);
  return (
    stringValue(fallback) ||
    (cleanStage && STAGE_LABEL_KEYS.has(cleanStage) ? t(`ask.stages.${cleanStage}`) : null) ||
    cleanStage ||
    t("ask.status.processing")
  );
}

function signalDotClass(tone: SignalTone) {
  if (tone === "error") return "bg-omi-market-up";
  if (tone === "done") return "bg-omi-market-down-flash";
  if (tone === "tool") return "bg-omi-warning";
  if (tone === "data") return "bg-omi-info";
  return "bg-omi-text-subtle";
}

function statusDotClass(tone: StatusTone) {
  if (tone === "error") return "bg-omi-market-up-flash";
  if (tone === "asking") return "bg-omi-info";
  if (tone === "done") return "bg-omi-market-down-flash";
  return "bg-omi-text-muted";
}

function consumerAnswer(response: UnknownRecord, t: TranslationFunction) {
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
        t("ask.fallback.organized"),
      stance_label: stringValue(overview.stance) || t("ask.fallback.undecided"),
      confidence_label: stringValue(overview.confidence) || t("ask.fallback.undecided"),
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

function priceLevelItems(response: UnknownRecord, t: TranslationFunction) {
  const technical = technicalLevels(response);
  const levels = asRecord(technical.levels);
  const entry = asRecord(technical.entry);
  const risk = asRecord(technical.risk);
  const items: PriceLevelItem[] = [];

  function add(key: PriceLevelKey, value: string | null, tone: string) {
    if (!value) return;
    items.push({ key, label: t(`ask.priceLevels.${key}`), value, tone });
  }

  add("latest", formatPrice(technical.latest_price) || formatPrice(levels.latest), "neutral");
  add("pullback", zoneText(entry.preferred_zone), "entry");
  add("breakout", priceText(entry.breakout_confirm_above), "breakout");
  add("chaseLimit", priceText(entry.do_not_chase_above), "warning");
  add("shortStop", priceText(risk.short_stop), "risk");
  add("invalidation", priceText(risk.technical_invalidation), "risk");

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

function fallbackAnswer(response: UnknownRecord, t: TranslationFunction) {
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

  return t("ask.fallback.completed");
}

function priceToneClass(tone: string) {
  if (tone === "entry") return "border-omi-success-border bg-omi-success-soft text-omi-success-strong";
  if (tone === "breakout") return "border-omi-info-border bg-omi-info-soft text-omi-info-strong";
  if (tone === "warning") return "border-omi-warning-border bg-omi-warning-soft text-omi-warning-strong";
  if (tone === "risk") return "border-omi-danger-border bg-omi-danger-soft text-omi-danger-strong";
  return "border-omi-border-subtle bg-omi-surface-subtle text-omi-text-strong";
}

function Pill({ label, value }: { label: string; value: string | null }) {
  if (!value) return null;

  return (
    <span className="inline-flex items-center gap-1 border border-omi-border-subtle bg-omi-surface-subtle px-2 py-1 text-[11px] font-semibold text-omi-text">
      <span className="text-omi-text-subtle">{label}</span>
      <span className="text-omi-text">{value}</span>
    </span>
  );
}

function TextList({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;

  return (
    <section className="space-y-1">
      <div className="text-[11px] font-bold uppercase tracking-[0.18em] text-omi-text-subtle">
        {title}
      </div>
      <div className="space-y-1">
        {items.map((item) => (
          <div key={item} className="flex gap-2 text-sm leading-6 text-omi-text">
            <span className="mt-2 h-1.5 w-1.5 flex-none rounded-full bg-omi-market-up" />
            <span>{item}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

function PriceLevels({ response }: { response: UnknownRecord }) {
  const t = useT();
  const items = priceLevelItems(response, t);
  if (items.length === 0) return null;

  return (
    <section className="space-y-1">
      <div className="text-[11px] font-bold uppercase tracking-[0.18em] text-omi-text-subtle">
        {t("ask.priceLevels.title")}
      </div>
      <div className="grid grid-cols-2 gap-1.5">
        {items.map((item) => (
          <div key={item.label} className={`border px-2.5 py-2 ${priceToneClass(item.tone)}`}>
            <div className="text-[11px] font-bold text-omi-text-muted">{item.label}</div>
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
  const t = useT();
  const cleanActions = arrayValue(actions)
    .map((item) => {
      const record = asRecord(item);
      return {
        label: stringValue(record.label) || t("ask.structured.observe"),
        text: stringValue(record.text) || textFromItem(item),
      };
    })
    .filter((item): item is { label: string; text: string } => Boolean(item.text))
    .slice(0, 3);

  if (cleanActions.length === 0) return null;

  return (
    <section className="space-y-1">
      <div className="text-[11px] font-bold uppercase tracking-[0.18em] text-omi-text-subtle">
        {title}
      </div>
      <div className="grid gap-1.5">
        {cleanActions.map((item) => (
          <div key={`${item.label}:${item.text}`} className="border border-omi-border-subtle bg-omi-surface-subtle px-2.5 py-2">
            <div className="text-xs font-bold text-omi-text-strong">{item.label}</div>
            <div className="mt-0.5 text-sm leading-6 text-omi-text">{item.text}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

function StructuredAnswer({ response }: { response: UnknownRecord | null }) {
  const t = useT();
  if (!response) return null;

  const consumer = consumerAnswer(response, t);
  const headline = stringValue(consumer.headline);
  if (!headline) return null;

  const intent = consumerIntent(consumer, response);
  const source = consumerSource(consumer, response);
  const isEntryDecision = intent === "entry_decision";
  const detail = stringValue(consumer.detail) || stringValue(consumer.text);

  return (
    <div className="space-y-3">
      <div className="border-l-4 border-omi-market-up bg-omi-surface-subtle px-3 py-2">
        <div className="text-[11px] font-bold uppercase tracking-[0.18em] text-omi-text-subtle">
          {isEntryDecision ? t("ask.structured.buyDecision") : t("ask.structured.conclusion")}
        </div>
        <div className="mt-1 text-base font-black leading-6 text-omi-text-strong">
          {headline}
        </div>
        <div className="mt-2 flex flex-wrap gap-1.5">
          <Pill label={t("ask.structured.type")} value={intentLabel(intent, t)} />
          <Pill label={t("ask.structured.direction")} value={stringValue(consumer.stance_label)} />
          <Pill label={t("ask.structured.confidence")} value={stringValue(consumer.confidence_label)} />
          <Pill label={t("ask.structured.source")} value={sourceLabel(source, t)} />
        </div>
      </div>

      {isEntryDecision ? <PriceLevels response={response} /> : null}
      <TextList
        title={isEntryDecision ? t("ask.structured.evidence") : t("ask.structured.topPoints")}
        items={textItems(consumer.summary, 4)}
      />
      <ActionPlan
        title={isEntryDecision ? t("ask.structured.conditions") : t("ask.structured.whatToDo")}
        actions={consumer.action_plan}
      />
      <ActionPlan title={t("ask.structured.scenarios")} actions={consumer.scenarios} />
      <TextList title={t("ask.structured.counterEvidence")} items={textItems(consumer.counter_evidence, 2)} />
      <TextList title={t("ask.structured.risks")} items={textItems(consumer.risks, 2)} />
      <TextList title={t("ask.structured.dataLimits")} items={textItems(consumer.data_limits, 3)} />

      {detail ? (
        <details className="border border-omi-border-subtle bg-omi-surface px-3 py-2 text-sm leading-6 text-omi-text">
          <summary className="cursor-pointer text-xs font-bold text-omi-text-muted">
            {t("ask.structured.expand")}
          </summary>
          <div className="mt-2 whitespace-pre-wrap text-omi-text">{detail}</div>
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
  const t = useT();
  const consumer = finalResponse ? consumerAnswer(finalResponse, t) : {};
  if (finalResponse && stringValue(consumer.headline)) {
    return <StructuredAnswer response={finalResponse} />;
  }

  if (answerText) return <div className="whitespace-pre-wrap">{answerText}</div>;

  return (
    <div className="border border-dashed border-omi-border bg-omi-surface-subtle px-3 py-4 text-sm leading-6 text-omi-text-muted">
      {t("ask.fallback.empty")}
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

function buildSignal(raw: SignalInput, t: TranslationFunction) {
  const stage = stringValue(raw.stage) || "status";
  const label = stringValue(raw.label) || stageLabel(stage, t, raw.stage_label);
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
  locale,
  options,
  question,
  responseLanguage,
  theme,
}: {
  context: OmiAskDockContext;
  lastResolution: UnknownRecord | null;
  locale: AppLocale;
  options: Partial<QuickQuestion>;
  question: string;
  responseLanguage: string;
  theme: string | null;
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
    mode: "brief",
    caller_profile: "kuro_readonly",
    allow_llm: false,
    allow_write: false,
    allow_external_fetch: false,
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
        response_locale: locale,
        response_language: responseLanguage,
        settings: {
          locale,
          response_locale: locale,
          response_language: responseLanguage,
          theme,
          technical_analysis_parameters: "server_persisted",
        },
      },
    },
  };
}

function dataCountFromResponse(finalResponse: UnknownRecord | null, evidence: UnknownRecord | null) {
  if (finalResponse) return responseSourceCount(finalResponse);
  return sourceCount(evidence);
}

export default function OmiAskDock({ context }: { context: OmiAskDockContext }) {
  const t = useT();
  const { locale } = useI18n();
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [askedQuestion, setAskedQuestion] = useState("");
  const [answerText, setAnswerText] = useState("");
  const [finalResponse, setFinalResponse] = useState<UnknownRecord | null>(null);
  const [evidence, setEvidence] = useState<UnknownRecord | null>(null);
  const [toolRuns, setToolRuns] = useState(0);
  const [signals, setSignals] = useState<DockSignal[]>([]);
  const [statusLabel, setStatusLabel] = useState(() => t("ask.status.idle"));
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
  const displayStatusLabel =
    !isStreaming && !askedQuestion && statusTone === "idle"
      ? t("ask.status.idle")
      : statusLabel;

  const appendSignal = useCallback((signalInput: SignalInput) => {
    const signal = buildSignal(signalInput, t);
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
  }, [t]);

  const appendDecisionSignals = useCallback(
    (response: UnknownRecord) => {
      const consumer = consumerAnswer(response, t);
      const intent = consumerIntent(consumer, response);
      const evidenceRecord = decisionEvidence(consumer, response);
      const marketSession = asRecord(evidenceRecord.market_session);
      const levels = priceLevelItems(response, t);
      const sourceCountValue = responseSourceCount(response);
      const moduleCount = decisionModuleCount(response);

      if (intent && intent !== "general") {
        appendSignal({
          stage: "intent",
          label: t("ask.stages.intent"),
          message: t("ask.signals.intentRecognized", { intent: intentLabel(intent, t) }),
          tone: "data",
        });
      }

      if (marketSession.is_trading_day === false) {
        appendSignal({
          stage: "market_session",
          label: t("ask.stages.market_session"),
          message:
            stringValue(marketSession.summary) ||
            t("ask.signals.notTradingDay"),
          tone: "data",
        });
      }

      const entryLevel = levels.find((item) => item.key === "pullback");
      const breakoutLevel = levels.find((item) => item.key === "breakout");
      const chaseLevel = levels.find((item) => item.key === "chaseLimit");
      const priceParts = [
        entryLevel ? t("ask.signals.pullback", { value: entryLevel.value }) : null,
        breakoutLevel ? t("ask.signals.breakout", { value: breakoutLevel.value }) : null,
        chaseLevel ? t("ask.signals.chaseLimit", { value: chaseLevel.value }) : null,
      ].filter((value): value is string => Boolean(value));

      if (priceParts.length > 0) {
        appendSignal({
          stage: "price_levels",
          label: t("ask.stages.price_levels"),
          message: `${priceParts.join(t("ask.signals.listSeparator"))}${t("ask.signals.sentenceSuffix")}`,
          tone: "tool",
        });
      }

      const stopLevel = levels.find((item) => item.key === "shortStop");
      const invalidationLevel = levels.find((item) => item.key === "invalidation");
      const riskParts = [
        stopLevel ? t("ask.signals.stop", { value: stopLevel.value }) : null,
        invalidationLevel ? t("ask.signals.invalidation", { value: invalidationLevel.value }) : null,
      ].filter((value): value is string => Boolean(value));

      if (riskParts.length > 0) {
        appendSignal({
          stage: "risk_levels",
          label: t("ask.stages.risk_levels"),
          message: `${riskParts.join(t("ask.signals.listSeparator"))}${t("ask.signals.sentenceSuffix")}`,
          tone: "tool",
        });
      }

      if (sourceCountValue || moduleCount) {
        appendSignal({
          stage: "decision_sources",
          label: t("ask.stages.decision_sources"),
          message: t("ask.signals.usedSources", {
            sourceCount: sourceCountValue,
            moduleCount,
          }),
          tone: "data",
        });
      }
    },
    [appendSignal, t]
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
    setStatusLabel(t("ask.status.preparing"));
    setStatusTone("asking");
    setSignalsOpen(false);
  }, [t]);

  const handleMessage = useCallback(
    (message: OmiSseMessage) => {
      const data = asRecord(message.data);

      if (message.event === "status") {
        const label = stageLabel(data.stage, t, data.stage_label);
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
          label: t("ask.stages.evidence"),
          message: t("ask.signals.evidenceReceived", {
            count: sourceCount(data),
            trustLevel: stringValue(data.trust_level) || t("ask.fallback.trustUnknown"),
          }),
          tone: "data",
        });
        return;
      }

      if (message.event === "tool_run") {
        const toolName = stringValue(data.tool) || stringValue(data.name) || t("ask.fallback.tool");
        const toolScope = stringValue(data.tool_scope) || "default";
        const toolLabel = stringValue(data.tool_label) || toolName;
        const status = stringValue(data.status) || t("ask.fallback.returned");
        setToolRuns((value) => value + 1);
        appendSignal({
          stage: "tool_run",
          label: t("ask.stages.tool_run"),
          message: stringValue(data.message) || `${toolLabel}${t("ask.signals.statusSeparator")}${status}`,
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
            label: t("ask.stages.delta"),
            message: t("ask.signals.responseStarted"),
            tone: "running",
          });
          responseSignalAddedRef.current = true;
        }
        setAnswerText((value) => value + (stringValue(data.text) || ""));
        setStatusLabel(t("ask.status.responding"));
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
          setAnswerText(fallbackAnswer(data, t));
        }
        appendDecisionSignals(data);
        appendSignal({
          stage: "final",
          label: t("ask.stages.final"),
          message: t("ask.signals.finalReceived"),
          tone: "done",
        });
        return;
      }

      if (message.event === "error") {
        const errorMessage =
          stringValue(data.error) || stringValue(data.message) || t("ask.fallback.requestFailed");
        appendSignal({
          stage: "error",
          label: t("ask.stages.error"),
          message: errorMessage,
          tone: "error",
        });
        throw new Error(errorMessage);
      }

      if (message.event === "done") {
        const ok = data.ok !== false;
        setStatusLabel(ok ? t("ask.status.completed") : t("ask.status.incomplete"));
        setStatusTone(ok ? "done" : "error");
        appendSignal({
          stage: "done",
          label: ok ? t("ask.status.completed") : t("ask.status.incomplete"),
          message: ok ? t("ask.signals.streamCompleted") : t("ask.signals.streamIncomplete"),
          tone: ok ? "done" : "error",
        });
      }
    },
    [appendDecisionSignals, appendSignal, t]
  );

  const submitQuestion = useCallback(
    (rawQuestion: string, options: Partial<QuickQuestion> = {}) => {
      const nextQuestion = rawQuestion.trim();
      if (!nextQuestion) return;

      resetForAsk(nextQuestion);
      const request = buildRequest({
        context,
        lastResolution: lastResolutionRef.current,
        locale,
        options,
        question: nextQuestion,
        responseLanguage: t(`locales.${locale}`),
        theme: currentThemePreference(),
      });

      void ask(request, {
        onMessage: handleMessage,
        onError: (error) => {
          setStatusLabel(t("ask.status.error"));
          setStatusTone("error");
          setAnswerText(error.message);
          appendSignal({
            stage: "error",
            label: t("ask.stages.error"),
            message: error.message,
            tone: "error",
          });
        },
      });
    },
    [appendSignal, ask, context, handleMessage, locale, resetForAsk, t]
  );

  const stopAsk = useCallback(() => {
    stop();
    setStatusLabel(t("ask.status.stopped"));
    setStatusTone("idle");
    appendSignal({
      stage: "stopped",
      label: t("ask.status.stopped"),
      message: t("ask.signals.userStopped"),
      tone: "error",
    });
  }, [appendSignal, stop, t]);

  useEffect(() => {
    lastResolutionRef.current = lastResolution;
  }, [lastResolution]);

  return (
    <div className="fixed bottom-4 right-4 z-[2147483647]" data-omi-context-key={contextKey}>
      {!open ? (
        <button
          type="button"
          className="inline-flex h-11 items-center gap-2 border border-omi-control bg-omi-control px-3 text-sm font-black text-omi-text-inverse shadow-lg transition hover:bg-omi-accent"
          aria-label={t("ask.ui.open")}
          onClick={() => setOpen(true)}
        >
          <span className="h-2 w-2 rounded-full bg-omi-market-up-flash" />
          <span>{t("ask.ui.compactTitle")}</span>
        </button>
      ) : (
        <aside className="flex max-h-[calc(100vh-2rem)] w-[390px] max-w-[calc(100vw-2rem)] flex-col border border-omi-border bg-omi-surface shadow-2xl">
          <header className="flex items-center justify-between border-b border-omi-border-subtle bg-omi-control py-2 pl-3 pr-3 text-omi-text-inverse">
            <div>
              <div className="text-[11px] font-semibold uppercase tracking-[0.22em] text-omi-market-up-flash">
                OMI
              </div>
              <div className="text-sm font-bold">{t("ask.ui.title")}</div>
            </div>
            <div className="flex items-center gap-2">
              <div className="relative">
                <button
                  type="button"
                  className="inline-flex max-w-[170px] items-center gap-1.5 text-xs text-omi-text-inverse-muted transition hover:text-omi-text-inverse"
                  aria-label={t("ask.ui.viewSignals")}
                  onClick={() => setSignalsOpen((value) => !value)}
                >
                  <span className={`h-2 w-2 flex-none rounded-full ${statusDotClass(statusTone)}`} />
                  <span className="truncate">{displayStatusLabel}</span>
                </button>
                {signalsOpen ? (
                  <div className="absolute right-0 top-7 z-10 w-72 max-w-[calc(100vw-2rem)] border border-omi-control-border bg-omi-control p-2 text-xs text-omi-text-inverse-muted shadow-2xl">
                    <div className="mb-1 text-[10px] font-bold uppercase tracking-[0.18em] text-omi-text-muted">
                      {t("ask.ui.signals")}
                    </div>
                    <div className="space-y-1.5">
                      {signals.length > 0 ? (
                        signals.map((signal) => (
                          <div key={signal.key} className="flex gap-2 text-xs leading-5 text-omi-text-inverse-muted">
                            <span className={`mt-1.5 h-2 w-2 flex-none rounded-full ${signalDotClass(signal.tone)}`} />
                            <div className="min-w-0 flex-1">
                              <div className="font-bold text-omi-text-inverse-muted">{signal.label}</div>
                              <div className="break-words text-omi-text-subtle">{signal.message}</div>
                            </div>
                          </div>
                        ))
                      ) : (
                        <div className="text-omi-text-muted">{t("ask.fallback.noSignals")}</div>
                      )}
                    </div>
                  </div>
                ) : null}
              </div>
              <button
                type="button"
                className="grid h-7 w-7 place-items-center border border-omi-control-border text-sm font-bold text-omi-text-inverse-muted hover:border-omi-surface hover:text-omi-text-inverse"
                aria-label={t("ask.ui.collapse")}
                onClick={() => {
                  setSignalsOpen(false);
                  setOpen(false);
                }}
              >
                -
              </button>
            </div>
          </header>

          <div className="border-b border-omi-border-subtle bg-omi-surface-subtle px-3 py-2">
            <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-omi-text-muted">
              {t("ask.ui.currentTarget")}
            </div>
            <div className="mt-0.5 truncate text-sm font-bold text-omi-text-strong">
              {context.label || t("ask.fallback.currentTarget")}
            </div>
          </div>

          <div className="min-h-[220px] flex-1 overflow-y-auto px-3 py-3">
            {askedQuestion ? (
              <section className="mb-3">
                <div className="mb-1 text-[11px] font-bold uppercase tracking-[0.18em] text-omi-text-subtle">
                  {t("ask.ui.question")}
                </div>
                <div className="border border-omi-border-subtle bg-omi-surface-subtle px-3 py-2 text-sm font-bold leading-6 text-omi-text">
                  {askedQuestion}
                </div>
              </section>
            ) : null}
            <section>
              <div className="mb-1 text-[11px] font-bold uppercase tracking-[0.18em] text-omi-text-subtle">
                {t("ask.ui.answer")}
              </div>
              <div className="border border-omi-border-subtle bg-omi-surface p-2 text-sm leading-6 text-omi-text">
                <AnswerPanel answerText={answerText} finalResponse={finalResponse} />
              </div>
            </section>
          </div>

          <div className="border-t border-omi-border-subtle bg-omi-surface-subtle px-3 py-2 text-xs text-omi-text-muted">
            {t("ask.ui.dataTools", { dataCount, toolRuns })}
          </div>

          <div className="border-t border-omi-border-subtle bg-omi-surface-subtle px-3 py-3">
            <div className="mb-2 flex flex-wrap gap-1.5">
              {QUICK_QUESTIONS.map((item) => (
                <button
                  key={item.labelKey}
                  type="button"
                  disabled={isStreaming}
                  className="border border-omi-border bg-omi-surface px-3 py-1.5 text-sm font-semibold text-omi-text hover:border-omi-control disabled:cursor-not-allowed disabled:opacity-50"
                  onClick={() =>
                    submitQuestion(
                      t(`ask.quickQuestionPrompts.${item.promptKey}`),
                      item
                    )
                  }
                >
                  {t(`ask.quickQuestions.${item.labelKey}`)}
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
                placeholder={t("ask.ui.placeholder")}
                className="min-h-[44px] flex-1 resize-none border border-omi-border bg-omi-surface px-3 py-2 text-sm text-omi-text-strong outline-none transition placeholder:text-omi-text-subtle focus:border-omi-control disabled:bg-omi-surface-muted"
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
                  className="h-11 border border-omi-control bg-omi-surface px-4 text-sm font-bold text-omi-text-strong hover:bg-omi-surface-muted"
                  onClick={stopAsk}
                >
                  {t("ask.ui.stop")}
                </button>
              ) : null}
              <button
                type="submit"
                disabled={isStreaming || !question.trim()}
                className="h-11 bg-omi-accent px-4 text-sm font-bold text-omi-text-inverse hover:bg-omi-control disabled:bg-omi-border"
              >
                {t("ask.ui.send")}
              </button>
            </form>
          </div>
        </aside>
      )}
    </div>
  );
}
