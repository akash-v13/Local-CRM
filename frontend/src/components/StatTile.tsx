import { Link } from "react-router";

interface Props {
  label: string;
  value: number;
  /** Optional one-line explanation under the value. */
  hint?: string;
  /** Where clicking the tile goes (e.g. the case list, filtered). */
  to?: string;
  /** The dashboard's single lead number: rendered larger. */
  hero?: boolean;
  /** Needs attention when above zero: shows a warning icon and label, never color alone. */
  warnWhenPositive?: boolean;
}

const compact = new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 });

/** A headline number (KPI). */
export function StatTile({ label, value, hint, to, hero, warnWhenPositive }: Props) {
  const warn = warnWhenPositive && value > 0;
  const body = (
    <>
      <span className="stat-label">{label}</span>
      <span className="stat-value">{compact.format(value)}</span>
      {warn ? (
        <span className="stat-warn">
          <span aria-hidden>⚠</span> Needs attention
        </span>
      ) : (
        hint && <span className="stat-hint">{hint}</span>
      )}
    </>
  );
  const className = `stat-tile${hero ? " hero" : ""}${warn ? " warn" : ""}`;
  return to ? (
    <Link to={to} className={className}>
      {body}
    </Link>
  ) : (
    <div className={className}>{body}</div>
  );
}
