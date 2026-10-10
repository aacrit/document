// Serves films, posters and sources ledgers from R2 at /media/<key>, with
// byte ranges so a <video> can seek. Only keys shaped like a film folder's
// files are read; anything else is a 404 without touching R2.

const KEY = /^[a-z0-9-]+\/[a-z0-9-]+\.(mp4|jpg|json|vtt)$/;
const TYPES: Record<string, string> = {
  mp4: "video/mp4",
  jpg: "image/jpeg",
  json: "application/json",
  vtt: "text/vtt",
};

export function isMediaKey(key: string): boolean {
  return KEY.test(key);
}

export async function handleMedia(request: Request, bucket: R2Bucket, key: string): Promise<Response> {
  if (!isMediaKey(key)) return new Response("not found", { status: 404 });
  const obj = await bucket.get(key, { range: request.headers, onlyIf: request.headers });
  if (obj === null) return new Response("not found", { status: 404 });

  const headers = new Headers();
  obj.writeHttpMetadata(headers);
  headers.set("content-type", TYPES[key.split(".").pop() as string]);
  headers.set("etag", obj.httpEtag);
  headers.set("accept-ranges", "bytes");
  headers.set("cache-control", "public, max-age=3600");

  if (!("body" in obj)) return new Response(null, { status: 304, headers });

  const range = obj.range as { offset?: number; length?: number; suffix?: number } | undefined;
  if (range && request.headers.has("range")) {
    const offset = range.suffix !== undefined ? obj.size - range.suffix : (range.offset ?? 0);
    const length = range.suffix !== undefined ? range.suffix : (range.length ?? obj.size - offset);
    headers.set("content-range", `bytes ${offset}-${offset + length - 1}/${obj.size}`);
    headers.set("content-length", String(length));
    return new Response(request.method === "HEAD" ? null : obj.body, { status: 206, headers });
  }
  headers.set("content-length", String(obj.size));
  return new Response(request.method === "HEAD" ? null : obj.body, { status: 200, headers });
}
