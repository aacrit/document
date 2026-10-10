import { describe, expect, it } from "vitest";
import { handleMedia, isMediaKey } from "../worker/src/media";

const BODY = new Uint8Array(100).map((_, i) => i);

// A minimal R2Bucket stand-in: one object, honouring a parsed byte range.
function bucket(): R2Bucket {
  return {
    async get(key: string, opts?: { range?: Headers }) {
      if (key !== "maxwell-street/sketch.mp4") return null;
      const header = opts?.range?.get("range") ?? "";
      const m = /^bytes=(\d+)-(\d*)$/.exec(header);
      const range = m ? { offset: Number(m[1]), length: (m[2] ? Number(m[2]) + 1 : BODY.length) - Number(m[1]) } : undefined;
      const slice = range ? BODY.slice(range.offset, range.offset + range.length) : BODY;
      return {
        size: BODY.length,
        httpEtag: '"e1"',
        range,
        body: new Response(slice).body,
        writeHttpMetadata() {},
      };
    },
  } as unknown as R2Bucket;
}

describe("media", () => {
  it("accepts only film-folder keys", () => {
    expect(isMediaKey("maxwell-street/sketch.mp4")).toBe(true);
    expect(isMediaKey("maxwell-street/sources.json")).toBe(true);
    expect(isMediaKey("../secrets.json")).toBe(false);
    expect(isMediaKey("maxwell-street/sketch.exe")).toBe(false);
    expect(isMediaKey("a/b/c.mp4")).toBe(false);
  });

  it("refuses a bad key without reading the bucket", async () => {
    const res = await handleMedia(new Request("https://x/media/x"), { get: () => { throw new Error("read"); } } as unknown as R2Bucket, "../x.mp4");
    expect(res.status).toBe(404);
  });

  it("serves the whole object with its type", async () => {
    const res = await handleMedia(new Request("https://x/"), bucket(), "maxwell-street/sketch.mp4");
    expect(res.status).toBe(200);
    expect(res.headers.get("content-type")).toBe("video/mp4");
    expect(res.headers.get("accept-ranges")).toBe("bytes");
    expect((await res.arrayBuffer()).byteLength).toBe(100);
  });

  it("serves a byte range as 206 with content-range", async () => {
    const req = new Request("https://x/", { headers: { range: "bytes=10-19" } });
    const res = await handleMedia(req, bucket(), "maxwell-street/sketch.mp4");
    expect(res.status).toBe(206);
    expect(res.headers.get("content-range")).toBe("bytes 10-19/100");
    expect(new Uint8Array(await res.arrayBuffer())[0]).toBe(10);
  });

  it("404s a missing object", async () => {
    const res = await handleMedia(new Request("https://x/"), bucket(), "maxwell-street/poster.jpg");
    expect(res.status).toBe(404);
  });
});
