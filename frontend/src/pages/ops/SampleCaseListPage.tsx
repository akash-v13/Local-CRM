import { Link, useNavigate } from "react-router";

import { api } from "../../api/client";
import { useSession } from "../../context/SessionContext";
import { formatCategory } from "../../lib/format";
import { useLoad } from "../../lib/useLoad";

/** Reusable test inputs for the template test lab. */
export function SampleCaseListPage() {
  const { tenantId } = useSession();
  const navigate = useNavigate();
  const samples = useLoad(tenantId ? () => api.listSampleCases(tenantId) : null, [tenantId]);
  return (
    <section>
      <div className="page-header">
        <div>
          <h1>Sample cases</h1>
          <p className="muted">
            Realistic customer messages with their facts, for testing reply templates. Keep a set that covers your common
            and tricky cases, and use it to compare models and template versions consistently.
          </p>
        </div>
        <Link className="button" to="/ops/samples/new">New sample</Link>
      </div>
      {samples.data?.length === 0 && <div className="empty"><h2>No samples yet</h2></div>}
      {samples.data && samples.data.length > 0 && (
        <div className="table-wrap card">
          <table className="table">
            <thead><tr><th>Name</th><th>Category</th><th>Message</th><th>Facts</th></tr></thead>
            <tbody>
              {samples.data.map((s) => (
                <tr key={s.id} className="clickable" onClick={() => navigate(`/ops/samples/${s.id}`)}>
                  <td><Link to={`/ops/samples/${s.id}`} onClick={(e) => e.stopPropagation()}><strong>{s.name}</strong></Link></td>
                  <td>{formatCategory(s.category)}</td>
                  <td className="small">{s.message.length > 90 ? `${s.message.slice(0, 90)}…` : s.message}</td>
                  <td className="small code-inline">{Object.keys(s.facts).join(", ") || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
