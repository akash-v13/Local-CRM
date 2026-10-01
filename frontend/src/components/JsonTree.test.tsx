import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { JsonTree, suggestTarget } from "./JsonTree";

const RESPONSE = { total: { amount: 742.5 }, carrier: "FastShip", items: [{ sku: "A1" }] };

describe("JsonTree", () => {
  it("offers every value, including nested and list items, with its path", async () => {
    const onPick = vi.fn();
    const user = userEvent.setup();
    render(<JsonTree data={RESPONSE} picked={new Set(["carrier"])} onPick={onPick} />);

    await user.click(screen.getByRole("button", { name: "Keep total.amount" }));
    await user.click(screen.getByRole("button", { name: "Keep items.0.sku" }));
    expect(onPick.mock.calls).toEqual([["total.amount"], ["items.0.sku"]]);

    expect(screen.getByRole("button", { name: "carrier kept" })).toBeDisabled();
  });
});

describe("suggestTarget", () => {
  it("makes readable, valid, unique names", () => {
    expect(suggestTarget("total.amount", new Set())).toBe("totalAmount");
    expect(suggestTarget("carrier", new Set())).toBe("carrier");
    expect(suggestTarget("items.0.sku", new Set())).toBe("sku");
    expect(suggestTarget("data.token", new Set())).toBe("token");
    expect(suggestTarget("carrier", new Set(["carrier"]))).toBe("carrier2");
    expect(suggestTarget("0", new Set())).toMatch(/^[A-Za-z]/);
  });
});
