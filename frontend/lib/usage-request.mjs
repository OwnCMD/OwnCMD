// A stalled fetch must not hold the Usage view's refresh lock forever.
export async function loadUsage(
  params,
  request,
  { signal, timeoutMs = 12000 } = {},
) {
  let lastError;
  for (let attempt = 0; attempt < 2; attempt++) {
    if (signal?.aborted) throw new DOMException("Cancelled", "AbortError");
    const controller = new AbortController();
    let timer, cancel;
    const aborted = new Promise((_, reject) => {
      cancel = () => {
        controller.abort();
        reject(new DOMException("Cancelled", "AbortError"));
      };
      signal?.addEventListener("abort", cancel, { once: true });
      timer = setTimeout(() => {
        controller.abort();
        reject(new Error("Usage took too long to load. Please retry."));
      }, timeoutMs);
    });
    try {
      // Each retry/poll gets a fresh URL, including the default 30-day period.
      const suffix = `_refresh=${Date.now()}-${attempt}-${Math.random().toString(36).slice(2)}`;
      return await Promise.race([
        request(`usage?${params}&${suffix}`, controller.signal),
        aborted,
      ]);
    } catch (error) {
      if (signal?.aborted) throw new DOMException("Cancelled", "AbortError");
      lastError = error;
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener("abort", cancel);
    }
  }
  throw lastError;
}
