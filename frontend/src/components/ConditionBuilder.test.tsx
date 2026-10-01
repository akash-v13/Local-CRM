import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import type { MatchCriteria, RoutingFields } from "../api/types";
import { fromDrafts, type ConditionDraft } from "../lib/criteria";
import { ConditionBuilder } from "./ConditionBuilder";

const FIELDS: RoutingFields = {
  fields: [
    { key: "category.category", label: "Category", suggestions: ["Delivery", "Order"] },
    { key: "message", label: "Customer message text", suggestions: [] },
  ],
  operators: [
    { key: "equals", label: "is", takes_list: false },
    { key: "contains_any", label: "contains any of the words", takes_list: true },
  ],
};

function Harness({ showProblems = false }: { showProblems?: boolean }) {
  const [match, setMatch] = useState<MatchCriteria["match"]>("all");
  const [conditions, setConditions] = useState<ConditionDraft[]>([]);
  return (
    <>
      <ConditionBuilder
        fields={FIELDS}
        match={match}
        onMatchChange={setMatch}
        conditions={conditions}
        onConditionsChange={setConditions}
        showProblems={showProblems}
      />
      <output>{JSON.stringify(fromDrafts(match, conditions, FIELDS))}</output>
    </>
  );
}

describe("ConditionBuilder", () => {
  it("starts as a catch-all and builds conditions row by row", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    expect(screen.getByText(/matches/)).toHaveTextContent("every case");

    await user.click(screen.getByRole("button", { name: "+ Add condition" }));
    await user.type(screen.getByLabelText("Condition 1 value"), "Delivery");

    await user.click(screen.getByRole("button", { name: "+ Add condition" }));
    await user.selectOptions(screen.getByLabelText("Condition 2 field"), "message");
    await user.selectOptions(screen.getByLabelText("Condition 2 operator"), "contains_any");
    await user.type(screen.getByLabelText("Condition 2 value"), "late, delayed");
    await user.selectOptions(screen.getByLabelText("Match mode"), "any");

    expect(JSON.parse(screen.getByRole("status").textContent ?? "")).toEqual({
      match: "any",
      conditions: [
        { field: "category.category", op: "equals", value: "Delivery" },
        { field: "message", op: "contains_any", value: ["late", "delayed"] },
      ],
    });
    expect(screen.getByText("or")).toBeInTheDocument(); // row join word follows the match mode
  });

  it("removes rows and flags incomplete ones when asked", async () => {
    const user = userEvent.setup();
    render(<Harness showProblems />);
    await user.click(screen.getByRole("button", { name: "+ Add condition" }));
    expect(screen.getByText("Enter a value.")).toBeInTheDocument();
    expect(screen.getByLabelText("Condition 1 value")).toHaveAttribute("aria-invalid", "true");

    await user.click(screen.getByRole("button", { name: "Remove condition 1" }));
    expect(screen.queryByLabelText("Condition 1 value")).not.toBeInTheDocument();
  });
});
