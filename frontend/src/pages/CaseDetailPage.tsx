import { Fragment, useEffect } from "react";
import { Link, useParams } from "react-router";

import { api } from "../api/client";
import { CompensationCard } from "../components/CompensationCard";
import { EnrichmentCard } from "../components/EnrichmentCard";
import { EventTimeline } from "../components/EventTimeline";
import { NeedsTenant } from "../components/Layout";
import { MessageThread } from "../components/MessageThread";
import { QueueCard } from "../components/QueueCard";
import { ReplyComposer } from "../components/ReplyComposer";
import { StatusActions } from "../components/StatusActions";
import { StatusBadge } from "../components/StatusBadge";
import { useSession } from "../context/SessionContext";
import { formatCaseNumber, formatCategory, formatDateTime, parseCaseNumber } from "../lib/format";
import { useLoad } from "../lib/useLoad";

/**
 * One case: the conversation and reply box on the left; customer, category,
 * status actions and the audit trail on the right.
 */
export function CaseDetailPage() {
  const caseNumber = parseCaseNumber(useParams().caseNumber);
  const { tenantId, agentId } = useSession();
  const ready = tenantId !== null && caseNumber !== null;

  const detail = useLoad(ready ? () => api.getCase(tenantId, caseNumber) : null, [tenantId, caseNumber]);
  const events = useLoad(ready ? () => api.listEvents(tenantId, caseNumber) : null, [
    tenantId,
    caseNumber,
  ]);

  // While the worker is enriching (case still in Intake), refresh every 2 seconds.
  const enriching = detail.data?.status === "Intake";
  useEffect(() => {
    if (!enriching) return;
    const timer = window.setInterval(() => {
      void detail.reload();
      void events.reload();
    }, 2000);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reload functions are stable
  }, [enriching]);

  if (!tenantId) return <NeedsTenant />;
  if (caseNumber === null) {
    return (
      <div className="empty">
        <h2>That isn't a valid case number</h2>
        <Link to="/cases">Back to cases</Link>
      </div>
    );
  }

  // After any change (reply, note, status move), reload both the case and its history.
  const refresh = () => {
    void detail.reload();
    void events.reload();
  };

  if (detail.error) {
    return (
      <div className="empty">
        <h2>Couldn't load this case</h2>
        <p className="error">{detail.error}</p>
        <Link to="/cases">Back to cases</Link>
      </div>
    );
  }
  if (!detail.data) return <p className="muted">Loading…</p>;

  const c = detail.data;
  const customerName = c.customer.display_name ?? c.customer.email;
  const selected = c.category.customerSelected;
  const effective = c.category.effective;
  const attributes = Object.entries(c.attributes);

  return (
    <section>
      <div className="page-header">
        <div>
          <Link to="/cases" className="back">
            ← Cases
          </Link>
          <h1>
            Case <code>{formatCaseNumber(c.case_number)}</code> <StatusBadge status={c.status} />
          </h1>
          <p className="muted">
            {formatCategory(effective)} · {c.queue?.name ?? "unrouted"} · via {c.channel} · opened{" "}
            {formatDateTime(c.created_at)}
          </p>
        </div>
      </div>

      <div className="case-layout">
        <div className="case-main">
          <div className="card">
            <h2>Conversation</h2>
            <MessageThread messages={c.messages} customerName={customerName} />
          </div>
          <ReplyComposer caseDetail={c} agentId={agentId} onSent={refresh} />
        </div>

        <aside className="case-side">
          <div className="card">
            <h2>Customer</h2>
            <dl className="details">
              <dt>Name</dt>
              <dd>{c.customer.display_name ?? "—"}</dd>
              <dt>Email</dt>
              <dd>{c.customer.email}</dd>
              <dt>Tier</dt>
              <dd>{c.customer.tier ?? "—"}</dd>
            </dl>
          </div>

          <div className="card">
            <h2>Case</h2>
            <dl className="details">
              <dt>Category</dt>
              <dd>{formatCategory(effective)}</dd>
              {JSON.stringify(selected) !== JSON.stringify(effective) && (
                <>
                  <dt>Customer picked</dt>
                  <dd>{formatCategory(selected)}</dd>
                </>
              )}
              <dt>Assignee</dt>
              <dd>{c.assignee_id ? `${c.assignee_id} (${c.assignee_type})` : "—"}</dd>
              {attributes.map(([key, value]) => (
                <Fragment key={key}>
                  <dt>{key}</dt>
                  <dd>{String(value)}</dd>
                </Fragment>
              ))}
              <dt>Version</dt>
              <dd>{c.version}</dd>
            </dl>
          </div>

          <div className="card">
            <h2>Enrichment</h2>
            <EnrichmentCard caseDetail={c} agentId={agentId} onChanged={refresh} />
          </div>

          <div className="card">
            <h2>Queue</h2>
            <QueueCard caseDetail={c} agentId={agentId} onChanged={refresh} />
          </div>

          <div className="card">
            <h2>Compensation</h2>
            <CompensationCard caseDetail={c} agentId={agentId} onChanged={refresh} />
          </div>

          <div className="card">
            <h2>Status</h2>
            <StatusActions caseDetail={c} agentId={agentId} onChanged={refresh} />
          </div>

          <div className="card">
            <h2>History</h2>
            {events.error && <p className="error">{events.error}</p>}
            {events.data && <EventTimeline events={events.data} />}
          </div>
        </aside>
      </div>
    </section>
  );
}
