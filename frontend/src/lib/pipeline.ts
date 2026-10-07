/**
 * Turns the intake pipeline (or one case's run through it) into diagram nodes:
 *
 *   Case received → ⓪ read → ① Shopify order → ② connector → … → Routing → Compensation → Agent
 *
 * Steps run one after another. `uses` links a step to the earlier steps whose
 * data its request needs (from {{enrichment.<key>.<field>}} placeholders).
 */
import type { ExecutionDetail, PipelineDefinition, StepStatus } from "../api/types";
import { METHOD_SHORT, PAYOUT_STATUS_LABELS } from "./payouts";

export type NodeKind = "start" | "reader" | "connector" | "routing" | "compensation" | "end";
/** "done" = a non-connector stage that happened; "waiting" = not reached yet. */
export type NodeState = StepStatus | "done" | "waiting";

export interface FlowNode {
  id: string;
  kind: NodeKind;
  /** ⓪ for reading the message, ① ② ③ for connector steps. */
  number?: number;
  title: string;
  subtitle?: string;
  /** Short facts shown on the node. */
  facts: string[];
  /** Ids of earlier nodes whose data this one uses. */
  uses: string[];
  problems: string[];
  /** Only in an execution. */
  state?: NodeState;
  durationMs?: number | null;
}

export const STATE_LABELS: Record<NodeState, string> = {
  ok: "Succeeded",
  failed: "Failed",
  skipped: "Skipped",
  not_run: "Didn't run",
  pending: "Waiting to run",
  done: "Done",
  waiting: "Not reached",
};

export const STATE_ICONS: Record<NodeState, string> = {
  ok: "✓",
  failed: "✗",
  skipped: "↷",
  not_run: "–",
  pending: "…",
  done: "✓",
  waiting: "…",
};

export const stepId = (key: string) => `step:${key}`;

export const READER_LABELS: Record<string, string> = {
  jev: "Jev (TypeSafe AI)",
  claude: "Claude",
  patterns: "Patterns only (no AI key set)",
};

/** "jev-1.13.0" → "Jev (TypeSafe AI)", "claude-haiku-4-5" → "Claude (claude-haiku-4-5)". */
export function readerLabel(model: string): string {
  if (model.startsWith("jev")) return `Jev (TypeSafe AI)${model === "jev" ? "" : ` · ${model}`}`;
  if (model.startsWith("claude-")) return `Claude (${model})`;
  return READER_LABELS[model] ?? model;
}

/** "Shopify", "Stripe" or "Shopify and Stripe", from the payout methods in use. */
export function payoutProviders(methods: Partial<Record<string, string>>): string {
  const used = new Set(Object.values(methods).map((m) => (m?.startsWith("shopify") ? "Shopify" : "Stripe")));
  return [...used].sort().join(" and ") || "your provider";
}

const percent = (n: number | null) => (n === null ? "" : ` (${Math.round(n * 100)}%)`);

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** The business-wide pipeline every new case goes through. */
export function definitionNodes(d: PipelineDefinition): FlowNode[] {
  const keys = new Set([...d.connectors.map((c) => c.key), ...(d.shopify ? ["shopify"] : [])]);
  const nodes: FlowNode[] = [
    {
      id: "start",
      kind: "start",
      title: "Case received",
      subtitle: "Webform, email or API",
      facts: d.connectors.length || d.shopify ? ["Enrichment starts automatically"] : ["No connectors: routed straight away"],
      uses: [],
      problems: [],
    },
  ];
  if (d.reading) {
    nodes.push({
      id: "reader",
      kind: "reader",
      number: 0,
      title: "Read the message",
      subtitle: `${READER_LABELS[d.reading.model] ?? d.reading.model} · ${d.reading.channels.join(", ")} cases`,
      facts: [
        ...(d.reading.fields.length ? [`Finds: ${d.reading.fields.map((f) => f.label).join(", ")}`] : []),
        ...(d.reading.read_category ? ["Chooses the category from the tone and context"] : []),
        `Saves answers ≥ ${Math.round(d.reading.min_confidence * 100)}% confident; the rest go to an agent`,
      ],
      uses: [],
      problems: [],
    });
  }
  if (d.shopify) {
    nodes.push({
      id: stepId("shopify"),
      kind: "connector",
      number: 1,
      title: "Shopify order",
      subtitle: d.shopify.shop,
      facts: [
        `Finds the order by ${d.shopify.order_field}`,
        ...(d.shopify.match_by_email ? ["No order number: the customer's latest order, by email"] : []),
        "Saves order total, payment, delivery, tracking, days late",
      ],
      uses: [],
      problems: [],
    });
  }
  for (const c of d.connectors) {
    const facts = [
      `${c.method} ${shortUrl(c.url_template)}`,
      c.credential_name ? `Auth: ${c.credential_name}` : "No authentication",
      c.fields.length ? `Saves ${plural(c.fields.length, "field")}` : "Saves nothing yet",
      c.run_when.length ? `Runs when: ${c.run_when.join(c.run_when_match === "any" ? " or " : " and ")}` : "Runs for every case",
    ];
    if (c.required) facts.push("Required: a failure stops the case");
    nodes.push({
      id: stepId(c.key),
      kind: "connector",
      number: c.position,
      title: c.name,
      subtitle: c.description ?? undefined,
      facts,
      uses: [...new Set(c.uses.filter((u) => u.source === "step" && keys.has(u.step_key ?? "")).map((u) => stepId(u.step_key ?? "")))],
      problems: c.problems,
    });
  }
  nodes.push(
    {
      id: "routing",
      kind: "routing",
      title: "Routing",
      subtitle: "First matching queue wins",
      facts: d.queues.map((q) => `${q.name}${q.conditions.length ? `: ${q.conditions.join(q.match === "any" ? " or " : " and ")}` : ": every case"}`),
      uses: [],
      problems: d.queues.length ? [] : ["No active queues: cases will be left unrouted."],
    },
    {
      id: "compensation",
      kind: "compensation",
      title: "Compensation",
      subtitle: d.compensation_rules.length ? "First matching rule decides" : "No rules: no decision is made",
      facts: [
        ...d.compensation_rules.map((r) => `${r.name} → ${r.outcome}`),
        ...(d.payouts ? [`Approved: issued through ${payoutProviders(d.payouts.methods)}${d.payouts.auto_pay ? " automatically" : " when an agent clicks Issue"}`] : []),
      ],
      uses: [],
      problems: [],
    },
    {
      id: "end",
      kind: "end",
      title: "Ready for an agent",
      subtitle: "Agent reviews, drafts with AI, replies",
      facts: d.queues.filter((q) => q.ai_drafting).map((q) => `AI drafting on in ${q.name}`),
      uses: [],
      problems: [],
    },
  );
  return nodes;
}

