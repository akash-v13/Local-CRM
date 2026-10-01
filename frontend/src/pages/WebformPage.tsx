import { useState, type FormEvent } from "react";
import { Link } from "react-router";

import { api, errorMessage } from "../api/client";
import type { Case, CategorySelection } from "../api/types";
import { CategorySelect } from "../components/CategorySelect";
import { Field } from "../components/Field";
import { NeedsTenant } from "../components/Layout";
import { useSession } from "../context/SessionContext";
import { useLoad } from "../lib/useLoad";

const EMPTY_CATEGORY: CategorySelection = { type: "", category: "", subcategory: null };

/**
 * A stand-in for the customer-facing contact form a business would embed on
 * its website. Submitting it creates a real case (channel "webform") that
 * appears in the agent console.
 */
export function WebformPage() {
  const { tenantId } = useSession();
  const taxonomy = useLoad(tenantId ? () => api.listCategories(tenantId) : null, [tenantId]);

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [orderNumber, setOrderNumber] = useState("");
  const [category, setCategory] = useState<CategorySelection>(EMPTY_CATEGORY);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [created, setCreated] = useState<Case>();

  if (!tenantId) return <NeedsTenant />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!tenantId) return;
    setBusy(true);
    setError(undefined);
    try {
      const result = await api.createCase(tenantId, {
        channel: "webform",
        customer: { email: email.trim(), display_name: name.trim() || undefined },
        category,
        message: message.trim(),
        attributes: orderNumber.trim() ? { orderNumber: orderNumber.trim() } : {},
      });
      setCreated(result);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  function reset() {
    setCreated(undefined);
    setCategory(EMPTY_CATEGORY);
    setMessage("");
    setOrderNumber("");
  }

  if (created) {
    return (
      <div className="webform card">
        <h1>Thanks, we've got it</h1>
        <p>Your request was received. Case number: <code>{created.case_number}</code></p>
        <div className="actions start">
          <Link className="button" to={`/cases/${created.case_number}`}>
            Open in agent console
          </Link>
          <button type="button" className="button secondary" onClick={reset}>
            Submit another
          </button>
        </div>
      </div>
    );
  }

  return (
    <form className="webform card" onSubmit={submit}>
      <div className="webform-header">
        <h1>Contact us</h1>
        <p className="muted">
          Test webform. This simulates the form a business puts on its website. Submitting it
          creates a case.
        </p>
      </div>

      <div className="grid-2">
        <Field label="Your name">
          {(id) => (
            <input
              id={id}
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoComplete="name"
            />
          )}
        </Field>
        <Field label="Email *">
          {(id) => (
            <input
              id={id}
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              required
            />
          )}
        </Field>
      </div>

      <fieldset className="fieldset">
        <legend>What is this about? *</legend>
        {taxonomy.error && <p className="error">{taxonomy.error}</p>}
        {taxonomy.data && (
          <CategorySelect taxonomy={taxonomy.data} value={category} onChange={setCategory} />
        )}
      </fieldset>

      <Field label="Order number (optional)">
        {(id) => (
          <input id={id} value={orderNumber} onChange={(e) => setOrderNumber(e.target.value)} />
        )}
      </Field>

      <Field label="Message *">
        {(id) => (
          <textarea
            id={id}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            rows={6}
            placeholder="Tell us what happened…"
            required
          />
        )}
      </Field>

      {error && <p className="error" role="alert">{error}</p>}

      <div className="actions">
        <button className="button" disabled={busy}>
          {busy ? "Submitting…" : "Submit"}
        </button>
      </div>
    </form>
  );
}
