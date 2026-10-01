import { describe, expect, it } from "vitest";

import { categoryNames, displayName, fallbackFor, isValidName, personaNames, slug } from "./templateNames";

// Must resolve exactly like backend/app/ai/engine.py.
describe("template names", () => {
  it("slugs queue and category names", () => {
    expect(slug("Late delivery")).toBe("LateDelivery");
    expect(slug("High-value VIP")).toBe("HighValueVIP");
  });

  it("orders lookups from most specific to default", () => {
    expect(personaNames("Delivery")).toEqual(["queue/Delivery.jinja", "queue/_default.jinja"]);
    expect(categoryNames("Complaint", "Delivery", "Late delivery")).toEqual([
      "category/Complaint_Delivery_LateDelivery.jinja",
      "category/Complaint_Delivery.jinja",
      "category/Complaint.jinja",
      "category/_default.jinja",
    ]);
    expect(categoryNames("Question")).toEqual(["category/Question.jinja", "category/_default.jinja"]);
  });

  it("finds what a new template currently falls back to", () => {
    const existing = new Set(["category/Complaint_Delivery.jinja", "category/_default.jinja"]);
    expect(fallbackFor("category/Complaint_Delivery_Damaged.jinja", existing)).toBe("category/Complaint_Delivery.jinja");
    expect(fallbackFor("category/Compliment_Staff.jinja", existing)).toBe("category/_default.jinja");
    expect(fallbackFor("queue/Vip.jinja", existing)).toBe("queue/_default.jinja");
  });

  it("validates and displays names", () => {
    expect(isValidName("queue/../x.jinja")).toBe(false);
    expect(isValidName("category/Complaint_Delivery.jinja")).toBe(true);
    expect(displayName("category/Complaint_Delivery_LateDelivery.jinja")).toBe("Complaint › Delivery › LateDelivery");
  });
});
