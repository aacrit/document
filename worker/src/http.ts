// Byte-capped request body reading, shared by every POST handler in
// index.ts. A `Content-Length` header is trusted only as a fast rejection
// (it is attacker-controlled and can lie), so the real enforcement is a
// byte-counting read of the body stream that aborts the moment it passes
// the cap - this also catches a chunked body, which has no Content-Length
// at all. Either way, an oversized body is rejected before its bytes are
// ever handed to JSON.parse.

export type BodyReadResult = { ok: true; text: string } | { ok: false; reason: "too_large" };

export async function readBodyWithCap(request: Request, capBytes: number): Promise<BodyReadResult> {
  const contentLength = request.headers.get("content-length");
  if (contentLength !== null) {
    const declared = Number(contentLength);
    if (Number.isFinite(declared) && declared > capBytes) {
      return { ok: false, reason: "too_large" };
    }
  }

  if (!request.body) {
    return { ok: true, text: "" };
  }

  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    if (value) {
      total += value.byteLength;
      if (total > capBytes) {
        await reader.cancel().catch(() => {});
        return { ok: false, reason: "too_large" };
      }
      chunks.push(value);
    }
  }

  const buffer = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    buffer.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return { ok: true, text: new TextDecoder().decode(buffer) };
}

export type JsonReadResult =
  | { ok: true; body: Record<string, unknown> | null }
  | { ok: false; reason: "too_large" };

// Reads and JSON-parses a request body under a byte cap in one step.
// JSON.parse is only ever reached on the `ok: true` path, i.e. never on a
// body that failed the cap.
export async function readJsonWithCap(request: Request, capBytes: number): Promise<JsonReadResult> {
  const read = await readBodyWithCap(request, capBytes);
  if (!read.ok) return read;

  try {
    const parsed = JSON.parse(read.text);
    const body = typeof parsed === "object" && parsed !== null ? (parsed as Record<string, unknown>) : null;
    return { ok: true, body };
  } catch {
    return { ok: true, body: null };
  }
}
