import { Link, useNavigate } from "react-router";

import { api } from "../../api/client";
import { useSession } from "../../context/SessionContext";
import { modelLabel } from "../../components/DraftPanel";
import { summarizeCriteria } from "../../lib/criteria";
import { useLoad } from "../../lib/useLoad";

/** Reply templates in the order they're checked; the first match drafts the reply. */
export function ReplyTemplateListPage() {
  const { tenantId } = useSession();
  const navigate = useNavigate();
  const templates = useLoad(tenantId ? () => api.listReplyTemplates(tenantId) : null, [tenantId]);
  const fields = useLoad(tenantId ? () => api.routingFields(tenantId) : null, [tenantId]);

  return (
    <section>
      <div className="page-header">
        <div>
          <h1>Reply templates</h1>
          <p className="muted">
            How AI drafts replies. When an agent clicks <strong>Draft with AI</strong>, the first active template
            (top to bottom) whose conditions match the case is used. AI drafting must also be allowed on the case's
            queue.
          </p>
        </div>
        <Link className="button" to="/ops/templates/new">New template</Link>
      </div>
      {templates.error && <p className="error">{templates.error}</p>}
      {templates.data && (
        <div className="table-wrap card">
          <table className="table">
            <thead>
              <tr>
                <th className="num">Priority</th>
                <th>Template</th>
                <th>Used for cases where</th>
                <th>Model</th>
                <th className="num">Version</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {templates.data.map((t) => (
                <tr key={t.id} className={`clickable${t.is_active ? "" : " inactive"}`} onClick={() => navigate(`/ops/templates/${t.id}`)}>
                  <td className="num">{t.priority}</td>
                  <td>
                    <Link to={`/ops/templates/${t.id}`} onClick={(e) => e.stopPropagation()}><strong>{t.name}</strong></Link>
                    {t.description && <div className="muted small">{t.description}</div>}
                  </td>
                  <td>{summarizeCriteria(t.match_criteria, fields.data)}</td>
                  <td>{modelLabel(t.current.model)}</td>
                  <td className="num">v{t.current_version}</td>
                  <td>{t.is_active ? "Active" : "Inactive"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
