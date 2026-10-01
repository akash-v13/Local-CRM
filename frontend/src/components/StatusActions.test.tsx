import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import { makeCase } from "../test/fixtures";
import { StatusActions } from "./StatusActions";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return { ...actual, api: { ...actual.api, transition: vi.fn().mockResolvedValue({}) } };
});

describe("StatusActions", () => {
  it("shows one button per allowed next status, in the order the API gives", () => {
    render(<StatusActions caseDetail={makeCase()} agentId="a" onChanged={() => {}} />);
    const labels = screen.getAllByRole("button").map((b) => b.textContent);
    expect(labels).toEqual(["Move to queue", "Request approval", "Wait on customer", "Mark solved"]);
  });

  it("moves the case with the agent as actor and the typed reason", async () => {
    const user = userEvent.setup();
    const onChanged = vi.fn();
    render(<StatusActions caseDetail={makeCase()} agentId="agent.alex" onChanged={onChanged} />);

    await user.type(screen.getByLabelText("Reason (optional)"), "Wrong queue");
    await user.click(screen.getByRole("button", { name: "Move to queue" }));

    expect(api.transition).toHaveBeenCalledWith("tenant-1", makeCase().case_number, {
      to_status: "Queued",
      actor_type: "human",
      actor_id: "agent.alex",
      reason: "Wrong queue",
    });
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it("says so when the case is final", () => {
    render(
      <StatusActions
        caseDetail={makeCase({ status: "Closed", allowed_next_statuses: [] })}
        agentId="a"
        onChanged={() => {}}
      />,
    );
    expect(screen.getByText(/This case is final/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
