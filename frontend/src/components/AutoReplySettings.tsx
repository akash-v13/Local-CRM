import { useState } from "react";
import { Link } from "react-router";

import { api, errorMessage } from "../api/client";
import type { QueueSettings } from "../api/types";
import { formatCaseNumber } from "../lib/format";
import { useLoad } from "../lib/useLoad";
import { Field } from "./Field";

/** The standard reply the backend starts with (schemas.DEFAULT_AUTO_REPLY). */
export const DEFAULT_AUTO_REPLY =
  "Hi {{customer.first_name}},\n\n" +
  "Thank you for getting in touch about {{case.order}}, and I'm sorry for the trouble. " +
  "{{compensation.sentence}}\n\n" +
  "If there's anything else I can help with, just reply to this message.\n\n" +
  "Best regards,\n{{business.name}}";

export const PLACEHOLDERS: { path: string; label: string }[] = [
  { path: "customer.first_name", label: "First name (or \"there\")" },
  { path: "customer.name", label: "Full name" },
  { path: "case.order", label: "\"order NW-10211\" (or \"your order\")" },
  { path: "case.order_number", label: "Order number only" },
  { path: "compensation.sentence", label: "\"Here's what we've done: …\" (or nothing)" },
  { path: "compensation.label", label: "What was given, e.g. a voucher code" },
  { path: "case.number", label: "Case number" },
  { path: "business.name", label: "Your business name" },
];

interface Props {
  tenantId: string;
  settings: QueueSettings;
  onChange: (patch: Partial<QueueSettings>) => void;
}

/**
 * The queue editor's "Automatic replies" section: on/off, standard reply or
 * AI-written, how long to wait, and the standard reply with a live preview.
 */
export function AutoReplySettings({ tenantId, settings, onChange }: Props) {
  const cases = useLoad(() => api.listCases(tenantId), [tenantId]);
  const [caseNumber, setCaseNumber] = useState("");
  const [preview, setPreview] = useState<string>();
  const [previewError, setPreviewError] = useState<string>();
  const hours = settings.auto_send_delay_minutes / 60;

  async function runPreview() {
    setPreview(undefined);
    setPreviewError(undefined);
    try {
      setPreview((await api.previewAutoReply(tenantId, Number(caseNumber), settings.auto_send_template)).reply);
    } catch (e) {
      setPreviewError(errorMessage(e));
    }
  }

  function insert(path: string) {
    const text = settings.auto_send_template;
    onChange({ auto_send_template: `${text}${text.endsWith(" ") || text.endsWith("\n") ? "" : " "}{{${path}}}` });
  }

  return (
    <div className="card form-card">
      <h2>Automatic replies</h2>
      <label className="checkbox">
        <input type="checkbox" checked={settings.auto_send} onChange={(e) => onChange({ auto_send: e.target.checked })} />
        Reply to new cases automatically
      </label>
      {settings.auto_send && (
        <>
          <p className="hint">
            The reply is written as soon as the case arrives and sent after the wait below, like a person would. Until
            then the case shows <strong>With AI</strong>, and anyone can <strong>Send now</strong> or <strong>Cancel</strong> it.
            It is held for a person instead when compensation needs approval or its payout failed, a complaint matched no
            compensation rule, the order number needs confirming, or the customer writes again.
          </p>
          <fieldset className="radio-stack">
            <legend className="small">How the reply is written</legend>
            <label className="checkbox">
              <input type="radio" name="auto-mode" checked={settings.auto_send_mode === "template"}
                onChange={() => onChange({ auto_send_mode: "template" })} />
              <span>Standard reply: your text, with the customer's name and case details filled in (no AI cost)</span>
            </label>
            <label className="checkbox">
              <input type="radio" name="auto-mode" checked={settings.auto_send_mode === "ai"} disabled={!settings.gen_ai_allowed}
                onChange={() => onChange({ auto_send_mode: "ai" })} />
              <span>
                Written by AI from your prompt templates
                {!settings.gen_ai_allowed && <span className="muted"> (turn on "Allow AI to draft replies" first)</span>}
              </span>
            </label>
            <p className="hint">AI replies follow your <Link to="/ops/templates">prompt templates</Link>: your voice, per queue and category.</p>
          </fieldset>
          <Field label={`Wait before sending: ${hours === 0 ? "send at once" : `${hours} hour${hours === 1 ? "" : "s"}`}`}>
            {(id) => (
              <input id={id} type="number" min={0} max={48} step="any" value={hours}
                onChange={(e) => onChange({ auto_send_delay_minutes: Math.round(Number(e.target.value || 0) * 60) })} />
            )}
          </Field>
          {settings.auto_send_mode === "template" && (
            <div className="auto-reply-template">
              <Field label="Standard reply">
                {(id) => (
                  <textarea id={id} rows={9} value={settings.auto_send_template}
                    onChange={(e) => onChange({ auto_send_template: e.target.value })} />
                )}
              </Field>
              <div className="placeholder-list small">
                <span className="muted">Insert:</span>
                {PLACEHOLDERS.map((p) => (
                  <button key={p.path} type="button" className="button small ghost" title={p.label} onClick={() => insert(p.path)}>
                    {`{{${p.path}}}`}
                  </button>
                ))}
                <button type="button" className="button small ghost" onClick={() => onChange({ auto_send_template: DEFAULT_AUTO_REPLY })}>
                  Reset to default
                </button>
              </div>
              <p className="hint">
                Order data works too, e.g. <code className="code-inline">{"{{enrichment.shopify.trackingNumber}}"}</code>; a case
                without it is held for a person rather than sent with a gap.
              </p>
              <div className="preview-row">
                <select aria-label="Preview with a case" value={caseNumber} onChange={(e) => setCaseNumber(e.target.value)}>
                  <option value="">Preview with a case…</option>
                  {(cases.data ?? []).slice(0, 30).map((c) => (
                    <option key={c.case_number} value={c.case_number}>{formatCaseNumber(c.case_number)} · {c.customer.email}</option>
                  ))}
                </select>
                <button type="button" className="button small secondary" disabled={!caseNumber} onClick={() => void runPreview()}>Preview</button>
              </div>
              {preview && <pre className="reply-preview">{preview}</pre>}
              {previewError && <p className="error small">{previewError}</p>}
            </div>
          )}
        </>
      )}
    </div>
  );
}
