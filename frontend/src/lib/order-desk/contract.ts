/** Projection of ExecutionApplication / ExecutionRuntime v1 source contracts.
 * No broker reducer, quantity accounting, strategy policy or position store here.
 */
export const DESK_CONTRACT = "omi.order-desk.fake.v1" as const;
export type Space = "USER_SPACE" | "AGENT_SPACE";
export type Command = {
  account_id: string; trade_date: string; request_id: string; intent_id: string;
  symbol: string; action: "Buy" | "Sell"; quantity: number; price: string;
  condition: string; lot: string; shares_per_unit: number; space_id: Space;
  strategy_id: string | null; revision: number | null;
};
export type Draft = { command: Command; owner_id: string; source: string };
export type AuditEvent = { seq: number; kind: string; occurred_at: string; payload: Record<string, unknown> };
export type Order = {
  execution_id: string; intent_id: string; request_id: string; space_id: Space;
  strategy_id: string | null; revision: number | null; broker_order_id: string | null;
  trade_date: string; state: string; filled_shares: number; quantity: number;
  submit_stage: string; cancel_stage: string | null; reconcile_required: boolean;
  fills: { fill_id: string; quantity: number; price: string; source_time: string }[];
};
export type Review = {
  review_id: string; review_revision: number; state: "DRAFT" | "PREVIEW" | "REJECTED" | "CONFIRMED" | "EXECUTION";
  draft: Draft; confirmed_at: string | null; execution_id: string | null;
  snapshot: { digest: string; review_id: string; review_revision: number; draft: Draft;
    previewed_at: string; order_semantics: { order_kind: string; time_in_force: string; quantity_unit: string; broker_quantity: number } } | null;
  execution: Order | null; audit: AuditEvent[]; execution_audit: AuditEvent[];
};
export type Rules = { stop_loss: string | null; take_profit: string | null; exit_limit_price: string; protection_mode: "LOCAL_SYNTHETIC" };
export type Source = { source_id: string; observed_at: string; content: Record<string, unknown> };
export type Strategy = {
  strategy_id: string; strategy_revision: number; review_id: string; review_digest: string;
  rules: Rules; state: string; protection_mode: "LOCAL_SYNTHETIC";
  broker_native_protection: "NOT_SUPPORTED"; source_snapshot: Source & { digest: string };
  consent_policy: string; price_input: string; strategy_error: string | null;
  entry_filled: number; exit_filled: number; entry_remaining: number | null;
  effective_position: number; protected_quantity: number; reserved_exit_quantity: number;
  target_position: number | null; unresolved_exit_claims: string[]; reconcile_required: boolean;
  fill_history_complete: boolean; entry: Order; exits: Order[];
};
export type DeskSnapshot = {
  contract: typeof DESK_CONTRACT; mode: "FAKE_ONLY"; live_broker: "NOT_DEPLOYED";
  session_id: string; account_id: string; trade_date: string;
  reviews: Review[]; strategies: Strategy[];
  broker_snapshot: { status: "AVAILABLE" | "PARTIAL" | "UNAVAILABLE"; reconcile_required?: boolean;
    fill_history_complete?: boolean; invalid_report_count?: number; diagnostics?: unknown[] };
  scenario: { strategy_id: string; completed_steps: number; next_step: string | null };
};
type ReviewSelector = { review_id: string; expected_revision: number };
export type DeskCommand =
  | ({ type: "confirm"; expected_digest: string } & ReviewSelector)
  | ({ type: "preview" } & ReviewSelector)
  | ({ type: "reject"; reason: string } & ReviewSelector)
  | ({ type: "revise"; draft: Draft } & ReviewSelector)
  | { type: "cancel"; execution_id: string; key: { account_id: string; trade_date: string; order_id: string } }
  | { type: "create_strategy"; review_id: string; expected_digest: string; rules: Rules; source: Source }
  | { type: "revise_strategy"; strategy_id: string; expected_revision: number; request_id: string; rules: Rules; source: Source }
  | { type: "query" }
  | { type: "fake_submit_unknown" }
  | { type: "fake_step"; step: string }
  | { type: "fake_snapshot"; status: "AVAILABLE" | "PARTIAL" | "UNAVAILABLE" };

