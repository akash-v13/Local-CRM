export interface KeyValueRow {
  key: string;
  value: string;
}

interface Props {
  rows: KeyValueRow[];
  onChange: (rows: KeyValueRow[]) => void;
  /** Accessible name for the whole list, e.g. "Header". Rows get "Header 1 name" etc. */
  itemLabel: string;
  keyPlaceholder: string;
  valuePlaceholder: string;
  /** Hide typed values (for secrets). */
  secretValues?: boolean;
  addLabel: string;
}

/** Editable list of name/value pairs (request headers, named secret values). */
export function KeyValueEditor({
  rows,
  onChange,
  itemLabel,
  keyPlaceholder,
  valuePlaceholder,
  secretValues,
  addLabel,
}: Props) {
  const update = (index: number, change: Partial<KeyValueRow>) =>
    onChange(rows.map((row, i) => (i === index ? { ...row, ...change } : row)));

  return (
    <div className="kv-editor">
      {rows.map((row, i) => (
        <div className="kv-row" key={i}>
          <input
            className="code"
            aria-label={`${itemLabel} ${i + 1} name`}
            placeholder={keyPlaceholder}
            value={row.key}
            onChange={(e) => update(i, { key: e.target.value })}
            autoComplete="off"
          />
          <input
            className="code"
            aria-label={`${itemLabel} ${i + 1} value`}
            placeholder={valuePlaceholder}
            type={secretValues ? "password" : "text"}
            value={row.value}
            onChange={(e) => update(i, { value: e.target.value })}
            autoComplete={secretValues ? "new-password" : "off"}
          />
          <button
            type="button"
            className="button small ghost"
            aria-label={`Remove ${itemLabel.toLowerCase()} ${i + 1}`}
            onClick={() => onChange(rows.filter((_, j) => j !== i))}
          >
            Remove
          </button>
        </div>
      ))}
      <button
        type="button"
        className="button small secondary"
        onClick={() => onChange([...rows, { key: "", value: "" }])}
      >
        {addLabel}
      </button>
    </div>
  );
}

export const toRows = (record: Record<string, string>): KeyValueRow[] =>
  Object.entries(record).map(([key, value]) => ({ key, value }));

export const fromRows = (rows: KeyValueRow[]): Record<string, string> =>
  Object.fromEntries(rows.filter((r) => r.key.trim()).map((r) => [r.key.trim(), r.value]));
