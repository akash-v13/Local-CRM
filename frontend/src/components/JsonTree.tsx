interface Props {
  data: unknown;
  /** Paths already kept, e.g. "total.amount". */
  picked: Set<string>;
  onPick: (path: string) => void;
}

function preview(value: unknown): string {
  const text = typeof value === "string" ? `"${value}"` : JSON.stringify(value);
  return text.length > 60 ? `${text.slice(0, 60)}…` : text;
}

/**
 * The API's JSON response as a tree. Every value has a "Keep" button that
 * saves it on the case; objects and lists can be expanded/collapsed.
 */
export function JsonTree({ data, picked, onPick }: Props) {
  return (
    <div className="json-tree" role="tree" aria-label="API response">
      <Node value={data} path="" depth={0} picked={picked} onPick={onPick} />
    </div>
  );
}

function Node({
  value,
  path,
  name,
  depth,
  picked,
  onPick,
}: {
  value: unknown;
  path: string;
  name?: string;
  depth: number;
  picked: Set<string>;
  onPick: (path: string) => void;
}) {
  const isContainer = value !== null && typeof value === "object";
  if (!isContainer) {
    const kept = picked.has(path);
    return (
      <div className="json-leaf" role="treeitem" aria-selected={kept}>
        {name !== undefined && <span className="json-key">{name}:</span>}
        <span className="json-value">{preview(value)}</span>
        {path && (
          <button
            type="button"
            className={`button small ${kept ? "ghost" : "secondary"}`}
            disabled={kept}
            aria-label={kept ? `${path} kept` : `Keep ${path}`}
            onClick={() => onPick(path)}
          >
            {kept ? "Kept ✓" : "Keep"}
          </button>
        )}
      </div>
    );
  }
  const entries = Array.isArray(value)
    ? value.map((v, i) => [String(i), v] as const)
    : Object.entries(value as Record<string, unknown>);
  const summary = Array.isArray(value) ? `[${value.length}]` : `{${entries.length}}`;
  const children = entries.map(([key, child]) => (
    <Node
      key={key}
      value={child}
      name={key}
      path={path ? `${path}.${key}` : key}
      depth={depth + 1}
      picked={picked}
      onPick={onPick}
    />
  ));
  if (depth === 0) return <div className="json-children root">{children}</div>;
  return (
    <details className="json-branch" open={depth < 3} role="treeitem">
      <summary>
        <span className="json-key">{name}:</span> <span className="muted">{summary}</span>
      </summary>
      <div className="json-children">{children}</div>
    </details>
  );
}

/** A friendly default name for a picked path: "total.amount" → "totalAmount", "items.0.sku" → "itemsSku". */
export function suggestTarget(path: string, taken: Set<string>): string {
  const words = path.split(".").filter((p) => !/^\d+$/.test(p));
  const last = words.slice(-2);
  let base = last
    .map((w, i) => {
      const clean = w.replace(/[^A-Za-z0-9]+/g, " ").trim();
      const camel = clean.replace(/ (\w)/g, (_, c: string) => c.toUpperCase());
      return i === 0 ? camel.charAt(0).toLowerCase() + camel.slice(1) : camel.charAt(0).toUpperCase() + camel.slice(1);
    })
    .join("");
  if (!/^[A-Za-z]/.test(base)) base = `field${base}`;
  if (words.length > 1 && !taken.has(words[words.length - 1])) {
    const simple = words[words.length - 1].replace(/[^A-Za-z0-9_]/g, "");
    if (/^[A-Za-z][A-Za-z0-9_]*$/.test(simple) && !["amount", "value", "id", "name", "code"].includes(simple)) {
      base = simple;
    }
  }
  let candidate = base.slice(0, 60);
  for (let n = 2; taken.has(candidate); n++) candidate = `${base.slice(0, 57)}${n}`;
  return candidate;
}
