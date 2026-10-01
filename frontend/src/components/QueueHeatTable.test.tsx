import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import type { QueueReportRow } from "../api/types";
import { QueueHeatTable } from "./QueueHeatTable";

const ROWS: QueueReportRow[] = [
  {
    queue_id: "q-delivery",
    queue_name: "Delivery",
    priority: 10,
    is_active: true,
    counts: { Queued: 10, WaitingApproval: 1, Solved: 4 },
    open_total: 11,
    oldest_open_at: new Date(Date.now() - 3 * 3600_000).toISOString(),
  },
  {
    queue_id: null,
    queue_name: "Unrouted",
    priority: null,
    is_active: true,
    counts: { Intake: 2 },
    open_total: 2,
    oldest_open_at: null,
  },
];

describe("QueueHeatTable", () => {
  it("links every count to exactly those cases and shades by volume", () => {
    render(
      <MemoryRouter>
        <QueueHeatTable rows={ROWS} />
      </MemoryRouter>,
    );
    const delivery = screen.getByRole("row", { name: /Delivery/ });

    const queued = within(delivery).getByRole("link", { name: "Delivery · Queued: 10 cases" });
    expect(queued).toHaveAttribute("href", "/cases?queue=q-delivery&status=Queued");
    expect(queued.closest("td")).toHaveAttribute("data-heat", "5"); // the busiest cell

    const approval = within(delivery).getByRole("link", { name: /Waiting for approval: 1 case$/ });
    expect(approval.closest("td")).toHaveAttribute("data-heat", "1");

    expect(within(delivery).getByRole("link", { name: "11" })).toHaveAttribute("href", "/cases?queue=q-delivery");
    expect(within(delivery).getByText("3h")).toBeInTheDocument(); // oldest open case age

    const unrouted = screen.getByRole("row", { name: /Unrouted/ });
    expect(within(unrouted).getByRole("link", { name: /Intake: 2 cases/ })).toHaveAttribute(
      "href",
      "/cases?queue=unrouted&status=Intake",
    );
  });
});
