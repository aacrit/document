import { describe, expect, it } from "vitest";
import { correctionText, whereIsValid } from "../web/src/correction";
import { MAX_FEEDBACK_TEXT_BYTES } from "../worker/src/config";

describe("the corrections form", () => {
  it("sends what is wrong, then where and how, only when given", () => {
    expect(correctionText({ what: " A wrong date. ", when: "", how: "", shot: null })).toBe("A wrong date.");
    expect(correctionText({ what: "A wrong date.", when: "11:07", how: "The 1951 census", shot: "S05" })).toBe(
      "A wrong date.\n\nWhere in the film: 11:07 (S05)\n\nHow they know: The 1951 census",
    );
  });

  it("fits the Worker's byte cap at the fields' own maximum lengths (ASCII)", () => {
    const text = correctionText({ what: "x".repeat(2000), when: "y".repeat(200), how: "z".repeat(500), shot: "S100" });
    expect(new TextEncoder().encode(text).byteLength).toBeLessThanOrEqual(MAX_FEEDBACK_TEXT_BYTES);
  });

  it("understands a time inside the film, a title, or nothing", () => {
    expect(whereIsValid("", 297)).toBe(true);
    expect(whereIsValid("4:20", 297)).toBe(true);
    expect(whereIsValid("17:12", 297)).toBe(false);
    expect(whereIsValid("17:12", null)).toBe(true);
    expect(whereIsValid("Refugees on train roof during Partition", 297)).toBe(true);
    expect(whereIsValid("2:4", 297)).toBe(false);
    expect(whereIsValid("240", 297)).toBe(false);
  });
});
