import { STATE_ICONS, STATE_LABELS, formatDuration, type FlowNode } from "../lib/pipeline";

const CIRCLED = ["⓪", "①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩"];

interface Props {
  nodes: FlowNode[];
  selectedId?: string;
  onSelect: (id: string) => void;
}

/**
 * The intake flow drawn top to bottom, one step after another (like a Step
 * Functions graph). Click a step for details. The steps whose data the
 * selected step uses are outlined, so dependencies are visible at a glance.
 * In an execution, each step shows what happened (icon + label, never colour alone).
 */
export function PipelineDiagram({ nodes, selectedId, onSelect }: Props) {
  const selected = nodes.find((n) => n.id === selectedId);
  const dependsOn = new Set(selected?.uses ?? []);
  const names = new Map(nodes.map((n) => [n.id, n]));

  return (
    <ol className="flow" aria-label="Intake pipeline">
      {nodes.map((n) => (
        <li key={n.id} className="flow-item">
          <button
            type="button"
            className={`flow-node kind-${n.kind}`}
            data-state={n.state}
            data-selected={n.id === selectedId || undefined}
            data-dependency={dependsOn.has(n.id) || undefined}
            aria-pressed={n.id === selectedId}
            onClick={() => onSelect(n.id)}
          >
            <span className="flow-head">
              {n.number !== undefined && <span className="flow-number" aria-hidden>{CIRCLED[n.number] ?? n.number}</span>}
              <strong>{n.title}</strong>
              {n.state && (
                <span className="flow-state">
                  <span aria-hidden>{STATE_ICONS[n.state]} </span>
                  {STATE_LABELS[n.state]}
                  {n.durationMs !== undefined && n.durationMs !== null && ` · ${formatDuration(n.durationMs)}`}
                </span>
              )}
            </span>
            {n.subtitle && <span className="flow-subtitle">{n.subtitle}</span>}
            {n.uses.length > 0 && (
              <span className="flow-uses">
                Uses data from{" "}
                {n.uses.map((id, i) => {
                  const dep = names.get(id);
                  return <span key={id}>{i > 0 && ", "}{dep?.number !== undefined ? `${CIRCLED[dep.number]} ` : ""}{dep?.title ?? id}</span>;
                })}
              </span>
            )}
            {n.facts.length > 0 && (
              <ul className="flow-facts">
                {n.facts.slice(0, 4).map((f) => <li key={f}>{f}</li>)}
                {n.facts.length > 4 && <li className="muted">+{n.facts.length - 4} more</li>}
              </ul>
            )}
            {n.problems.map((p) => (
              <span key={p} className="flow-problem"><span aria-hidden>⚠ </span>{p}</span>
            ))}
          </button>
        </li>
      ))}
    </ol>
  );
}
