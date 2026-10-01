import { describe, expect, it } from "vitest";

import type { MatchCriteria, RoutingFields } from "../api/types";
import {
  CUSTOM_ATTRIBUTE,
  draftProblem,
  emptyCondition,
  fromDrafts,
  summarizeCriteria,
  toDrafts,
} from "./criteria";

const FIELDS: RoutingFields = {
  fields: [
    { key: "category.category", label: "Category", suggestions: [] },
    { key: "message", label: "Customer message text", suggestions: [] },
  ],
  operators: [
    { key: "equals", label: "is", takes_list: false },
    { key: "not_equals", label: "is not", takes_list: false },
    { key: "one_of", label: "is one of", takes_list: true },
    { key: "contains_any", label: "contains any of the words", takes_list: true },
  ],
};

const CRITERIA: MatchCriteria = {
  match: "any",
  conditions: [
    { field: "category.category", op: "equals", value: "Delivery" },
    { field: "message", op: "contains_any", value: ["late", "delayed"] },
    { field: "attributes.region", op: "one_of", value: ["EU", "UK"] },
  ],
};

describe("criteria conversion", () => {
  it("round-trips API criteria through the editor's draft rows", () => {
    const drafts = toDrafts(CRITERIA);
    expect(drafts.map((d) => d.valueText)).toEqual(["Delivery", "late, delayed", "EU, UK"]);
    expect(drafts[2]).toMatchObject({ field: CUSTOM_ATTRIBUTE, attributeKey: "region" });
    expect(fromDrafts("any", drafts, FIELDS)).toEqual(CRITERIA);
  });

  it("trims values and drops empty list items", () => {
    const draft = { ...emptyCondition(), field: "message", op: "contains_any" as const, valueText: " late ,, delayed , " };
    expect(fromDrafts("all", [draft], FIELDS).conditions[0].value).toEqual(["late", "delayed"]);
  });

  it("reports incomplete rows", () => {
    expect(draftProblem({ ...emptyCondition(), valueText: "" }, FIELDS)).toBe("Enter a value.");
    expect(draftProblem({ ...emptyCondition(), op: "one_of", valueText: " , " }, FIELDS)).toMatch(/at least one/);
    expect(draftProblem({ ...emptyCondition(), field: CUSTOM_ATTRIBUTE, valueText: "x" }, FIELDS)).toMatch(/attribute/);
    expect(draftProblem({ ...emptyCondition(), valueText: "Delivery" }, FIELDS)).toBeNull();
  });

  it("summarizes criteria in plain language", () => {
    expect(summarizeCriteria(CRITERIA, FIELDS)).toBe(
      'Category is "Delivery" or Customer message text contains any of the words "late, delayed" or region is one of "EU, UK"',
    );
    expect(summarizeCriteria({ match: "all", conditions: [] })).toBe("Everything (catch-all)");
  });
});
