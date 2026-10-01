import { useCallback, useEffect, useRef, useState, type ChangeEvent, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { ApiError, api, errorMessage } from "../../api/client";
import type { PromptPreview, PromptTemplateVersion, TemplateOverride } from "../../api/types";
import { CostProjectionPanel } from "../../components/CostProjectionPanel";
import { Field } from "../../components/Field";
import { TemplateTestLab } from "../../components/TemplateTestLab";
import { useSession } from "../../context/SessionContext";
import { formatDateTime } from "../../lib/format";
import { KIND_LABEL, LAYER_LABEL, displayName, fallbackFor, isValidName, kindOf } from "../../lib/templateNames";
import { useLoad } from "../../lib/useLoad";

const lines = (text: string) => text.split("\n").map((l) => l.trim()).filter(Boolean);

const KIND_HINT = {
  base: "Tone and empathy rules every reply follows. Keep it about how to write, not what to say.",
  persona: "Voice, level of empathy, greeting and sign-off for this queue's replies.",
  category: "What this case type needs answered and how to structure the reply.",
} as const;

/**
 * Edit one Jinja prompt template. Saving a change to the source or checks
 * creates a new version; drafts record which versions wrote them.
 * A name that doesn't exist yet opens as a new template, prefilled from the
 * template it currently falls back to.
 * Route: /ops/templates/<name>  (e.g. /ops/templates/category/Complaint_Delivery.jinja)
 */
export function PromptTemplateEditorPage() {
  const name = useParams()["*"] ?? "";
  const { tenantId, agentId } = useSession();
  const navigate = useNavigate();
  const all = useLoad(tenantId ? () => api.listPromptTemplates(tenantId) : null, [tenantId]);
  const models = useLoad(() => api.aiModels(), []);
  const variables = useLoad(tenantId ? () => api.templateVariables(tenantId) : null, [tenantId]);

  const [description, setDescription] = useState("");
  const [source, setSource] = useState("");
  const [maxWords, setMaxWords] = useState("");
  const [mustInclude, setMustInclude] = useState("");
  const [mustNotInclude, setMustNotInclude] = useState("");
  const [loadedFrom, setLoadedFrom] = useState<string>();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string>();
  const [saved, setSaved] = useState<string>();
  const [projectionKey, setProjectionKey] = useState(0);
  const editor = useRef<HTMLTextAreaElement>(null);

  const existing = all.data?.find((t) => t.name === name);
  const isNew = !!all.data && !existing;

  // Fill the form from the template (or, for a new one, from its fallback) once loaded.
  useEffect(() => {
    if (!all.data || loadedFrom === name) return;
    const names = new Set(all.data.map((t) => t.name));
    const from = all.data.find((t) => t.name === name) ?? all.data.find((t) => t.name === fallbackFor(name, names));
    setDescription(from?.name === name ? (from.description ?? "") : "");
    if (from) loadVersion(from.current);
    setLoadedFrom(name);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once per template
  }, [all.data, name]);

  const onRunFinished = useCallback(() => setProjectionKey((k) => k + 1), []);

  function loadVersion(v: PromptTemplateVersion) {
    setSource(v.source);
    setMaxWords(v.max_words === null ? "" : String(v.max_words));
    setMustInclude(v.must_include.join("\n"));
    setMustNotInclude(v.must_not_include.join("\n"));
  }

  if (!tenantId) return null;
  if (!isValidName(name)) {
    return (
      <p className="error">
        “{name}” isn't a template name. Use base.jinja, queue/&lt;Queue&gt;.jinja or category/&lt;Type&gt;_&lt;Category&gt;.jinja.
      </p>
    );
  }
  if (all.error) return <p className="error">{all.error}</p>;
  if (!all.data || !models.data || loadedFrom !== name) return <p className="muted">Loading…</p>;
  const kind = kindOf(name);

  function build(): TemplateOverride | string[] {
    const problems: string[] = [];
    if (!source.trim()) problems.push("The template is empty.");
    if (maxWords.trim() && !(Number(maxWords) >= 10)) problems.push("Max words must be at least 10.");
    if (problems.length) return problems;
    return {
      name,
      source,
      description: description.trim() || null,
      max_words: maxWords.trim() ? Number(maxWords) : null,
      must_include: lines(mustInclude),
      must_not_include: lines(mustNotInclude),
    };
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    setError(undefined);
    setSaved(undefined);
    const body = build();
    if (Array.isArray(body) || !tenantId) {
      setError(Array.isArray(body) ? body.join("\n") : undefined);
      return;
    }
    setSaving(true);
    try {
      const before = existing?.current_version;
      const updated = await api.savePromptTemplate(tenantId, name, body, agentId);
      await all.reload();
      setSaved(updated.current_version !== before ? `Saved as v${updated.current_version} ✓` : "No changes ✓");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  async function upload(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file || !tenantId) return;
    setError(undefined);
    try {
      const updated = await api.importPromptTemplate(tenantId, name, await file.text(), agentId);
      setDescription(updated.description ?? "");
      loadVersion(updated.current);
      await all.reload();
      setSaved(`Uploaded ${file.name} as v${updated.current_version} ✓`);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  /** Insert `{{ path }}` at the cursor. */
  function insert(path: string) {
    const el = editor.current;
    const text = `{{ ${path} }}`;
    const at = el?.selectionStart ?? source.length;
    setSource(source.slice(0, at) + text + source.slice(el?.selectionEnd ?? at));
    requestAnimationFrame(() => {
      el?.focus();
      el?.setSelectionRange(at + text.length, at + text.length);
    });
  }

  return (
    <section>
      <div className="page-header">
        <div>
          <Link to="/ops/templates" className="back">← Prompt templates</Link>
          <h1>
            {displayName(name)} <span className="tag">{KIND_LABEL[kind]}</span>
            {existing && <span className="tag">v{existing.current_version}</span>}
            {isNew && <span className="tag tag-accent">new</span>}
          </h1>
          <p className="muted small"><code className="code-inline">{name}</code> · {KIND_HINT[kind]}</p>
        </div>
        <div className="actions">
          {existing && (
            <a className="button secondary small" href={api.promptTemplateDownloadUrl(tenantId, name)} download>
              Download .jinja
            </a>
          )}
          <label className="button secondary small">
            Upload .jinja
            <input type="file" accept=".jinja,.j2,.txt" className="sr-only" onChange={(e) => void upload(e)} />
          </label>
        </div>
      </div>
      {isNew && (
        <p className="hint">
          This template doesn't exist yet{source ? `; it starts from ${fallbackFor(name, new Set(all.data.map((t) => t.name)))}, which these cases use today` : ""}.
          Save to create it.
        </p>
      )}

      <div className="editor-layout">
        <form className="editor-main" onSubmit={save} noValidate>
          <div className="card form-card">
            <Field label="Description">
              {(id) => <input id={id} value={description} onChange={(e) => setDescription(e.target.value)} placeholder="What this template is for" />}
            </Field>
            <Field label="Template (Jinja)">
              {(id) => (
                <textarea id={id} ref={editor} className="code-editor" rows={18} spellCheck={false} value={source}
                  onChange={(e) => setSource(e.target.value)} />
              )}
            </Field>
            <p className="hint">
              Use <code className="code-inline">{"{{ variable }}"}</code> for case data and{" "}
              <code className="code-inline">{"{% if … %}…{% endif %}"}</code> for conditions. Guard optional data
              with <code className="code-inline">is defined</code>: a missing value stops the draft instead of
              leaving a gap. Personal details arrive masked.
            </p>
          </div>

          <div className="card form-card">
            <h2>Checks</h2>
            <p className="hint">
              Run on every draft and in the test lab. Checks from the baseline, persona and case type all apply
              (the lowest word limit wins).
            </p>
            <div className="grid-3">
              <Field label="Max words">{(id) => <input id={id} type="number" min={10} value={maxWords} onChange={(e) => setMaxWords(e.target.value)} placeholder="No limit" />}</Field>
              <Field label="Must mention (one per line)">{(id) => <textarea id={id} rows={3} value={mustInclude} onChange={(e) => setMustInclude(e.target.value)} placeholder="sorry" />}</Field>
              <Field label="Must not say (one per line)">{(id) => <textarea id={id} rows={3} value={mustNotInclude} onChange={(e) => setMustNotInclude(e.target.value)} placeholder={"voucher\nsmall gesture"} />}</Field>
            </div>
          </div>

          {error && <p className="error pre-line" role="alert">{error}</p>}
          <div className="actions">
            {saved && <span className="saved" role="status">{saved}</span>}
            <button type="button" className="button secondary" onClick={() => navigate("/ops/templates")}>Back</button>
            <button className="button" disabled={saving}>{saving ? "Saving…" : isNew ? "Create template" : "Save"}</button>
          </div>
        </form>

        <aside className="editor-side">
          <div className="card form-card">
            <h2>Variables</h2>
            <p className="hint">Click to insert at the cursor.</p>
            <ul className="variable-list">
              {variables.data?.map((v) => (
                <li key={v.path}>
                  <button type="button" className="chip" onClick={() => insert(v.path)}>{v.path}</button>
                  <span className="muted small">
                    {v.description}
                    {v.example && <> · e.g. <code className="code-inline">{v.example}</code></>}
                  </span>
                </li>
              ))}
            </ul>
          </div>
          <PreviewPanel tenantId={tenantId} name={name} build={build} />
        </aside>
      </div>

      <div className="card form-card lab-card">
        <h2>Test lab</h2>
        <p className="hint">
          Draft replies with this template <strong>as edited above</strong> (saved or not) on several models, several
          times each. It's used for every input you pick; the other layers resolve as usual. Nothing is sent or saved
          on cases.
        </p>
        <TemplateTestLab tenantId={tenantId} agentId={agentId} models={models.data} buildTemplate={build}
          onRunFinished={onRunFinished} />
      </div>

      {existing && (
        <div className="card form-card lab-card">
          <h2>Cost projection</h2>
          <CostProjectionPanel tenantId={tenantId} templateName={name} refreshKey={projectionKey} />
        </div>
      )}

      {existing && (
        <div className="card form-card lab-card">
          <h2>Version history</h2>
          <ol className="versions">
            {existing.versions.map((v) => (
              <li key={v.version}>
                <details>
                  <summary>
                    <strong>v{v.version}</strong> · {formatDateTime(v.created_at)}
                    {v.created_by && ` · ${v.created_by}`}
                    {v.version === existing.current_version && <span className="tag tag-accent">current</span>}
                  </summary>
                  <pre className="code-block">{v.source}</pre>
                  <button type="button" className="button secondary small" onClick={() => { loadVersion(v); setSaved(`Loaded v${v.version} into the editor; save to restore it.`); }}>
                    Load into editor
                  </button>
                </details>
              </li>
            ))}
          </ol>
        </div>
      )}
    </section>
  );
}

/** Render the full prompt for a sample or real case with the edit applied. Free: no model call. */
function PreviewPanel({ tenantId, name, build }: { tenantId: string; name: string; build: () => TemplateOverride | string[] }) {
  const samples = useLoad(() => api.listSampleCases(tenantId), [tenantId]);
  const cases = useLoad(() => api.listCases(tenantId), [tenantId]);
  const [input, setInput] = useState("");
  const [preview, setPreview] = useState<PromptPreview>();
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  async function run() {
    setError(undefined);
    setPreview(undefined);
    const override = build();
    if (Array.isArray(override)) {
      setError(override.join("\n"));
      return;
    }
    const [kind, id] = input.split(":");
    setBusy(true);
    try {
      setPreview(
        await api.previewPrompt(tenantId, {
          ...(kind === "case" ? { case_number: Number(id) } : { sample_id: id }),
          override,
        }),
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card form-card preview-panel">
      <h2>Preview</h2>
      <p className="hint">See the prompt this edit produces for a case. No model call, no cost.</p>
      <div className="inline-form">
        <select aria-label="Preview with" value={input} onChange={(e) => setInput(e.target.value)}>
          <option value="">Choose a sample or case…</option>
          {samples.data && samples.data.length > 0 && (
            <optgroup label="Samples">
              {samples.data.map((s) => <option key={s.id} value={`sample:${s.id}`}>{s.name}</option>)}
            </optgroup>
          )}
          {cases.data && cases.data.length > 0 && (
            <optgroup label="Cases">
              {cases.data.slice(0, 30).map((c) => (
                <option key={c.case_number} value={`case:${c.case_number}`}>
                  {c.case_number} · {c.category.effective?.subcategory ?? c.category.effective?.category ?? "uncategorized"}
                </option>
              ))}
            </optgroup>
          )}
        </select>
        <button type="button" className="button secondary" disabled={!input || busy} onClick={() => void run()}>
          {busy ? "Rendering…" : "Preview"}
        </button>
      </div>
      {error && <p className="error pre-line" role="alert">{error}</p>}
      {preview && !preview.ok && <p className="error pre-line" role="alert">{preview.error}</p>}
      {preview?.ok && (
        <div className="preview-layers">
          <p className="small muted">
            Drafts here use {preview.model}{preview.effort ? ` (${preview.effort} effort)` : ""}; checks: max{" "}
            {preview.checks?.max_words ?? "∞"} words
            {preview.checks?.must_include.length ? `, must mention ${preview.checks.must_include.join(", ")}` : ""}.
          </p>
          {preview.layers.map((l) => (
            <details key={l.layer} open={l.name === name}>
              <summary>
                <strong>{LAYER_LABEL[l.layer]}</strong> · <code className="code-inline">{l.name}</code>
                {l.version === null ? <span className="tag tag-accent">your edit</span> : <span className="tag">v{l.version}</span>}
              </summary>
              <pre className="code-block">{l.text}</pre>
            </details>
          ))}
          <details>
            <summary><strong>Case message</strong> (sent as the user turn)</summary>
            <pre className="code-block">{preview.user}</pre>
          </details>
          <details>
            <summary><strong>Platform rules</strong> <span className="tag">locked</span></summary>
            <pre className="code-block">{preview.system_platform}</pre>
          </details>
        </div>
      )}
    </div>
  );
}
