// Bounded binary framing. Network chunks may split any header or image boundary.
export class FrameDecoder {
  constructor(onFrame) {
    this.buffer = new Uint8Array();
    this.onFrame = onFrame;
  }
  push(chunk) {
    if (!(chunk instanceof Uint8Array)) throw Error("Invalid preview data");
    let offset = 0;
    // Consume in bounded pieces even when a proxy combines many frames.
    while (offset < chunk.length) {
      const count = Math.min(65536, chunk.length - offset);
      const combined = new Uint8Array(this.buffer.length + count);
      combined.set(this.buffer);
      combined.set(chunk.subarray(offset, offset + count), this.buffer.length);
      this.buffer = combined;
      offset += count;
      while (this.buffer.length >= 4) {
        const header = new DataView(
          this.buffer.buffer,
          this.buffer.byteOffset,
          4,
        ).getUint32(0);
        if (!header || header > 8192) throw Error("Invalid preview header");
        if (this.buffer.length < 4 + header) break;
        const metadata = JSON.parse(
          new TextDecoder().decode(this.buffer.subarray(4, 4 + header)),
        );
        const length = metadata.length;
        if (!Number.isInteger(length) || length < 0 || length > 4 * 1024 * 1024)
          throw Error("Invalid preview frame size");
        const end = 4 + header + length;
        if (this.buffer.length < end) break;
        this.onFrame(
          metadata,
          length ? this.buffer.slice(4 + header, end) : null,
        );
        this.buffer = this.buffer.slice(end);
      }
    }
  }
  finish() {
    if (this.buffer.length) throw Error("Incomplete preview frame");
  }
}

export async function readFrameStream(url, signal, onFrame) {
  const response = await fetch(url, {
    signal,
    credentials: "same-origin",
    cache: "no-store",
  });
  if (
    !response.ok ||
    !response.headers
      .get("content-type")
      ?.startsWith("application/x-owncmd-frames")
  ) {
    await response.body?.cancel();
    const error = Error("Preview stream unavailable");
    error.status = response.status;
    throw error;
  }
  const reader = response.body.getReader(),
    decoder = new FrameDecoder(onFrame);
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      decoder.push(value);
    }
    decoder.finish();
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
