import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { slugify } from "../lib/credentials";
import { TemplateField } from "./TemplateField";

function Harness() {
  const [value, setValue] = useState("https://api.example.com/orders/");
  return (
    <TemplateField
      label="URL"
      value={value}
      onChange={setValue}
      placeholders={[{ path: "case.attributes.orderNumber", label: "Order number" }]}
    />
  );
}

describe("TemplateField", () => {
  it("inserts a placeholder from the menu", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const input = screen.getByLabelText("URL");
    await user.click(input); // caret at the end
    await user.selectOptions(screen.getByLabelText("Insert a field into URL"), "case.attributes.orderNumber");
    expect(input).toHaveValue("https://api.example.com/orders/{{case.attributes.orderNumber}}");
  });
});

describe("slugify (connector keys)", () => {
  it("turns names into valid keys", () => {
    expect(slugify("Shop Orders API")).toBe("shop_orders_api");
    expect(slugify("2nd shipping")).toBe("nd_shipping");
    expect(slugify("x")).toBe("");
  });
});