/** Reject protocol/mode mismatch before presenting any actionable data. */
export function readDeskSnapshot(value: unknown): DeskSnapshot {
  const record = (item: unknown): item is Record<string, unknown> => !!item && typeof item === "object" && !Array.isArray(item);
  const integer = (item: unknown) => Number.isInteger(item) && Number(item) >= 0;
  const texts = (item: Record<string, unknown>, keys: string[]) => keys.every(key => typeof item[key] === "string");
  const array = (item: unknown, check: (item: unknown) => boolean) => Array.isArray(item) && item.every(check);
  const nullableText = (item: unknown) => item === null || typeof item === "string";
  const isCommand = (item: unknown): boolean => record(item)
    && texts(item, ["account_id", "trade_date", "request_id", "intent_id", "symbol", "price", "condition", "lot"])
    && ["Buy", "Sell"].includes(String(item.action)) && ["USER_SPACE", "AGENT_SPACE"].includes(String(item.space_id))
    && integer(item.quantity) && integer(item.shares_per_unit) && nullableText(item.strategy_id)
    && (item.revision === null || integer(item.revision));
  const isDraft = (item: unknown): boolean => record(item) && texts(item, ["owner_id", "source"]) && isCommand(item.command);
  const isOrder = (item: unknown): boolean => record(item) && texts(item, ["execution_id", "trade_date", "state", "submit_stage"])
    && nullableText(item.broker_order_id) && nullableText(item.cancel_stage) && typeof item.reconcile_required === "boolean"
    && integer(item.filled_shares) && integer(item.quantity) && array(item.fills, fill => record(fill)
      && texts(fill, ["fill_id", "price", "source_time"]) && integer(fill.quantity));
  const isEvent = (item: unknown): boolean => record(item) && integer(item.seq)
    && texts(item, ["kind", "occurred_at"]) && record(item.payload);
  const isReview = (item: unknown): boolean => {
    if (!record(item) || !texts(item, ["review_id"]) || !integer(item.review_revision)
      || !["DRAFT", "PREVIEW", "REJECTED", "CONFIRMED", "EXECUTION"].includes(String(item.state))
      || !isDraft(item.draft) || !nullableText(item.execution_id)
      || !(item.execution === null || isOrder(item.execution)) || !array(item.audit, isEvent) || !array(item.execution_audit, isEvent)) return false;
    if (item.snapshot === null) return item.state === "DRAFT" || item.state === "REJECTED";
    const snap = item.snapshot;
    if (!record(snap) || snap.review_id !== item.review_id || snap.review_revision !== item.review_revision
      || !/^[0-9a-f]{64}$/.test(String(snap.digest)) || !isDraft(snap.draft) || !record(snap.order_semantics)
      || !texts(snap.order_semantics, ["order_kind", "time_in_force", "quantity_unit"]) || !integer(snap.order_semantics.broker_quantity)) return false;
    const draft = item.draft as Draft;
    const saved = snap.draft as Draft;
    return draft.owner_id === saved.owner_id && draft.source === saved.source
      && Object.keys(draft.command).every(key => draft.command[key as keyof Command] === saved.command[key as keyof Command]);
  };
  const isStrategy = (item: unknown): boolean => record(item)
    && texts(item, ["strategy_id", "review_id", "review_digest", "state", "consent_policy", "price_input"])
    && integer(item.strategy_revision) && isOrder(item.entry) && array(item.exits, isOrder)
    && ["entry_filled", "exit_filled", "effective_position", "protected_quantity", "reserved_exit_quantity"].every(key => integer(item[key]))
    && (item.entry_remaining === null || integer(item.entry_remaining)) && (item.target_position === null || integer(item.target_position))
    && typeof item.reconcile_required === "boolean" && typeof item.fill_history_complete === "boolean"
    && array(item.unresolved_exit_claims, claim => typeof claim === "string") && nullableText(item.strategy_error)
    && item.protection_mode === "LOCAL_SYNTHETIC" && item.broker_native_protection === "NOT_SUPPORTED"
    && record(item.rules) && nullableText(item.rules.stop_loss) && nullableText(item.rules.take_profit)
    && typeof item.rules.exit_limit_price === "string" && item.rules.protection_mode === "LOCAL_SYNTHETIC"
    && record(item.source_snapshot) && texts(item.source_snapshot, ["source_id", "observed_at", "digest"])
    && record(item.source_snapshot.content);
  if (!record(value) || value.contract !== DESK_CONTRACT || value.mode !== "FAKE_ONLY" || value.live_broker !== "NOT_DEPLOYED"
    || !texts(value, ["session_id", "account_id", "trade_date"]) || !array(value.reviews, isReview) || !array(value.strategies, isStrategy)
    || !record(value.broker_snapshot) || !["AVAILABLE", "PARTIAL", "UNAVAILABLE"].includes(String(value.broker_snapshot.status))
    || !record(value.scenario) || typeof value.scenario.strategy_id !== "string" || !integer(value.scenario.completed_steps)
    || !nullableText(value.scenario.next_step)) {
    throw new Error("INVALID_EXECUTION_CONTRACT");
  }
  return value as DeskSnapshot;
}
