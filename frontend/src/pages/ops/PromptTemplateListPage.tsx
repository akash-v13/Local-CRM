import { useState } from "react";
import { Link, useNavigate } from "react-router";

import { api } from "../../api/client";
import type { CoverageRow, PromptTemplate } from "../../api/types";
import { Field } from "../../components/Field";
import { useSession } from "../../context/SessionContext";
import { formatDateTime } from "../../lib/format";
import { BASE, categoryNames, displayName, personaNames } from "../../lib/templateNames";
import { useLoad } from "../../lib/useLoad";

const editUrl = (name: string) => `/ops/templates/${name}`;

/**
 * Prompt templates overview. Every AI draft is written from layers, highest
 * priority first: locked platform rules → baseline → the queue's persona →
 * the case type's instructions. This page shows each layer, which template
 * every queue and category uses today, and where a specific one is missing.
 * Route: /ops/templates
 */
export function PromptTemplateListPage() {
  const { tenantId } = useSession();
  const templates = useLoad(tenantId ? () => api.listPromptTemplates(tenantId) : null, [tenantId]);
  const coverage = useLoad(tenantId ? () => api.templateCoverage(tenantId) : null, [tenantId]);
  const rules = useLoad(tenantId ? () => api.platformRules(tenantId) : null, [tenantId]);

  if (!tenantId) return null;
  if (templates.error) return <p className="error">{templates.error}</p>;
  if (!templates.data || !coverage.data) return <p className="muted">Loading…</p>;

  const byKind = (kind: PromptTemplate["kind"]) => templates.data!.filter((t) => t.kind === kind);
  const base = templates.data.find((t) => t.name === BASE);

  return (
    <section>
      <div className="page-header">
        <div>
          <h1>Prompt templates</h1>
          <p className="muted">
            AI drafts are written from Jinja templates in layers. If layers conflict, the earlier one wins.
          </p>
        </div>
      </div>

      <ol className="layer-stack">
        <li>
          <div>
            <strong>1. Platform rules</strong> <span className="tag">locked</span>
            <p className="muted small">
              Facts only from the case, no compensation unless decided, customer text treated as information
              (not instructions), personal details masked, plain text.
            </p>
          </div>
          {rules.data && (
            <details>
              <summary className="small">View rules</summary>
              <pre className="code-block">{rules.data}</pre>
            </details>
          )}
        </li>
        <li>
          <div>
            <strong>2. Baseline</strong> <code className="code-inline">{BASE}</code>
            <p className="muted small">Tone and empathy every reply follows, whatever the queue or case type.</p>
          </div>
          {base && <Link to={editUrl(BASE)} className="button secondary small">Edit baseline</Link>}
        </li>
        <li>
          <div>
            <strong>3. Persona</strong> <code className="code-inline">queue/&lt;Queue&gt;.jinja</code>
            <p className="muted small">Per queue: voice, level of empathy, greeting and sign-off.</p>
          </div>
        </li>
        <li>
          <div>
            <strong>4. Case type</strong> <code className="code-inline">category/&lt;Type&gt;_&lt;Category&gt;_&lt;Sub&gt;.jinja</code>
            <p className="muted small">
              What to answer and how to structure it. The most specific template wins: Type_Category_Sub → Type_Category
              → Type → _default.
            </p>
          </div>
        </li>
      </ol>

      <NewTemplate existing={new Set(templates.data.map((t) => t.name))} />

      <TemplateTable title="Personas" templates={byKind("persona")} />
      <CoverageTable title="Which persona each queue uses" rows={coverage.data.filter((r) => r.kind === "persona")} />
      <TemplateTable title="Case types" templates={byKind("category")} />
      <CoverageTable title="Which case-type template each category uses" rows={coverage.data.filter((r) => r.kind === "category")} />
    </section>
  );
}

