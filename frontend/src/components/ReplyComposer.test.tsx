import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api, ApiError } from "../api/client";
import { makeCase } from "../test/fixtures";
import { ReplyComposer } from "./ReplyComposer";

// Replace real network calls with spies; everything else in the module stays real.
vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return { ...actual, api: { ...actual.api, addMessage: vi.fn() } };
});
const addMessage = vi.mocked(api.addMessage);

describe("ReplyComposer", () => {
  beforeEach(() => {
    addMessage.mockReset();
    addMessage.mockResolvedValue({} as never);
  });

  it("sends an agent reply and clears the box", async () => {
    const user = userEvent.setup();
    const onSent = vi.fn();
    render(<ReplyComposer caseDetail={makeCase()} agentId="agent.alex" onSent={onSent} />);

    await user.type(screen.getByLabelText("Message"), "  Sorry about that!  ");
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(addMessage).toHaveBeenCalledWith("tenant-1", makeCase().case_number, {
      kind: "agent_reply",
      body: "Sorry about that!",
      author_id: "agent.alex",
      then_status: undefined,
    });
    await waitFor(() => expect(onSent).toHaveBeenCalled());
    expect(screen.getByLabelText("Message")).toHaveValue("");
  });

  it("offers 'Send & mark solved' only when Solved is an allowed next status", async () => {
    const user = userEvent.setup();
    const { rerender } = render(
      <ReplyComposer caseDetail={makeCase()} agentId="a" onSent={() => {}} />,
    );
    await user.type(screen.getByLabelText("Message"), "Done");
    await user.click(screen.getByRole("button", { name: "Send & mark solved" }));
    expect(addMessage.mock.calls[0][2]).toMatchObject({ then_status: "Solved" });

    rerender(
      <ReplyComposer
        caseDetail={makeCase({ status: "Queued", allowed_next_statuses: ["AssignedAgent"] })}
        agentId="a"
        onSent={() => {}}
      />,
    );
    expect(screen.queryByRole("button", { name: "Send & mark solved" })).not.toBeInTheDocument();
  });

  it("sends internal notes and simulated customer replies with the right kind", async () => {
    const user = userEvent.setup();
    render(<ReplyComposer caseDetail={makeCase()} agentId="a" onSent={() => {}} />);

    await user.click(screen.getByRole("tab", { name: "Internal note" }));
    await user.type(screen.getByLabelText("Message"), "Checked with carrier");
    await user.click(screen.getByRole("button", { name: "Add note" }));
    await waitFor(() => expect(addMessage).toHaveBeenCalledTimes(1));
    expect(addMessage.mock.calls[0][2]).toMatchObject({ kind: "internal_note" });

    await user.click(screen.getByRole("tab", { name: "Simulate customer reply" }));
    await user.type(screen.getByLabelText("Message"), "Still waiting");
    await user.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(addMessage).toHaveBeenCalledTimes(2));
    expect(addMessage.mock.calls[1][2]).toMatchObject({ kind: "customer_reply" });
  });

  it("only allows internal notes on a closed case", async () => {
    const user = userEvent.setup();
    render(
      <ReplyComposer
        caseDetail={makeCase({ status: "Closed", allowed_next_statuses: [] })}
        agentId="a"
        onSent={() => {}}
      />,
    );
    expect(screen.getByLabelText("Message")).toBeDisabled();
    expect(screen.getByText("Closed cases only accept internal notes.")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Internal note" }));
    expect(screen.getByLabelText("Message")).toBeEnabled();
  });

  it("shows the backend's error message and keeps the text", async () => {
    addMessage.mockRejectedValueOnce(new ApiError(409, "Case is closed."));
    const user = userEvent.setup();
    render(<ReplyComposer caseDetail={makeCase()} agentId="a" onSent={() => {}} />);

    await user.type(screen.getByLabelText("Message"), "Hello");
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Case is closed.");
    expect(screen.getByLabelText("Message")).toHaveValue("Hello");
  });
});
