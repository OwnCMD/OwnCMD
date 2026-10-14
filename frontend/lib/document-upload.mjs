export const ARCHIVE_EXTENSIONS = [
  ".zip",
  ".zipx",
  ".7z",
  ".rar",
  ".tar",
  ".gz",
  ".tgz",
  ".bz2",
  ".tbz2",
  ".xz",
  ".txz",
  ".zst",
  ".tzst",
];
export const isArchive = (name) =>
  ARCHIVE_EXTENSIONS.some((ext) => String(name).toLowerCase().endsWith(ext));
async function bounded(fn, signal, timeoutMs = 45000) {
  const controller = new AbortController();
  let timer;
  const abort = () => controller.abort(signal?.reason);
  signal?.addEventListener("abort", abort, { once: true });
  if (signal?.aborted) abort();
  const deadline = new Promise((_, reject) => {
    timer = setTimeout(() => {
      controller.abort();
      reject(new Error("Upload connection timed out. Retry to resume."));
    }, timeoutMs);
  });
  try {
    return await Promise.race([fn(controller.signal), deadline]);
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", abort);
  }
}
export async function uploadDocument(
  file,
  id,
  { request, put, onUpdate, signal, mode = "chat" },
) {
  if (isArchive(file.name) && mode !== "work")
    throw new Error("Switch to Work mode to upload archives.");
  const rawRequest = request,
    rawPut = put;
  request = (path, body, method) =>
    bounded((s) => rawRequest(path, body, method, s), signal);
  put = (id, n, blob) => bounded((s) => rawPut(id, n, blob, s), signal);
  let item = await request(
    "attachments",
    { id, name: file.name, size: file.size, mode },
    "POST",
    signal,
  );
  const state = await request(
      "attachments/" + item.id,
      undefined,
      "GET",
      signal,
    ),
    parts = new Set(state.parts || []);
  if (state.status === "ready") {
    onUpdate(state);
    return state;
  }
  onUpdate({ ...state, status: "uploading" });
  if (state.status === "uploading") {
    for (
      let offset = 0, ordinal = 0;
      offset < file.size;
      offset += item.part_size, ordinal++
    ) {
      if (parts.has(ordinal)) continue;
      let error;
      for (let attempt = 0; attempt < 2; attempt++) {
        try {
          item = await put(
            item.id,
            ordinal,
            file.slice(offset, offset + item.part_size),
            signal,
          );
          error = null;
          break;
        } catch (e) {
          if (signal?.aborted) throw e;
          error = e;
        }
      }
      if (error) throw error;
      onUpdate({ ...item, status: "uploading" });
    }
  }
  item = await request(`attachments/${item.id}/complete`, {}, "POST", signal);
  onUpdate(item);
  const deadline = Date.now() + 12 * 60 * 1000;
  while (Date.now() < deadline) {
    if (signal?.aborted)
      throw new DOMException("Upload cancelled", "AbortError");
    item = await request("attachments/" + item.id, undefined, "GET", signal);
    onUpdate(item);
    if (item.status === "ready") return item;
    if (item.status === "failed")
      throw new Error(item.info?.error || "Document could not be processed");
    await new Promise((resolve, reject) => {
      const abort = () => {
        clearTimeout(timer);
        reject(new DOMException("Upload cancelled", "AbortError"));
      };
      const timer = setTimeout(() => {
        signal?.removeEventListener("abort", abort);
        resolve();
      }, 1500);
      signal?.addEventListener("abort", abort, { once: true });
    });
  }
  throw new Error(
    "Processing is taking longer than expected. Retry to check its status.",
  );
}
