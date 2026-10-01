import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { api, errorMessage } from "../../api/client";
import type { CategorySelection } from "../../api/types";
import { CategorySelect } from "../../components/CategorySelect";
import { Field } from "../../components/Field";
import { KeyValueEditor, type KeyValueRow } from "../../components/KeyValueEditor";
import { useSession } from "../../context/SessionContext";
import { useLoad } from "../../lib/useLoad";

const EMPTY: CategorySelection = { type: "", category: "", subcategory: null };

/** Fact values typed as text become numbers/booleans when they look like them. */
function parseValue(text: string): unknown {
  const t = text.trim();
  if (t === "true" || t === "false") return t === "true";
  if (t !== "" && !Number.isNaN(Number(t))) return Number(t);
  return text;
}

export function SampleCaseEditorPage() {
  const { sampleId } = useParams();
  const isNew = !sampleId;
  const { tenantId } = useSession();
  const navigate = useNavigate();
  const samples = useLoad(tenantId ? () => api.listSampleCases(tenantId) : null, [tenantId]);
  const taxonomy = useLoad(tenantId ? () => api.listCategories(tenantId) : null, [tenantId]);

  const [name, setName] = useState("");
  const [category, setCategory] = useState<CategorySelection>(EMPTY);
  const [customerName, setCustomerName] = useState("");
  const [tier, setTier] = useState("");
  const [queueName, setQueueName] = useState("");
  const [facts, setFacts] = useState<KeyValueRow[]>([{ key: "daysLate", value: "" }]);
  const [message, setMessage] = useState("");
  const [error, setError] = useState<string>();
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const s = samples.data?.find((x) => x.id === sampleId);
    if (!s) return;
    setName(s.name);
    setCategory(s.category ?? EMPTY);
    setCustomerName(s.customer_name ?? "");
    setTier(s.customer_tier ?? "");
    setQueueName(s.queue_name ?? "");
    setFacts(Object.entries(s.facts).map(([key, value]) => ({ key, value: String(value) })));
    setMessage(s.message);
  }, [samples.data, sampleId]);

  if (!tenantId) return null;

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!tenantId) return;
    setError(undefined);
    if (!name.trim() || !message.trim()) {
      setError("Name and customer message are required.");
      return;
    }
    const body = {
      name: name.trim(),
      channel: "webform" as const,
      category: category.type ? category : null,
      customer_name: customerName.trim() || null,
      customer_tier: tier.trim() || null,
      queue_name: queueName.trim() || null,
      facts: Object.fromEntries(facts.filter((f) => f.key.trim()).map((f) => [f.key.trim(), parseValue(f.value)])),
      message,
    };
    setSaving(true);
    try {
      if (isNew) await api.createSampleCase(tenantId, body);
      else await api.updateSampleCase(tenantId, sampleId, body);
      navigate("/ops/samples");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <section>
      <div className="page-header">
        <div>
          <Link to="/ops/samples" className="back">← Sample cases</Link>
          <h1>{isNew ? "New sample case" : "Edit sample case"}</h1>
        </div>
      </div>
      <form className="editor-main narrow card form-card" onSubmit={save} noValidate>
        <Field label="Name *">{(id) => <input id={id} value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Very late, angry, Gold customer" />}</Field>
        {taxonomy.data && <CategorySelect taxonomy={taxonomy.data} value={category} onChange={setCategory} />}
        <div className="grid-3">
          <Field label="Customer name">{(id) => <input id={id} value={customerName} onChange={(e) => setCustomerName(e.target.value)} />}</Field>
          <Field label="Customer tier">{(id) => <input id={id} value={tier} onChange={(e) => setTier(e.target.value)} />}</Field>
          <Field label="Queue">{(id) => <input id={id} value={queueName} onChange={(e) => setQueueName(e.target.value)} />}</Field>
        </div>
        <div className="field">
          <span className="field-title">Facts (what the case data would say)</span>
          <KeyValueEditor rows={facts} onChange={setFacts} itemLabel="Fact" keyPlaceholder="e.g. daysLate" valuePlaceholder="e.g. 6" addLabel="+ Add fact" />
        </div>
        <Field label="Customer message *">{(id) => <textarea id={id} rows={6} value={message} onChange={(e) => setMessage(e.target.value)} />}</Field>
        {error && <p className="error" role="alert">{error}</p>}
        <div className="actions">
          <Link to="/ops/samples" className="button secondary">Cancel</Link>
          <button className="button" disabled={saving}>{saving ? "Saving…" : "Save sample"}</button>
        </div>
      </form>
    </section>
  );
}
