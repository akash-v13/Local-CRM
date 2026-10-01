import type { CaseStatus } from "../api/types";
import { STATUS_LABELS } from "../lib/format";

/** Colored pill showing a case status. Colors are defined per status in styles.css. */
export function StatusBadge({ status }: { status: CaseStatus }) {
  return (
    <span className="badge" data-status={status}>
      {STATUS_LABELS[status]}
    </span>
  );
}
