// scripts/lint-events.mjs (doctrine L-25): the success event must be the
// product's own core action, allowed, counted by the kill criteria, and sent
// by some code. Fixtures, so this passes while the template still carries
// its placeholder; the gate step itself fails on the real files until the
// product renames it.

import { describe, expect, it } from "vitest";
import { checkSuccessEvent, hasCallSite, killCriteriaSection, PLACEHOLDER, stripComments } from "../scripts/lint-events.mjs";

const charter = (name: string) =>
  `# Charter\n\n| Surface | Why |\n\n## Kill criteria\n\n- 2027-01-31: fewer than 20 \`${name}\` in total.\n\n## Not in v1\n\n- Accounts.\n`;
const contract = (name: string | undefined, extra: { allowed?: string[]; server_only?: string[] } = {}) => ({
  success_event: name,
  events: { allowed: extra.allowed ?? ["page_view", name ?? "x", "feedback_received"], server_only: extra.server_only ?? ["feedback_received"] },
});
const sent = (name: string) => ({ "web/src/main.ts": `button.onclick = () => sendEvent("${name}");` });

describe("checkSuccessEvent", () => {
  it("passes a named core event that is allowed, in the kill criteria, and sent", () => {
    expect(checkSuccessEvent({ contract: contract("pdf_exported"), charterText: charter("pdf_exported"), sources: sent("pdf_exported") })).toEqual([]);
  });

  it("fails the template placeholder (Rollbook's defect was a working default nobody renamed)", () => {
    const v = checkSuccessEvent({ contract: contract(PLACEHOLDER), charterText: charter(PLACEHOLDER), sources: sent(PLACEHOLDER) });
    expect(v.join("\n")).toMatch(/still the template placeholder/);
  });

  it("fails the generic names: success, page_view, feedback", () => {
    for (const name of ["success", "page_view", "feedback_received"]) {
      const v = checkSuccessEvent({ contract: contract(name), charterText: charter(name), sources: sent(name) });
      expect(v.join("\n"), name).toMatch(/is generic/);
    }
  });

  it("fails when it is missing, not allowed, or server-only", () => {
    expect(checkSuccessEvent({ contract: contract(undefined), charterText: charter("x"), sources: {} })[0]).toMatch(/no success_event/);
    const notAllowed = checkSuccessEvent({
      contract: contract("order_placed", { allowed: ["page_view"] }),
      charterText: charter("order_placed"),
      sources: sent("order_placed"),
    });
    expect(notAllowed.join("\n")).toMatch(/not in contract.yaml events.allowed/);
    const serverOnly = checkSuccessEvent({
      contract: contract("order_placed", { allowed: ["order_placed"], server_only: ["order_placed"] }),
      charterText: charter("order_placed"),
      sources: sent("order_placed"),
    });
    expect(serverOnly.join("\n")).toMatch(/server-only/);
  });

  it("fails when CHARTER.md's kill criteria do not name it, or have no section", () => {
    const other = checkSuccessEvent({ contract: contract("order_placed"), charterText: charter("page_view"), sources: sent("order_placed") });
    expect(other.join("\n")).toMatch(/kill criteria never name `order_placed`/);
    const none = checkSuccessEvent({ contract: contract("order_placed"), charterText: "# Charter\n\n`order_placed`\n", sources: sent("order_placed") });
    expect(none.join("\n")).toMatch(/no "## Kill criteria" section/);
  });

  it("fails when nothing sends it", () => {
    const v = checkSuccessEvent({
      contract: contract("order_placed"),
      charterText: charter("order_placed"),
      sources: { "web/src/main.ts": 'sendEvent("page_view");' },
    });
    expect(v.join("\n")).toMatch(/nothing in web\/src or worker\/src sends/);
  });

  it("fails when the only mention is the unused reportCoreSuccess wrapper (the template's own state after a rename)", () => {
    const wrapperOnly = {
      "web/src/main.ts": `function sendEvent(name: string): void {}\n\nexport function reportCoreSuccess(): void {\n  sendEvent("order_placed");\n}\n\nsendEvent("page_view");\n`,
    };
    const v = checkSuccessEvent({ contract: contract("order_placed"), charterText: charter("order_placed"), sources: wrapperOnly });
    expect(v.join("\n")).toMatch(/nothing in web\/src or worker\/src sends "order_placed"/);
  });

  it("passes when the wrapper is called where the action completes, in this file or another", () => {
    const wrapper = `export function reportCoreSuccess(): void {\n  sendEvent("order_placed");\n}\n`;
    const same = { "web/src/main.ts": `${wrapper}\nbutton.addEventListener("click", () => reportCoreSuccess());\n` };
    const other = { "web/src/main.ts": wrapper, "web/src/checkout.tsx": `import { reportCoreSuccess } from "./main";\nonPaid(() => reportCoreSuccess());\n` };
    for (const sources of [same, other]) {
      expect(checkSuccessEvent({ contract: contract("order_placed"), charterText: charter("order_placed"), sources })).toEqual([]);
    }
  });

  it("counts a direct send by template literal, and scans .vue and .svelte sources", () => {
    const templ = { "web/src/App.vue": "<script setup>\nfetch('/e', { body: JSON.stringify({ name: `order_placed` }) });\n</script>" };
    expect(hasCallSite("order_placed", templ)).toBe(true);
    expect(hasCallSite("order_placed", { "web/src/x.svelte": "sendEvent('order_placed_later')" })).toBe(false);
  });

  it("fails when a comment is the only place that names the call or the event", () => {
    const wrapper = `export function reportCoreSuccess(): void {\n  sendEvent("order_placed");\n}\n`;
    for (const comment of [
      "// TODO: call reportCoreSuccess() when the order is placed",
      "/* later: reportCoreSuccess(); */",
      '// sendEvent("order_placed");',
      "<!-- reportCoreSuccess() on submit -->",
    ]) {
      const v = checkSuccessEvent({ contract: contract("order_placed"), charterText: charter("order_placed"), sources: { "web/src/main.ts": `${wrapper}\n${comment}\n` } });
      expect(v.join("\n"), comment).toMatch(/nothing in web\/src or worker\/src sends "order_placed"/);
    }
    // A URL in a string is not a comment.
    expect(stripComments('fetch("https://x.example"); reportCoreSuccess();')).toContain("reportCoreSuccess()");
  });

  it("reads only the kill-criteria section, not the whole charter", () => {
    expect(killCriteriaSection(charter("a"))).toContain("`a`");
    expect(killCriteriaSection(charter("a"))).not.toContain("Accounts");
  });
});
