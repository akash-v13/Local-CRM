import { useState } from "react";
import { Link } from "react-router";

import { api, errorMessage } from "../api/client";
import type { CompensationRuleInput, SimulationResult } from "../api/types";
import { formatCaseNumber } from "../lib/format";

interface Props {
  tenantId: string;
  /** In the rule editor: the unsaved rule to include, or null if the form isn't valid. */
  buildDraft?: () => CompensationRuleInput | null;
  draftRuleId?: string;
}

/**
 * Backtest: "what would the matrix have decided for recent cases, and what
 * would it cost?" Runs the real decision logic over past cases, oldest first,
 * as if the rules had been live. Nothing is changed.
 */
export function SimulationPanel({ tenantId, buildDraft, draftRuleId }: Props) {
  const [days, setDays] = useState(90);
  const [result, setResult] = useState<SimulationResult>();
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  async function run() {
    setError(undefined);
    const draft = buildDraft ? buildDraft() : undefined;
    if (draft === null) {
      setError("Fix the highlighted fields above first.");
      return;
    }
    setBusy(true);
    try {
      setResult(await api.simulateCompensation(tenantId, { days, draft, draft_rule_id: draftRuleId }));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  const money = (n: number) => `${result?.currency ?? ""} ${n.toFixed(2)}`;

  return (
    <div className="simulation">
      <div className="inline-form wrap">
        <label className="inline-field">
          <span>Cases from the last</span>
          <select value={days} onChange={(e) => { setDays(Number(e.target.value)); setResult(undefined); }}>
            {[7, 30, 90, 180, 365].map((d) => <option key={d} value={d}>{d} days</option>)}
          </select>
        </label>
        <button type="button" className="button small" disabled={busy} onClick={() => void run()}>
          {busy ? "Running…" : "Run backtest"}
        </button>
      </div>
      {error && <p className="error pre-line" role="alert">{error}</p>}
      {result && (
        <>
          <div className="stat-row">
            <div className="stat-tile"><span className="stat-label">Cases checked</span><span className="stat-value">{result.cases_checked}</span></div>
            <div className="stat-tile"><span className="stat-label">Would be compensated</span><span className="stat-value">{result.cases_matched}</span></div>
            <div className="stat-tile"><span className="stat-label">Need approval</span><span className="stat-value">{result.needs_approval}</span></div>
            <div className="stat-tile"><span className="stat-label">Total cost</span><span className="stat-value">{money(result.total_amount)}</span></div>
          </div>
          {result.rows.length > 0 && (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Rule</th>
                    <th className="num">Cases</th>
                    <th className="num">Need approval</th>
                    <th className="num">Total</th>
                    <th>Examples</th>
                  </tr>
                </thead>
                <tbody>
                  {result.rows.map((r) => (
                    <tr key={`${r.rule_id ?? "draft"}-${r.rule_name}`}>
                      <th scope="row">{r.rule_name}{r.is_draft && <span className="tag">your changes</span>}</th>
                      <td className="num">{r.cases}</td>
                      <td className="num">{r.needs_approval}</td>
                      <td className="num strong">{money(r.total_amount)}</td>
                      <td className="small">
                        {r.example_case_numbers.map((n, i) => (
                          <span key={n}>{i > 0 && ", "}<Link to={`/cases/${n}`}>{formatCaseNumber(n)}</Link></span>
                        ))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="hint">
            {result.cases_checked - result.cases_matched} case(s) matched no rule. Each compensation counts toward the
            customer's repeat-claim history for later cases, as it would have live. Uses the cases' current data.
          </p>
        </>
      )}
    </div>
  );
}
