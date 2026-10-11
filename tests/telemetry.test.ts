// The client's events (web/src/telemetry.ts): film_completed is counted
// once per page load when the film reaches its last frame; source_opened
// when an archive's item link is opened.
import { afterEach, describe, expect, it, vi } from "vitest";
import { countCompletionOnce, countSourceOpens, reportCoreSuccess, sendEvent } from "../web/src/telemetry";

afterEach(() => vi.unstubAllGlobals());

describe("film_completed", () => {
  it("fires on the first `ended` only, however often the film ends again", () => {
    const film = new EventTarget();
    const report = vi.fn();
    countCompletionOnce(film, report);
    expect(report).not.toHaveBeenCalled();
    film.dispatchEvent(new Event("timeupdate"));
    film.dispatchEvent(new Event("pause"));
    expect(report).not.toHaveBeenCalled();
    film.dispatchEvent(new Event("ended"));
    film.dispatchEvent(new Event("ended"));
    film.dispatchEvent(new Event("play"));
    film.dispatchEvent(new Event("ended"));
    expect(report).toHaveBeenCalledTimes(1);
  });

  it("waits until enough was watched: an end reached by seeking does not count", () => {
    const film = new EventTarget();
    const report = vi.fn();
    let watched = false;
    countCompletionOnce(film, report, () => watched);
    film.dispatchEvent(new Event("ended"));
    expect(report).not.toHaveBeenCalled();
    watched = true;
    film.dispatchEvent(new Event("ended"));
    film.dispatchEvent(new Event("ended"));
    expect(report).toHaveBeenCalledTimes(1);
  });

  it("can be detached before the end, and then never fires", () => {
    const film = new EventTarget();
    const report = vi.fn();
    countCompletionOnce(film, report)();
    film.dispatchEvent(new Event("ended"));
    expect(report).not.toHaveBeenCalled();
  });

  it("is sent to /e as same-origin JSON with only the event name", () => {
    const fetchMock = vi.fn(() => Promise.resolve(new Response(null, { status: 202 })));
    vi.stubGlobal("fetch", fetchMock);
    reportCoreSuccess();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/e");
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>)["content-type"]).toBe("application/json");
    expect(JSON.parse(String(init.body))).toEqual({ name: "film_completed" });
  });

  it("swallows a failed send", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("offline"))));
    expect(() => sendEvent("page_view")).not.toThrow();
    await new Promise((r) => setTimeout(r, 0));
  });
});

describe("source_opened", () => {
  // A minimal event target standing in for the page, with a click target that knows its closest link.
  function click(type: string, matches: boolean, button = 0) {
    const root = new EventTarget();
    const send = vi.fn();
    countSourceOpens(root, send);
    const ev = new Event(type) as Event & { button: number };
    Object.defineProperty(ev, "button", { value: button });
    Object.defineProperty(ev, "target", { value: { closest: (sel: string) => (matches && sel === "a.source[data-item]" ? {} : null) } });
    root.dispatchEvent(ev);
    return send;
  }

  it("fires when an archive item link is clicked or middle-clicked", () => {
    expect(click("click", true)).toHaveBeenCalledWith("source_opened");
    expect(click("auxclick", true, 1)).toHaveBeenCalledWith("source_opened");
  });

  it("does not fire for other links, or a right-click", () => {
    expect(click("click", false)).not.toHaveBeenCalled();
    expect(click("auxclick", true, 2)).not.toHaveBeenCalled();
  });
});
