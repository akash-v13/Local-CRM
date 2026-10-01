import type { DraftInfo } from "../api/types";
import { formatUsd } from "../lib/format";

const MODEL_LABELS: Record<string, string> = {
  "claude-haiku-4-5": "Claude Haiku 4.5",
  "claude-sonnet-5": "Claude Sonnet 5",
  "claude-opus-5": "Claude Opus 5",
};

export function modelLabel(id: string): string {
  return MODEL_LABELS[id] ?? id;
}

/** Checks as compact pass/fail badges (icon + text, never color alone). */
export function CheckBadges({ checks }: { checks: DraftInfo["checks"] }) {
  if (checks.length === 0) return null;
  return (
    <ul className="check-badges">
      {checks.map((c, i) => (
        <li key={i} className={c.passed ? "pass" : "fail"}>
          <span aria-hidden>{c.passed ? "✓" : "✗"}</span> {c.detail}
        </li>
      ))}
    </ul>
  );
}

interface Props {
  info: DraftInfo;
  /** The agent has changed the draft text in the reply box. */
  edited: boolean;
  onDiscard: () => void;
}

/**
 * Shown above the reply box after "Draft with AI": what produced the draft,
 * what it cost, and anything the agent must check before sending.
 */
export function DraftPanel({ info, edited, onDiscard }: Props) {
  return (
    <div className="draft-panel" role="status">
      <div className="draft-panel-head">
        <strong>✨ AI draft</strong>
        <span className="muted small">
          {modelLabel(info.served_by)} ·{" "}
          {formatUsd(info.cost_usd)} · {(info.latency_ms / 1000).toFixed(1)}s
        </span>
        {edited && <span className="tag">edited</span>}
        <button type="button" className="button small ghost" onClick={onDiscard}>
          Discard
        </button>
      </div>
      {info.needs_attention && (
        <p className="draft-alert">
          <span aria-hidden>⚠ </span>
          <strong>Needs your attention:</strong> {info.attention_reason || "the model flagged this case."}
        </p>
      )}
      {info.warnings.map((w, i) => (
        <p key={i} className="draft-alert">
          <span aria-hidden>⚠ </span>
          {w}
        </p>
      ))}
      <CheckBadges checks={info.checks} />
      <p className="muted small">
        Templates:{" "}
        {info.templates.map((t, i) => (
          <span key={t.layer}>
            {i > 0 && " + "}
            <code className="code-inline">{t.name}</code>
            {t.version !== null && ` v${t.version}`}
          </span>
        ))}
      </p>
      {info.facts_used.length > 0 && (
        <p className="muted small">Based on: {info.facts_used.join("; ")}</p>
      )}
      <p className="hint">Review and edit below, then send. Nothing is sent automatically.</p>
    </div>
  );
}
