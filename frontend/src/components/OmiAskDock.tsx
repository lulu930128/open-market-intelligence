"use client";

import { useEffect } from "react";

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

const API_PROXY_PATH =
  process.env.NEXT_PUBLIC_API_PROXY_PATH?.trim() || "/omi-data";
const OMI_ASK_DOCK_VERSION = "omi-dock-entry-layout-v7";

const OMI_ASK_DOCK_SCRIPT = String.raw`
(() => {
  const win = window;
  const SCRIPT_VERSION = "${OMI_ASK_DOCK_VERSION}";

  const QUICK_QUESTIONS = [
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

  const STAGE_LABELS = {
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

  function asRecord(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value) ? value : {};
  }

  function stringValue(value) {
    return typeof value === "string" && value.trim() ? value.trim() : null;
  }

  function arrayValue(value) {
    return Array.isArray(value) ? value : [];
  }

  function numberValue(value) {
    return typeof value === "number" && Number.isFinite(value) ? value : null;
  }

  function parseSseBlock(block) {
    let event = "message";
    const dataLines = [];

    for (const rawLine of block.split(/\r?\n/)) {
      if (!rawLine || rawLine.startsWith(":")) continue;

      const separatorIndex = rawLine.indexOf(":");
      const field = separatorIndex === -1 ? rawLine : rawLine.slice(0, separatorIndex);
      const value =
        separatorIndex === -1 ? "" : rawLine.slice(separatorIndex + 1).replace(/^ /, "");

      if (field === "event") event = value;
      if (field === "data") dataLines.push(value);
    }

    if (dataLines.length === 0 && event === "message") return null;

    const dataText = dataLines.join("\n");
    if (!dataText) return { event, data: {} };

    try {
      return { event, data: JSON.parse(dataText) };
    } catch {
      return { event, data: dataText };
    }
  }

  function fallbackAnswer(response) {
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

  function textFromItem(item) {
    if (typeof item === "string") return stringValue(item);
    const record = asRecord(item);
    return stringValue(record.text) || stringValue(record.label) || stringValue(record.value);
  }

  function textItems(value, limit) {
    const items = [];
    for (const item of arrayValue(value)) {
      const text = textFromItem(item);
      if (!text || items.includes(text)) continue;
      items.push(text);
      if (typeof limit === "number" && items.length >= limit) break;
    }
    return items;
  }

  function formatPrice(value) {
    const number = numberValue(value);
    if (number === null) return null;
    if (Math.abs(number) >= 100) return number.toLocaleString("en-US", { maximumFractionDigits: 0 });
    return number.toLocaleString("en-US", { maximumFractionDigits: 2 });
  }

  function zoneText(zone) {
    const record = asRecord(zone);
    const low = formatPrice(record.low);
    const high = formatPrice(record.high);
    if (low && high) return low === high ? low : low + "-" + high;
    return low || high || null;
  }

  function priceText(value) {
    const record = asRecord(value);
    return formatPrice(record.price) || formatPrice(value);
  }

  function intentLabel(intent) {
    return (
      {
        entry_decision: "買入 / 回檔判斷",
        exit_decision: "續抱 / 出場判斷",
        risk_check: "風險檢查",
        position_risk_decision: "部位風控",
        trend_view: "走勢觀察",
      }[stringValue(intent) || ""] || "一般分析"
    );
  }

  function sourceLabel(source) {
    return (
      {
        question_intent: "專業判斷",
        analysis_digest: "技術摘要",
        llm_report: "AI 報告",
      }[stringValue(source) || ""] || stringValue(source)
    );
  }

  function consumerIntent(consumer, response) {
    const analysis = asRecord(response.analysis);
    return stringValue(consumer.intent) || stringValue(analysis.question_intent);
  }

  function consumerSource(consumer, response) {
    const analysis = asRecord(response.analysis);
    return stringValue(consumer.source) || stringValue(analysis.source);
  }

  function decisionEvidence(consumer, response) {
    const analysis = asRecord(response.analysis);
    const direct = asRecord(consumer.decision_evidence);
    if (Object.keys(direct).length > 0) return direct;
    return asRecord(analysis.decision_evidence);
  }

  function technicalLevels(response) {
    return asRecord(asRecord(response.analysis).technical_levels);
  }

  function priceLevelItems(response) {
    const technical = technicalLevels(response);
    const levels = asRecord(technical.levels);
    const entry = asRecord(technical.entry);
    const risk = asRecord(technical.risk);
    const items = [];

    function add(label, value, tone) {
      if (!value) return;
      items.push({ label, value, tone });
    }

    add("現價", formatPrice(technical.latest_price) || formatPrice(levels.latest), "neutral");
    add("回檔觀察", zoneText(asRecord(entry.preferred_zone)), "entry");
    add("突破確認", priceText(entry.breakout_confirm_above), "breakout");
    add("追價上限", priceText(entry.do_not_chase_above), "warning");
    add("短線停損", priceText(risk.short_stop), "risk");
    add("技術失效", priceText(risk.technical_invalidation), "risk");

    return items;
  }

  function uniqueCount(values) {
    return new Set(values.map((value) => String(value || "").trim()).filter(Boolean)).size;
  }

  function responseSourceCount(response) {
    const refs = arrayValue(response.source_refs)
      .map((item) => stringValue(asRecord(item).name))
      .filter(Boolean);
    const analysis = asRecord(response.analysis);
    const humanAnswer = asRecord(analysis.human_answer);
    const evidence = decisionEvidence(humanAnswer, response);
    const dataQuality = asRecord(evidence.data_quality);
    const sourceNames = arrayValue(dataQuality.source_names)
      .map((item) => stringValue(item))
      .filter(Boolean);
    return uniqueCount(refs.concat(sourceNames));
  }

  function decisionModuleCount(response) {
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

  function consumerAnswer(response) {
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
        headline: stringValue(overview.display) || stringValue(overviewHuman.text) || "OMI 已完成整理",
        stance_label: stringValue(overview.stance) || "未定",
        confidence_label: stringValue(overview.confidence) || "未定",
        summary: textItems(overviewHuman.lines, 3),
        detail: stringValue(overviewHuman.text) || textItems(overviewHuman.lines).join("\n"),
      };
    }

    return {};
  }

  function answerContainer(root) {
    return root.querySelector("[data-omi-answer]");
  }

  function setPlainAnswer(root, value) {
    const answer = answerContainer(root);
    if (!answer) return;
    answer.classList.add("whitespace-pre-wrap");
    answer.replaceChildren(document.createTextNode(value || ""));
  }

  function appendPlainAnswer(root, value) {
    const answer = answerContainer(root);
    if (!answer) return;
    answer.classList.add("whitespace-pre-wrap");
    answer.appendChild(document.createTextNode(value || ""));
  }

  function node(tagName, className, text) {
    const element = document.createElement(tagName);
    if (className) element.className = className;
    if (text !== undefined && text !== null) element.textContent = String(text);
    return element;
  }

  function appendPill(parent, label, value) {
    if (!value) return;
    const pill = node(
      "span",
      "inline-flex items-center gap-1 border border-slate-200 bg-slate-50 px-2 py-1 text-[11px] font-semibold text-slate-700"
    );
    pill.appendChild(node("span", "text-slate-400", label));
    pill.appendChild(node("span", "text-slate-900", value));
    parent.appendChild(pill);
  }

  function appendTextList(parent, title, items) {
    if (!items.length) return;
    const section = node("section", "space-y-1");
    section.appendChild(
      node("div", "text-[11px] font-bold uppercase tracking-[0.18em] text-slate-400", title)
    );
    const list = node("div", "space-y-1");
    items.forEach((item) => {
      const row = node("div", "flex gap-2 text-sm leading-6 text-slate-800");
      row.appendChild(node("span", "mt-2 h-1.5 w-1.5 flex-none rounded-full bg-red-600"));
      row.appendChild(node("span", "", item));
      list.appendChild(row);
    });
    section.appendChild(list);
    parent.appendChild(section);
  }

  function priceToneClass(tone) {
    if (tone === "entry") return "border-emerald-200 bg-emerald-50 text-emerald-950";
    if (tone === "breakout") return "border-blue-200 bg-blue-50 text-blue-950";
    if (tone === "warning") return "border-amber-200 bg-amber-50 text-amber-950";
    if (tone === "risk") return "border-red-200 bg-red-50 text-red-950";
    return "border-slate-200 bg-slate-50 text-slate-950";
  }

  function appendPriceLevels(parent, response) {
    const items = priceLevelItems(response);
    if (!items.length) return;

    const section = node("section", "space-y-1");
    section.appendChild(
      node("div", "text-[11px] font-bold uppercase tracking-[0.18em] text-slate-400", "關鍵價位")
    );
    const grid = node("div", "grid grid-cols-2 gap-1.5");
    items.forEach((item) => {
      const card = node("div", "border px-2.5 py-2 " + priceToneClass(item.tone));
      card.appendChild(node("div", "text-[11px] font-bold text-slate-500", item.label));
      card.appendChild(node("div", "mt-0.5 text-sm font-black leading-5", item.value));
      grid.appendChild(card);
    });
    section.appendChild(grid);
    parent.appendChild(section);
  }

  function appendActionPlan(parent, actions, title) {
    const cleanActions = arrayValue(actions)
      .map((item) => {
        const record = asRecord(item);
        return {
          label: stringValue(record.label) || "觀察",
          text: stringValue(record.text) || textFromItem(item),
        };
      })
      .filter((item) => item.text)
      .slice(0, 3);
    if (!cleanActions.length) return;

    const section = node("section", "space-y-1");
    section.appendChild(
      node("div", "text-[11px] font-bold uppercase tracking-[0.18em] text-slate-400", title || "怎麼做")
    );
    const list = node("div", "grid gap-1.5");
    cleanActions.forEach((item) => {
      const card = node("div", "border border-slate-200 bg-slate-50 px-2.5 py-2");
      card.appendChild(node("div", "text-xs font-bold text-slate-950", item.label));
      card.appendChild(node("div", "mt-0.5 text-sm leading-6 text-slate-700", item.text));
      list.appendChild(card);
    });
    section.appendChild(list);
    parent.appendChild(section);
  }

  function stageLabel(stage, fallback) {
    const cleanStage = stringValue(stage);
    return stringValue(fallback) || (cleanStage ? STAGE_LABELS[cleanStage] : null) || cleanStage || "處理中";
  }

  function signalDotClass(tone) {
    if (tone === "error") return "bg-red-600";
    if (tone === "done") return "bg-emerald-500";
    if (tone === "tool") return "bg-amber-500";
    if (tone === "data") return "bg-sky-500";
    return "bg-slate-400";
  }

  function resetSignals(root) {
    const state = win.__omiAskDockState;
    state.signals = [];
    state.responseSignalAdded = false;
    const list = root.querySelector("[data-omi-signals]");
    if (list) list.replaceChildren();
    setHidden(root, "[data-omi-signal-popover]", true);
  }

  function appendSignal(root, signal) {
    const list = root.querySelector("[data-omi-signals]");
    if (!list) return;

    const state = win.__omiAskDockState;
    const stage = stringValue(signal.stage) || "status";
    const label = stageLabel(stage, signal.stage_label);
    const message = stringValue(signal.message) || label;
    const tone = stringValue(signal.tone) || "running";
    const key = stage + "|" + label + "|" + message + "|" + tone;
    const last = state.signals[state.signals.length - 1];
    if (last?.key === key) return;

    state.signals.push({ key });

    const row = node("div", "flex gap-2 text-xs leading-5 text-slate-300");
    row.appendChild(node("span", "mt-1.5 h-2 w-2 flex-none rounded-full " + signalDotClass(tone)));
    const body = node("div", "min-w-0 flex-1");
    body.appendChild(node("div", "font-bold text-slate-100", label));
    body.appendChild(node("div", "break-words text-slate-400", message));
    row.appendChild(body);
    list.appendChild(row);

    while (list.childNodes.length > 10) {
      list.removeChild(list.firstChild);
    }
  }

  function appendDecisionSignals(root, response) {
    const consumer = consumerAnswer(response);
    const intent = consumerIntent(consumer, response);
    const evidence = decisionEvidence(consumer, response);
    const marketSession = asRecord(evidence.market_session);
    const levels = priceLevelItems(response);
    const dataCount = responseSourceCount(response);
    const moduleCount = decisionModuleCount(response);

    if (intent && intent !== "general") {
      appendSignal(root, {
        stage: "intent",
        stage_label: "辨識問題",
        message: "已辨識為「" + intentLabel(intent) + "」，使用價位與風控版型回答。",
        tone: "data",
      });
    }

    if (marketSession.is_trading_day === false) {
      appendSignal(root, {
        stage: "market_session",
        stage_label: "交易日判斷",
        message: stringValue(marketSession.summary) || "目前不是台股交易日，改用最新日線資料判斷。",
        tone: "data",
      });
    }

    const entryLevel = levels.find((item) => item.label === "回檔觀察");
    const breakoutLevel = levels.find((item) => item.label === "突破確認");
    const chaseLevel = levels.find((item) => item.label === "追價上限");
    const priceParts = [];
    if (entryLevel) priceParts.push("回檔 " + entryLevel.value);
    if (breakoutLevel) priceParts.push("突破 " + breakoutLevel.value);
    if (chaseLevel) priceParts.push("追價上限 " + chaseLevel.value);
    if (priceParts.length) {
      appendSignal(root, {
        stage: "price_levels",
        stage_label: "推導價位",
        message: priceParts.join("；") + "。",
        tone: "tool",
      });
    }

    const stopLevel = levels.find((item) => item.label === "短線停損");
    const invalidationLevel = levels.find((item) => item.label === "技術失效");
    const riskParts = [];
    if (stopLevel) riskParts.push("停損 " + stopLevel.value);
    if (invalidationLevel) riskParts.push("失效 " + invalidationLevel.value);
    if (riskParts.length) {
      appendSignal(root, {
        stage: "risk_levels",
        stage_label: "風控價位",
        message: riskParts.join("；") + "。",
        tone: "tool",
      });
    }

    if (dataCount || moduleCount) {
      appendSignal(root, {
        stage: "decision_sources",
        stage_label: "資料來源",
        message: "已使用 " + dataCount + " 個資料來源與 " + moduleCount + " 個判斷模組。",
        tone: "data",
      });
    }
  }

  function toggleSignalPopover(root) {
    const popover = root.querySelector("[data-omi-signal-popover]");
    if (!popover) return;
    popover.hidden = !popover.hidden;
  }

  function renderStructuredAnswer(root, response) {
    const answer = answerContainer(root);
    if (!answer) return false;

    const consumer = consumerAnswer(response);
    const headline = stringValue(consumer.headline);
    if (!headline) return false;
    const intent = consumerIntent(consumer, response);
    const source = consumerSource(consumer, response);
    const isEntryDecision = intent === "entry_decision";

    answer.classList.remove("whitespace-pre-wrap");
    answer.replaceChildren();

    const wrapper = node("div", "space-y-3");
    const header = node("div", "border-l-4 border-red-600 bg-slate-50 px-3 py-2");
    header.appendChild(
      node(
        "div",
        "text-[11px] font-bold uppercase tracking-[0.18em] text-slate-400",
        isEntryDecision ? "買入判斷" : "結論"
      )
    );
    header.appendChild(node("div", "mt-1 text-base font-black leading-6 text-slate-950", headline));
    const meta = node("div", "mt-2 flex flex-wrap gap-1.5");
    appendPill(meta, "類型", intentLabel(intent));
    appendPill(meta, "方向", stringValue(consumer.stance_label));
    appendPill(meta, "信心", stringValue(consumer.confidence_label));
    appendPill(meta, "來源", sourceLabel(source));
    if (meta.childNodes.length) header.appendChild(meta);
    wrapper.appendChild(header);

    if (isEntryDecision) appendPriceLevels(wrapper, response);
    appendTextList(wrapper, isEntryDecision ? "判斷依據" : "三個重點", textItems(consumer.summary, 4));
    appendActionPlan(wrapper, consumer.action_plan, isEntryDecision ? "操作條件" : "怎麼做");
    appendTextList(wrapper, "風險", textItems(consumer.risks, 2));
    appendTextList(wrapper, "資料限制", textItems(consumer.data_limits, 3));

    const detail = stringValue(consumer.detail) || stringValue(consumer.text);
    if (detail) {
      const details = node("details", "border border-slate-200 bg-white px-3 py-2 text-sm leading-6 text-slate-700");
      details.appendChild(node("summary", "cursor-pointer text-xs font-bold text-slate-500", "展開完整解讀"));
      details.appendChild(node("div", "mt-2 whitespace-pre-wrap text-slate-700", detail));
      wrapper.appendChild(details);
    }

    answer.appendChild(wrapper);
    return true;
  }

  function sourceCount(evidence) {
    const explicitCount = numberValue(evidence.source_count);
    if (explicitCount !== null) return explicitCount;

    const sources = arrayValue(evidence.sources);
    if (sources.length > 0) return sources.length;

    return arrayValue(evidence.datasets).length;
  }

  function latestPayload() {
    const nodes = Array.from(document.querySelectorAll("[data-omi-dock-config]"));
    const node = nodes[nodes.length - 1];
    if (!node) return {};

    try {
      return JSON.parse(node.textContent || "{}");
    } catch {
      return {};
    }
  }

  function setText(root, selector, value) {
    const node = root.querySelector(selector);
    if (node) node.textContent = value;
  }

  function setHidden(root, selector, hidden) {
    const node = root.querySelector(selector);
    if (node) node.hidden = hidden;
  }

  function setTone(root, tone) {
    const dot = root.querySelector("[data-omi-status-dot]");
    if (!dot) return;

    dot.className =
      "h-2 w-2 rounded-full " +
      (tone === "error"
        ? "bg-red-400"
        : tone === "asking"
          ? "bg-blue-400"
          : tone === "done"
            ? "bg-emerald-400"
            : "bg-slate-500");
  }

  function syncContext(root) {
    const payload = latestPayload();
    const context = asRecord(payload.context);
    const label = stringValue(context.label) || "目前標的";
    const labelNode = root.querySelector("[data-omi-context-label]");
    if (labelNode && labelNode.textContent !== label) labelNode.textContent = label;
    const contextKey = stringValue(payload.context_key) || "";
    if (root.getAttribute("data-omi-context-key") !== contextKey) {
      root.setAttribute("data-omi-context-key", contextKey);
    }
  }

  function setOpen(root, open) {
    setHidden(root, "[data-omi-open]", open);
    setHidden(root, "[data-omi-panel]", !open);
    if (open) syncContext(root);
  }

  function buildRoot(root) {
    root.className = "fixed bottom-4 right-4 z-50";
    root.style.zIndex = "2147483647";
    root.setAttribute("data-omi-version", SCRIPT_VERSION);
    root.setAttribute("data-omi-dock-root", "true");
    root.setAttribute("data-omi-bound", "portal");
    root.innerHTML = [
      '<button type="button" data-omi-open class="inline-flex h-11 items-center gap-2 border border-slate-900 bg-slate-950 px-3 text-sm font-black text-white shadow-lg transition hover:bg-red-700" aria-label="開啟 OMI 即時問答"><span class="h-2 w-2 rounded-full bg-red-400"></span><span>OMI 問答</span></button>',
      '<aside data-omi-panel hidden class="flex max-h-[calc(100vh-2rem)] w-[390px] max-w-[calc(100vw-2rem)] flex-col border border-slate-300 bg-white shadow-2xl">',
      '<header class="flex items-center justify-between border-b border-slate-200 bg-slate-950 py-2 pl-3 pr-3 text-white">',
      '<div><div class="text-[11px] font-semibold uppercase tracking-[0.22em] text-red-300">OMI</div><div class="text-sm font-bold">即時問答</div></div>',
      '<div class="flex items-center gap-2"><div class="relative"><button type="button" data-omi-status-toggle class="inline-flex max-w-[170px] items-center gap-1.5 text-xs text-slate-300 transition hover:text-white" aria-label="查看 OMI 處理訊號"><span data-omi-status-dot class="h-2 w-2 flex-none rounded-full bg-slate-500"></span><span data-omi-status class="truncate">待命</span></button><div data-omi-signal-popover hidden class="absolute right-0 top-7 z-10 w-72 max-w-[calc(100vw-2rem)] border border-slate-700 bg-slate-950 p-2 text-xs text-slate-200 shadow-2xl"><div class="mb-1 text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">Signals</div><div data-omi-signals class="space-y-1.5"></div></div></div><button type="button" data-omi-close class="grid h-7 w-7 place-items-center border border-slate-600 text-sm font-bold text-slate-200 hover:border-white hover:text-white" aria-label="收起 OMI 即時問答">-</button></div>',
      "</header>",
      '<div class="border-b border-slate-200 bg-slate-50 px-3 py-2"><div class="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">目前標的</div><div data-omi-context-label class="mt-0.5 truncate text-sm font-bold text-slate-950">目前標的</div></div>',
      '<div class="min-h-[220px] flex-1 overflow-y-auto px-3 py-3">',
      '<div data-omi-empty class="border border-dashed border-slate-300 bg-slate-50 px-3 py-4 text-sm text-slate-600">直接問 OMI 目前畫面上的標的或群組。系統會使用現有行情、技術、籌碼與基本面資料回覆，這裡只保留短期上下文。</div>',
      '<div data-omi-response hidden class="space-y-3"><div><div class="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">Question</div><div data-omi-question class="mt-1 border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-semibold text-slate-900"></div></div><div><div class="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">Answer</div><div data-omi-answer class="mt-1 min-h-[120px] border border-slate-200 bg-white px-3 py-2 text-sm leading-6 text-slate-900" aria-live="polite"></div></div></div>',
      '<div data-omi-error hidden class="mt-3 border border-red-200 bg-red-50 px-3 py-2 text-xs leading-5 text-red-700"></div>',
      "</div>",
      '<div class="border-t border-slate-200 px-3 py-2 text-xs text-slate-500"><span>資料 </span><span data-omi-source-count>0</span><span class="mx-2 text-slate-300">/</span><span>判斷 </span><span data-omi-tool-count>0</span></div>',
      '<div class="border-t border-slate-200 bg-slate-50 px-3 py-3"><div data-omi-preset-list class="mb-2 flex flex-wrap gap-1.5"></div><form data-omi-form="true" class="flex items-end gap-2"><textarea data-omi-input="true" rows="2" placeholder="輸入問題..." class="min-h-[44px] flex-1 resize-none border border-slate-300 bg-white px-3 py-2 text-sm text-slate-950 outline-none transition placeholder:text-slate-400 focus:border-slate-950"></textarea><button type="button" data-omi-stop hidden class="h-11 border border-slate-900 bg-white px-4 text-sm font-bold text-slate-950 hover:bg-slate-100">Stop</button><button type="submit" data-omi-submit class="h-11 bg-red-700 px-4 text-sm font-bold text-white hover:bg-slate-950 disabled:bg-slate-300">送出</button></form></div>',
      "</aside>",
    ].join("");

    const list = root.querySelector("[data-omi-preset-list]");
    if (list) {
      QUICK_QUESTIONS.forEach((item) => {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = item.label;
        button.setAttribute("data-omi-preset-question", item.question);
        button.setAttribute("data-omi-analysis-horizon", item.analysisHorizon);
        button.setAttribute("data-omi-strategy-profile", item.strategyProfile);
        button.setAttribute("data-omi-intent", item.intent);
        button.className =
          "border border-slate-300 bg-white px-2 py-1 text-xs font-semibold text-slate-700 hover:border-red-700 hover:text-red-700 disabled:border-slate-200 disabled:text-slate-400";
        list.appendChild(button);
      });
    }
  }

  function disableAskControls(root, disabled) {
    root.querySelectorAll("[data-omi-preset-question]").forEach((button) => {
      button.disabled = disabled;
    });
    const submit = root.querySelector("[data-omi-submit]");
    if (submit) submit.disabled = disabled;
  }

  function updateCounts(root) {
    const state = win.__omiAskDockState;
    const finalResponse = asRecord(state.finalResponse);
    const dataCount = Math.max(sourceCount(state.evidence || {}), responseSourceCount(finalResponse));
    const moduleCount = Math.max(state.toolRuns || 0, decisionModuleCount(finalResponse));
    setText(root, "[data-omi-source-count]", String(dataCount));
    setText(root, "[data-omi-tool-count]", String(moduleCount));
  }

  function resetForAsk(root, question) {
    const state = win.__omiAskDockState;
    state.evidence = {};
    state.toolRuns = 0;
    state.finalResponse = null;
    updateCounts(root);
    setOpen(root, true);
    setHidden(root, "[data-omi-empty]", true);
    setHidden(root, "[data-omi-response]", false);
    setHidden(root, "[data-omi-error]", true);
    setText(root, "[data-omi-question]", question);
    setPlainAnswer(root, "");
    setText(root, "[data-omi-error]", "");
    resetSignals(root);
    appendSignal(root, {
      stage: "queued",
      stage_label: "準備送出",
      message: "正在建立 OMI 請求與串流連線。",
      tone: "running",
    });
    setText(root, "[data-omi-status]", "準備中");
    setTone(root, "asking");
    const input = root.querySelector("[data-omi-input]");
    if (input) input.value = "";
  }

  function setError(root, message) {
    setHidden(root, "[data-omi-error]", false);
    setText(root, "[data-omi-error]", message || "OMI request failed.");
    setText(root, "[data-omi-status]", "發生錯誤");
    setTone(root, "error");
    appendSignal(root, {
      stage: "error",
      stage_label: "錯誤",
      message: message || "OMI request failed.",
      tone: "error",
    });
    disableAskControls(root, false);
    setHidden(root, "[data-omi-stop]", true);
  }

  async function ask(root, questionText, options = {}) {
    const question = String(questionText || "").trim();
    if (!question) return;

    const state = win.__omiAskDockState;
    const payload = latestPayload();
    const context = asRecord(payload.context);
    const target = asRecord(context.target);
    const analysisHorizon = stringValue(options.analysisHorizon) || "auto";
    const strategyProfile = stringValue(options.strategyProfile) || "short_term_momentum";
    const intent = stringValue(options.intent);
    let hasDelta = false;

    state.abortController?.abort();
    state.requestId += 1;
    const currentRequestId = state.requestId;
    const abortController = new AbortController();
    state.abortController = abortController;
    resetForAsk(root, question);
    disableAskControls(root, true);
    setHidden(root, "[data-omi-stop]", false);

    try {
      const response = await fetch(stringValue(payload.stream_path) || "/omi-data/ai/ask/stream", {
        method: "POST",
        headers: {
          Accept: "text/event-stream",
          "Content-Type": "application/json",
        },
        cache: "no-store",
        signal: abortController.signal,
        body: JSON.stringify({
          question,
          target,
          mode: "auto",
          caller_profile: "kuro_readonly",
          allow_llm: true,
          allow_write: false,
          allow_external_fetch: true,
          tool_budget: {
            max_calls: target.type === "us_stock" ? 5 : 4,
            max_external_fetches: target.type === "us_stock" ? 3 : 2,
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
            last_resolution: state.lastResolution,
            ui_context: {
              ...asRecord(context.uiContext),
              ask_intent: intent,
              analysis_horizon: analysisHorizon,
              strategy_profile: strategyProfile,
            },
          },
        }),
      });

      if (!response.ok) {
        throw new Error((await response.text()) || "OMI request failed.");
      }

      if (!response.body) {
        throw new Error("OMI did not return a readable stream.");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        if (currentRequestId !== state.requestId) return;

        buffer += decoder.decode(value, { stream: true });
        const blocks = buffer.split(/\r?\n\r?\n/);
        buffer = blocks.pop() || "";

        for (const block of blocks) {
          const message = parseSseBlock(block);
          if (!message) continue;

          const data = asRecord(message.data);
          if (message.event === "status") {
            const label = stageLabel(data.stage, data.stage_label);
            setText(root, "[data-omi-status]", label);
            appendSignal(root, {
              stage: stringValue(data.stage) || "status",
              stage_label: label,
              message: stringValue(data.message) || label,
              tone: "running",
            });
            setTone(root, "asking");
          } else if (message.event === "evidence") {
            state.evidence = data;
            updateCounts(root);
            appendSignal(root, {
              stage: "evidence",
              stage_label: "資料護照",
              message: "已取得 " + sourceCount(data) + " 個資料來源，可信度 " + (stringValue(data.trust_level) || "未標示") + "。",
              tone: "data",
            });
          } else if (message.event === "tool_run") {
            state.toolRuns += 1;
            updateCounts(root);
            appendSignal(root, {
              stage: "tool_run",
              stage_label: "工具執行",
              message: (stringValue(data.tool) || stringValue(data.name) || "工具") + "：" + (stringValue(data.status) || "已回傳"),
              tone: "tool",
            });
          } else if (message.event === "delta") {
            hasDelta = true;
            if (!state.responseSignalAdded) {
              appendSignal(root, {
                stage: "delta",
                stage_label: "回應串流",
                message: "開始輸出回答內容。",
                tone: "running",
              });
              state.responseSignalAdded = true;
            }
            appendPlainAnswer(root, stringValue(data.text) || "");
            setText(root, "[data-omi-status]", "回應中");
          } else if (message.event === "final") {
            const resolution = asRecord(data.resolution);
            if (Object.keys(resolution).length > 0) state.lastResolution = resolution;
            state.finalResponse = data;
            if (!renderStructuredAnswer(root, data) && !hasDelta) {
              setPlainAnswer(root, fallbackAnswer(data));
            }
            updateCounts(root);
            appendDecisionSignals(root, data);
            appendSignal(root, {
              stage: "final",
              stage_label: "渲染答案",
              message: "已收到完整回答資料並更新面板。",
              tone: "done",
            });
          } else if (message.event === "error") {
            appendSignal(root, {
              stage: "error",
              stage_label: "錯誤",
              message: stringValue(data.error) || stringValue(data.message) || "OMI request failed.",
              tone: "error",
            });
            throw new Error(stringValue(data.error) || stringValue(data.message) || "OMI request failed.");
          } else if (message.event === "done") {
            setText(root, "[data-omi-status]", data.ok === false ? "未完成" : "完成");
            setTone(root, data.ok === false ? "error" : "done");
            appendSignal(root, {
              stage: "done",
              stage_label: data.ok === false ? "未完成" : "完成",
              message: data.ok === false ? "OMI 串流未完成。" : "OMI 串流已完成。",
              tone: data.ok === false ? "error" : "done",
            });
          }
        }
      }
    } catch (error) {
      if (abortController.signal.aborted) return;
      setError(root, error instanceof Error ? error.message : "OMI request failed.");
    } finally {
      if (currentRequestId === state.requestId) {
        state.abortController = null;
        disableAskControls(root, false);
        setHidden(root, "[data-omi-stop]", true);
      }
    }
  }

  function install(root) {
    if (
      root.dataset.omiPortalInstalled === "true" &&
      root.getAttribute("data-omi-version") === SCRIPT_VERSION &&
      root.querySelector("[data-omi-open]") &&
      root.querySelector("[data-omi-panel]")
    ) {
      syncContext(root);
      return;
    }

    buildRoot(root);
    root.dataset.omiPortalInstalled = "true";
    syncContext(root);
    updateCounts(root);

    root.addEventListener("click", (event) => {
      const target = event.target instanceof Element ? event.target : null;
      if (target?.closest("[data-omi-open]")) {
        event.preventDefault();
        setOpen(root, true);
        return;
      }
      if (target?.closest("[data-omi-close]")) {
        event.preventDefault();
        setHidden(root, "[data-omi-signal-popover]", true);
        setOpen(root, false);
        return;
      }
      if (target?.closest("[data-omi-status-toggle]")) {
        event.preventDefault();
        toggleSignalPopover(root);
        return;
      }
      const preset = target?.closest("[data-omi-preset-question]");
      if (preset) {
        event.preventDefault();
        void ask(root, preset.getAttribute("data-omi-preset-question") || "", {
          analysisHorizon: preset.getAttribute("data-omi-analysis-horizon") || "auto",
          strategyProfile: preset.getAttribute("data-omi-strategy-profile") || "short_term_momentum",
          intent: preset.getAttribute("data-omi-intent") || "",
        });
        return;
      }
      const stop = target?.closest("[data-omi-stop]");
      if (stop) {
        const state = win.__omiAskDockState;
        event.preventDefault();
        state.requestId += 1;
        state.abortController?.abort();
        state.abortController = null;
        setText(root, "[data-omi-status]", "已停止");
        setTone(root, "idle");
        appendSignal(root, {
          stage: "stopped",
          stage_label: "已停止",
          message: "使用者已停止這次 OMI 串流。",
          tone: "error",
        });
        disableAskControls(root, false);
        setHidden(root, "[data-omi-stop]", true);
      }
    });

    root.addEventListener("submit", (event) => {
      const form = event.target instanceof HTMLFormElement ? event.target : null;
      if (form?.dataset.omiForm !== "true") return;
      event.preventDefault();
      ask(root, root.querySelector("[data-omi-input]")?.value || "");
    });

    root.addEventListener("keydown", (event) => {
      if (!(event.target instanceof HTMLTextAreaElement)) return;
      if (event.target.dataset.omiInput !== "true") return;
      if (event.key !== "Enter" || event.shiftKey) return;
      event.preventDefault();
      ask(root, event.target.value || "");
    });
  }

  function bootstrap() {
    const state =
      win.__omiAskDockState ||
      (win.__omiAskDockState = {
        requestId: 0,
        abortController: null,
        evidence: {},
        toolRuns: 0,
        signals: [],
        responseSignalAdded: false,
        finalResponse: null,
        lastResolution: null,
      });
    let root = document.getElementById("omi-ask-dock-portal");
    if (
      root &&
      (
        root.getAttribute("data-omi-version") !== SCRIPT_VERSION ||
        !root.querySelector("[data-omi-open]") ||
        !root.querySelector("[data-omi-panel]")
      )
    ) {
      root.remove();
      root = null;
    }
    if (!root) {
      root = document.createElement("div");
      root.id = "omi-ask-dock-portal";
      document.body.appendChild(root);
    }
    install(root);
    syncContext(root);

    if (state.contextSyncTimer) window.clearInterval(state.contextSyncTimer);
    state.contextSyncTimer = window.setInterval(() => {
      const currentRoot = document.getElementById("omi-ask-dock-portal");
      if (currentRoot) {
        syncContext(currentRoot);
        return;
      }

      bootstrap();
    }, 1000);
  }

  win.__omiAskDockBootstrap = bootstrap;
  win.__omiAskDockScriptVersion = SCRIPT_VERSION;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootstrap, { once: true });
  } else {
    bootstrap();
  }
})();
`;

