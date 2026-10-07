import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Message } from "../api/types";
import { MessageThread } from "./MessageThread";

const base: Message = {
  id: "m1", direction: "inbound", channel: "email", author_type: "customer", author_id: null,
  visibility: "public", body: "My order is late", ai: {}, external_id: "<m1@example.com>",
  email: { subject: "Where is my order?", attachments: [{ filename: "receipt.pdf", content_type: "application/pdf", size: 20480 }] },
  created_at: "2026-10-07T10:00:00Z",
};

const reply = (status: "queued" | "sent" | "failed", error: string | null = null): Message => ({
  ...base, id: `r-${status}`, direction: "outbound", author_type: "human", author_id: "agent.alex", body: "Sorry!",
  external_id: "<r@northwind>", email: { to: ["maya@example.com"], delivery: { status, error, sent_at: null } },
});

describe("MessageThread email details", () => {
  it("shows the subject, attachments and that it came by email", () => {
    render(<MessageThread messages={[base]} customerName="Maya" />);
    expect(screen.getByText("Where is my order?")).toBeInTheDocument();
    expect(screen.getByText(/receipt\.pdf \(20 KB\)/)).toBeInTheDocument();
    expect(screen.getByText("Email")).toBeInTheDocument();
  });

  it("shows delivery status, and Retry for failed emails", async () => {
    const onRetry = vi.fn();
    render(
      <MessageThread
        messages={[reply("sent"), reply("failed", "SMTP login failed")]}
        customerName="Maya"
        onRetry={onRetry}
      />,
    );
    expect(screen.getByText(/Emailed to maya@example\.com/)).toBeInTheDocument();
    expect(screen.getByText(/Email failed/)).toBeInTheDocument();
    expect(screen.getByText("SMTP login failed")).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledWith(expect.objectContaining({ id: "r-failed" }));
  });

  it("labels replies on non-email cases as simulated", () => {
    render(<MessageThread messages={[{ ...reply("sent"), email: {} }]} customerName="Maya" />);
    expect(screen.getByText("Sent · simulated")).toBeInTheDocument();
  });
});
