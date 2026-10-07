import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import type { Message, QueueSettings } from "../api/types";
import { makeCase } from "../test/fixtures";
import { AutoReplyCard, timeUntil } from "./AutoReplyCard";
import { AutoReplySettings, DEFAULT_AUTO_REPLY } from "./AutoReplySettings";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      autoReplySendNow: vi.fn().mockResolvedValue({}),
      autoReplyCancel: vi.fn().mockResolvedValue({}),
      listCases: vi.fn().mockResolvedValue([]),
    },
  };
});

const DRAFT = { id: "d1", body: "Hi Maya, sorry for the wait.", visibility: "draft" } as Message;

describe("AutoReplyCard", () => {
  it("shows when a scheduled reply goes out and lets you send it now or cancel", async () => {
    const user = userEvent.setup();
    const onChanged = vi.fn();
    const sendAt = new Date(Date.now() + 5 * 3600_000 + 20 * 60_000 + 5_000).toISOString();
    const c = makeCase({
      decisions: { auto_reply: { status: "scheduled", mode: "template", draft_id: "d1", send_at: sendAt } },
      messages: [DRAFT],
    });
    render(<AutoReplyCard caseDetail={c} agentId="owner" onChanged={onChanged} />);
    expect(screen.getByText(/Sends in 5 h 20 min/)).toBeInTheDocument();
    expect(screen.getByText("Hi Maya, sorry for the wait.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Send now" }));
    expect(api.autoReplySendNow).toHaveBeenCalledWith(c.tenant_id, c.case_number, "owner");
    await user.click(screen.getByRole("button", { name: "Cancel and reply myself" }));
    expect(api.autoReplyCancel).toHaveBeenCalledWith(c.tenant_id, c.case_number, "owner");
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(2));
  });

  it("explains why a reply was held", () => {
    const c = makeCase({ decisions: { auto_reply: { status: "held", reason: "Compensation is waiting for approval." } } });
    render(<AutoReplyCard caseDetail={c} agentId="owner" onChanged={vi.fn()} />);
    expect(screen.getByText("Automatic reply held for you")).toBeInTheDocument();
    expect(screen.getByText("Compensation is waiting for approval.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Send now" })).not.toBeInTheDocument();
  });

  it("formats the time left", () => {
    const now = new Date("2026-10-07T10:00:00Z");
    expect(timeUntil("2026-10-07T16:00:00Z", now)).toBe("in 6 h");
    expect(timeUntil("2026-10-07T10:03:00Z", now)).toBe("in 3 min");
    expect(timeUntil("2026-10-07T09:00:00Z", now)).toBe("any moment now");
  });
});

describe("AutoReplySettings", () => {
  const base: QueueSettings = {
    gen_ai_allowed: false, auto_send: true, auto_send_mode: "template", auto_send_delay_minutes: 360,
    auto_send_template: DEFAULT_AUTO_REPLY, approval_threshold: null, sla_first_response_hours: null,
    reopen_window_hours: 72, ai_model: "claude-sonnet-5", ai_effort: "low",
  };

  it("edits the wait in hours, inserts placeholders, and needs AI drafting for AI replies", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<MemoryRouter><AutoReplySettings tenantId="t" settings={base} onChange={onChange} /></MemoryRouter>);
    expect(screen.getByLabelText("Wait before sending: 6 hours")).toHaveValue(6);
    expect(screen.getByRole("radio", { name: /Written by AI/ })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "{{case.order_number}}" }));
    expect(onChange).toHaveBeenCalledWith({ auto_send_template: `${DEFAULT_AUTO_REPLY} {{case.order_number}}` });
  });
});