function escapeJsonForScript(value: unknown) {
  return JSON.stringify(value).replace(/</g, "\\u003c");
}

type OmiAskDockRuntimeWindow = Window & {
  __omiAskDockBootstrap?: () => void;
  __omiAskDockScriptVersion?: string;
};

function ensureOmiAskDockPortal() {
  const runtimeWindow = window as OmiAskDockRuntimeWindow;

  if (
    typeof runtimeWindow.__omiAskDockBootstrap === "function" &&
    runtimeWindow.__omiAskDockScriptVersion === OMI_ASK_DOCK_VERSION
  ) {
    runtimeWindow.__omiAskDockBootstrap();
    return;
  }

  const script = document.createElement("script");
  script.text = OMI_ASK_DOCK_SCRIPT;
  document.body.appendChild(script);
  script.remove();

  if (typeof runtimeWindow.__omiAskDockBootstrap === "function") {
    runtimeWindow.__omiAskDockBootstrap();
  }
}

export default function OmiAskDock({ context }: { context: OmiAskDockContext }) {
  const contextKey = `${context.market}:${context.target.type}:${context.target.id ?? ""}:${context.label}`;
  const payload = {
    context_key: contextKey,
    context,
    stream_path: `${API_PROXY_PATH}/ai/ask/stream`,
  };

  useEffect(() => {
    ensureOmiAskDockPortal();
  }, [contextKey]);

  return (
    <>
      <script
        type="application/json"
        data-omi-dock-config
        data-omi-context-key={contextKey}
        dangerouslySetInnerHTML={{ __html: escapeJsonForScript(payload) }}
      />
      <script dangerouslySetInnerHTML={{ __html: OMI_ASK_DOCK_SCRIPT }} />
    </>
  );
}