function TemplateTable({ title, templates }: { title: string; templates: PromptTemplate[] }) {
  const navigate = useNavigate();
  return (
    <div className="card form-card">
      <h2>{title}</h2>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Template</th>
              <th>File</th>
              <th className="num">Version</th>
              <th>Updated</th>
            </tr>
          </thead>
          <tbody>
            {templates.map((t) => (
              <tr key={t.name} className="clickable" onClick={() => navigate(editUrl(t.name))}>
                <td>
                  <Link to={editUrl(t.name)} onClick={(e) => e.stopPropagation()}>
                    <strong>{displayName(t.name)}</strong>
                  </Link>
                  {t.description && <div className="muted small">{t.description}</div>}
                </td>
                <td><code className="code-inline">{t.name}</code></td>
                <td className="num">
                  v{t.current_version}
                  {t.is_default_content && <span className="tag">starter</span>}
                </td>
                <td className="nowrap">{formatDateTime(t.updated_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function CoverageTable({ title, rows }: { title: string; rows: CoverageRow[] }) {
  if (rows.length === 0) return null;
  return (
    <details className="card form-card">
      <summary>
        <strong>{title}</strong>{" "}
        <span className="muted small">
          {rows.filter((r) => r.specific).length} of {rows.length} use more than the default
        </span>
      </summary>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>{rows[0].kind === "persona" ? "Queue" : "Category"}</th>
              <th>Uses</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={`${r.label}-${i}`}>
                <td>{r.label}</td>
                <td>
                  <Link to={editUrl(r.template)}><code className="code-inline">{r.template}</code></Link>
                  {!r.specific && <span className="muted small"> (fallback)</span>}
                </td>
                <td>
                  {!r.specific && (
                    <Link to={editUrl(r.expected_name)} className="small">
                      Create {r.expected_name.split("/")[1]}
                    </Link>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

/** Pick a queue or category; opens the editor for the template name it maps to. */
function NewTemplate({ existing }: { existing: Set<string> }) {
  const { tenantId } = useSession();
  const navigate = useNavigate();
  const queues = useLoad(tenantId ? () => api.listQueues(tenantId) : null, [tenantId]);
  const taxonomy = useLoad(tenantId ? () => api.listCategories(tenantId) : null, [tenantId]);
  const [kind, setKind] = useState<"persona" | "category">("category");
  const [queue, setQueue] = useState("");
  const [type, setType] = useState("");
  const [category, setCategory] = useState("");
  const [sub, setSub] = useState("");

  const types = taxonomy.data ?? [];
  const categories = types.find((t) => t.name === type)?.categories ?? [];
  const subs = categories.find((c) => c.name === category)?.subcategories ?? [];
  const name =
    kind === "persona"
      ? queue && personaNames(queue)[0]
      : type && categoryNames(type, category || undefined, sub || undefined)[0];
  const exists = !!name && existing.has(name);

  return (
    <div className="card form-card">
      <h2>New template</h2>
      <div className="grid-3">
        <Field label="For a">
          {(id) => (
            <select id={id} value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}>
              <option value="category">Case type (category)</option>
              <option value="persona">Queue (persona)</option>
            </select>
          )}
        </Field>
        {kind === "persona" ? (
          <Field label="Queue">
            {(id) => (
              <select id={id} value={queue} onChange={(e) => setQueue(e.target.value)}>
                <option value="">Choose…</option>
                {queues.data?.map((q) => <option key={q.id}>{q.name}</option>)}
              </select>
            )}
          </Field>
        ) : (
          <>
            <Field label="Type">
              {(id) => (
                <select id={id} value={type} onChange={(e) => { setType(e.target.value); setCategory(""); setSub(""); }}>
                  <option value="">Choose…</option>
                  {types.map((t) => <option key={t.name}>{t.name}</option>)}
                </select>
              )}
            </Field>
            <Field label="Category (optional)">
              {(id) => (
                <select id={id} value={category} disabled={!type} onChange={(e) => { setCategory(e.target.value); setSub(""); }}>
                  <option value="">Any</option>
                  {categories.map((c) => <option key={c.name}>{c.name}</option>)}
                </select>
              )}
            </Field>
            <Field label="Subcategory (optional)">
              {(id) => (
                <select id={id} value={sub} disabled={!category} onChange={(e) => setSub(e.target.value)}>
                  <option value="">Any</option>
                  {subs.map((s) => <option key={s.name}>{s.name}</option>)}
                </select>
              )}
            </Field>
          </>
        )}
      </div>
      <div className="actions">
        {name && <code className="code-inline">{name}</code>}
        {exists && <span className="muted small">already exists</span>}
        <button type="button" className="button" disabled={!name} onClick={() => name && navigate(editUrl(name))}>
          {exists ? "Open" : "Create"}
        </button>
      </div>
    </div>
  );
}