/** One case's run, on today's pipeline (plus steps since removed). */
export function executionNodes(d: PipelineDefinition, e: ExecutionDetail): FlowNode[] {
  const base = definitionNodes(d);
  const byId = new Map(base.map((n) => [n.id, n]));
  const enriching = e.outcome === "in_progress";
  const steps: FlowNode[] = e.steps.map((s) => ({
    ...(byId.get(stepId(s.key)) ?? { id: stepId(s.key), kind: "connector" as const, title: s.name, facts: ["Removed from the pipeline since"], uses: [], problems: [] }),
    number: s.position ?? undefined,
    state: s.status,
    durationMs: s.duration_ms,
    facts: stepFacts(s),
    problems: [],
  }));
  const routed = !!e.routing.queue_name;
  const decision = e.compensation;
  const reader = byId.get("reader");
  const r = e.reading;
  const readerNode: FlowNode[] = r
    ? [{
        ...(reader ?? { id: "reader", kind: "reader" as const, number: 0, title: "Read the message", facts: [], uses: [], problems: [] }),
        subtitle: readerLabel(r.model),
        state: r.status === "failed" ? "failed" : "ok",
        durationMs: r.latency_ms,
        facts: [
          ...r.fields.map((f) =>
            f.status === "found" ? `${f.label}: ${f.value}${percent(f.confidence)}`
            : f.status === "needs_review" ? `${f.label}: needs an agent (${f.candidates.length} candidates)`
            : `${f.label}: not in the message`),
          ...(r.category ? [`Category: ${r.category.label}${percent(r.category.confidence)}${r.category.applied ? "" : " (suggested)"}`] : []),
          ...(r.error ? [r.error] : []),
        ],
      }]
    : reader ? [{ ...reader, state: "skipped" as const, facts: ["Not needed for this case (nothing missing, or channel not read)"] }] : [];
  return [
    { ...byId.get("start")!, state: "done", facts: [`${e.customer_name ?? e.customer_email}`, e.category] },
    ...readerNode,
    ...steps,
    {
      ...byId.get("routing")!,
      state: routed ? "done" : enriching ? "waiting" : "failed",
      facts: routed
        ? [`→ ${e.routing.queue_name}`, ...(e.routing.matched_conditions.length ? e.routing.matched_conditions : ["Catch-all (no conditions)"])]
        : [enriching ? "Waits for enrichment" : "No queue matched"],
      problems: [],
    },
    {
      ...byId.get("compensation")!,
      state: decision ? "done" : routed ? "skipped" : "waiting",
      facts: decision
        ? decision.status === "no_match"
          ? ["No rule matched"]
          : [
              decision.label ?? "No compensation",
              ...(decision.rule_name ? [`Rule: ${decision.rule_name}`] : []),
              statusText(decision.status),
              ...(decision.payout ? [`${METHOD_SHORT[decision.payout.method]}: ${PAYOUT_STATUS_LABELS[decision.payout.status].toLowerCase()}`] : []),
            ]
        : [routed ? "No rules when this case was routed" : "Not reached"],
      problems: [],
    },
    {
      ...byId.get("end")!,
      state: routed ? "done" : "waiting",
      facts: [`Case status: ${e.case_status}`],
      problems: [],
    },
  ];
}

function stepFacts(s: ExecutionDetail["steps"][number]): string[] {
  const facts: string[] = [];
  if (s.http_status) facts.push(`HTTP ${s.http_status}`);
  if (s.status === "ok") facts.push(`Saved ${plural(Object.keys(s.data).length, "field")}`);
  if (s.error) facts.push(s.error);
  if (s.missing.length) facts.push(`Missing in response: ${s.missing.join(", ")}`);
  return facts;
}

function statusText(status: string): string {
  return status.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}

/** "http://mocks:8100/orders/{{case.attributes.orderNumber}}" → "mocks:8100/orders/{{…orderNumber}}" */
export function shortUrl(url: string): string {
  return url.replace(/^https?:\/\//, "").replace(/\{\{\s*[\w.]*?([\w]+)\s*\}\}/g, "{{…$1}}");
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "";
  if (ms < 1) return "<1 ms";
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}
