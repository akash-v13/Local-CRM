import { useState } from "react";

import { api } from "../api/client";
import { formatUsd } from "../lib/format";
import { useLoad } from "../lib/useLoad";

/**
 * What drafts using this template cost per reply and per month on each model.
 * Uses measured usage from real drafts and test runs where available.
 */
export function CostProjectionPanel({ tenantId, templateName, refreshKey }: { tenantId: string; templateName: string; refreshKey: number }) {
  const [volume, setVolume] = useState("10000");
  const monthly = Math.max(1, Math.floor(Number(volume) || 1));
  const projection = useLoad(() => api.costProjection(tenantId, templateName, monthly), [tenantId, templateName, monthly, refreshKey]);

  return (
    <div className="cost-projection">
      <label className="inline-field">
        <span>Replies per month</span>
        <input type="number" min={1} value={volume} onChange={(e) => setVolume(e.target.value)} />
      </label>
      {projection.error && <p className="error">{projection.error}</p>}
      {projection.data && (
        <>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Model</th>
                  <th>Based on</th>
                  <th className="num">Tokens in / out</th>
                  <th className="num">Per reply</th>
                  <th className="num">Per 1,000</th>
                  <th className="num">Per month</th>
                </tr>
              </thead>
              <tbody>
                {projection.data.rows.map((r) => (
                  <tr key={r.model}>
                    <th scope="row">{r.label}</th>
                    <td>
                      {r.source === "measured" ? (
                        <span className="tag tag-accent">measured · {r.sample_size} drafts</span>
                      ) : (
                        <span className="tag">estimate</span>
                      )}
                    </td>
                    <td className="num">{Math.round(r.avg_input_tokens)} / {Math.round(r.avg_output_tokens)}</td>
                    <td className="num">{formatUsd(r.cost_per_reply_usd)}</td>
                    <td className="num">{formatUsd(r.cost_per_1000_usd)}</td>
                    <td className="num strong">{formatUsd(r.monthly_cost_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <ul className="notes small muted">
            {projection.data.notes.map((n) => <li key={n}>{n}</li>)}
          </ul>
        </>
      )}
    </div>
  );
}
