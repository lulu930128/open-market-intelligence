export type OmiAskTarget = {
  type: "auto" | "market" | "data_freshness" | "tw_stock" | "tw_watchlist" | "us_stock" | string;
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

const OMI_ASK_DOCK_SCRIPT = String.raw`
(() => {
  const win = window;
  const SCRIPT_VERSION = "omi-dock-consumer-risk-v2";

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

  function appendActionPlan(parent, actions) {
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
      node("div", "text-[11px] font-bold uppercase tracking-[0.18em] text-slate-400", "怎麼做")
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

  function renderStructuredAnswer(root, response) {
    const answer = answerContainer(root);
    if (!answer) return false;

    const consumer = consumerAnswer(response);
    const headline = stringValue(consumer.headline);
    if (!headline) return false;

    answer.classList.remove("whitespace-pre-wrap");
    answer.replaceChildren();

    const wrapper = node("div", "space-y-3");
    const header = node("div", "border-l-4 border-red-600 bg-slate-50 px-3 py-2");
    header.appendChild(node("div", "text-[11px] font-bold uppercase tracking-[0.18em] text-slate-400", "結論"));
    header.appendChild(node("div", "mt-1 text-base font-black leading-6 text-slate-950", headline));
    const meta = node("div", "mt-2 flex flex-wrap gap-1.5");
    appendPill(meta, "方向", stringValue(consumer.stance_label));
    appendPill(meta, "信心", stringValue(consumer.confidence_label));
    if (meta.childNodes.length) header.appendChild(meta);
    wrapper.appendChild(header);

    appendTextList(wrapper, "三個重點", textItems(consumer.summary, 3));
    appendActionPlan(wrapper, consumer.action_plan);
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
      '<button type="button" data-omi-open class="grid h-12 w-12 place-items-center border border-slate-900 bg-slate-950 text-sm font-black text-white shadow-lg transition hover:bg-red-700" aria-label="開啟 OMI 即時問答">O</button>',
      '<aside data-omi-panel hidden class="flex max-h-[calc(100vh-2rem)] w-[390px] max-w-[calc(100vw-2rem)] flex-col border border-slate-300 bg-white shadow-2xl">',
      '<header class="flex items-center justify-between border-b border-slate-200 bg-slate-950 py-2 pl-3 pr-3 text-white">',
      '<div><div class="text-[11px] font-semibold uppercase tracking-[0.22em] text-red-300">OMI</div><div class="text-sm font-bold">即時問答</div></div>',
      '<div class="flex items-center gap-3"><span class="inline-flex items-center gap-1.5 text-xs text-slate-300"><span data-omi-status-dot class="h-2 w-2 rounded-full bg-slate-500"></span><span data-omi-status>待命</span></span><button type="button" data-omi-close class="grid h-7 w-7 place-items-center border border-slate-600 text-sm font-bold text-slate-200 hover:border-white hover:text-white" aria-label="收起 OMI 即時問答">-</button></div>',
      "</header>",
      '<div class="border-b border-slate-200 bg-slate-50 px-3 py-2"><div class="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">目前標的</div><div data-omi-context-label class="mt-0.5 truncate text-sm font-bold text-slate-950">目前標的</div></div>',
      '<div class="min-h-[220px] flex-1 overflow-y-auto px-3 py-3">',
      '<div data-omi-empty class="border border-dashed border-slate-300 bg-slate-50 px-3 py-4 text-sm text-slate-600">直接問 OMI 目前畫面上的標的或群組。系統會使用現有行情、技術、籌碼與基本面資料回覆，這裡只保留短期上下文。</div>',
      '<div data-omi-response hidden class="space-y-3"><div><div class="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">Question</div><div data-omi-question class="mt-1 border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-semibold text-slate-900"></div></div><div><div class="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">Answer</div><div data-omi-answer class="mt-1 min-h-[120px] border border-slate-200 bg-white px-3 py-2 text-sm leading-6 text-slate-900" aria-live="polite"></div></div></div>',
      '<div data-omi-error hidden class="mt-3 border border-red-200 bg-red-50 px-3 py-2 text-xs leading-5 text-red-700"></div>',
      "</div>",
      '<div class="border-t border-slate-200 px-3 py-2 text-xs text-slate-500"><span>資料 </span><span data-omi-source-count>0</span><span class="mx-2 text-slate-300">/</span><span>工具 </span><span data-omi-tool-count>0</span></div>',
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
    setText(root, "[data-omi-source-count]", String(sourceCount(state.evidence || {})));
    setText(root, "[data-omi-tool-count]", String(state.toolRuns || 0));
  }

  function resetForAsk(root, question) {
    const state = win.__omiAskDockState;
    state.evidence = {};
    state.toolRuns = 0;
    updateCounts(root);
    setOpen(root, true);
    setHidden(root, "[data-omi-empty]", true);
    setHidden(root, "[data-omi-response]", false);
    setHidden(root, "[data-omi-error]", true);
    setText(root, "[data-omi-question]", question);
    setPlainAnswer(root, "");
    setText(root, "[data-omi-error]", "");
    setText(root, "[data-omi-status]", "連線中");
    setTone(root, "asking");
    const input = root.querySelector("[data-omi-input]");
    if (input) input.value = "";
  }

  function setError(root, message) {
    setHidden(root, "[data-omi-error]", false);
    setText(root, "[data-omi-error]", message || "OMI request failed.");
    setText(root, "[data-omi-status]", "發生錯誤");
    setTone(root, "error");
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
            setText(root, "[data-omi-status]", stringValue(data.message) || "處理中");
            setTone(root, "asking");
          } else if (message.event === "evidence") {
            state.evidence = data;
            updateCounts(root);
          } else if (message.event === "tool_run") {
            state.toolRuns += 1;
            updateCounts(root);
          } else if (message.event === "delta") {
            hasDelta = true;
            appendPlainAnswer(root, stringValue(data.text) || "");
            setText(root, "[data-omi-status]", "回應中");
          } else if (message.event === "final") {
            const resolution = asRecord(data.resolution);
            if (Object.keys(resolution).length > 0) state.lastResolution = resolution;
            if (!renderStructuredAnswer(root, data) && !hasDelta) {
              setPlainAnswer(root, fallbackAnswer(data));
            }
            updateCounts(root);
          } else if (message.event === "error") {
            throw new Error(stringValue(data.error) || stringValue(data.message) || "OMI request failed.");
          } else if (message.event === "done") {
            setText(root, "[data-omi-status]", data.ok === false ? "未完成" : "完成");
            setTone(root, data.ok === false ? "error" : "done");
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
        setOpen(root, false);
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
      if (currentRoot) syncContext(currentRoot);
    }, 1000);
  }

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

export default function OmiAskDock({ context }: { context: OmiAskDockContext }) {
  const contextKey = `${context.market}:${context.target.type}:${context.target.id ?? ""}:${context.label}`;
  const payload = {
    context_key: contextKey,
    context,
    stream_path: `${API_PROXY_PATH}/ai/ask/stream`,
  };

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
