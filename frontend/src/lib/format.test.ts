import { describe, expect, it } from "vitest";

import { parseCaseNumber } from "./format";

describe("parseCaseNumber", () => {
  it("accepts microsecond timestamps from URLs", () => {
    expect(parseCaseNumber("1790812345678901")).toBe(1790812345678901);
  });

  it("rejects anything that isn't a safe whole number", () => {
    for (const bad of [undefined, "", "abc", "12.5", "-5", "11111111-2222-3333-4444-555555555555", "99999999999999999"]) {
      expect(parseCaseNumber(bad)).toBeNull();
    }
  });
});
