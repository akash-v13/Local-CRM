import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import type { CategorySelection } from "../api/types";
import { TAXONOMY } from "../test/fixtures";
import { CategorySelect } from "./CategorySelect";

function Harness() {
  const [value, setValue] = useState<CategorySelection>({ type: "", category: "", subcategory: null });
  return (
    <>
      <CategorySelect taxonomy={TAXONOMY} value={value} onChange={setValue} />
      <output>{JSON.stringify(value)}</output>
    </>
  );
}

describe("CategorySelect", () => {
  it("only enables each level once the level above is chosen", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    expect(screen.getByLabelText("Category")).toBeDisabled();
    expect(screen.getByLabelText("Subcategory")).toBeDisabled();

    await user.selectOptions(screen.getByLabelText("Type"), "Complaint");
    expect(screen.getByLabelText("Category")).toBeEnabled();

    await user.selectOptions(screen.getByLabelText("Category"), "Delivery");
    await user.selectOptions(screen.getByLabelText("Subcategory"), "Late delivery");

    expect(screen.getByRole("status")).toHaveTextContent(
      JSON.stringify({ type: "Complaint", category: "Delivery", subcategory: "Late delivery" }),
    );
  });

  it("resets lower levels when a higher level changes", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.selectOptions(screen.getByLabelText("Type"), "Complaint");
    await user.selectOptions(screen.getByLabelText("Category"), "Delivery");
    await user.selectOptions(screen.getByLabelText("Subcategory"), "Late delivery");
    await user.selectOptions(screen.getByLabelText("Type"), "Question");

    expect(screen.getByRole("status")).toHaveTextContent(
      JSON.stringify({ type: "Question", category: "", subcategory: null }),
    );
    expect(screen.getByLabelText("Subcategory")).toBeDisabled();
  });
});
