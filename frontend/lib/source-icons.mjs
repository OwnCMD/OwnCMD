import { sourceIcons, sourceKey } from "./sources.mjs";
// Share discovery and failures by origin. A late result can supply the icon for
// earlier citations too; components never race through independent fallbacks.
export function createSourceIconStore(load) {
  const entries = new Map();
  function entry(host) {
    if (!entries.has(host))
      entries.set(host, {
        url: "",
        candidates: [],
        failed: new Set(),
        listeners: new Set(),
        loading: false,
      });
    return entries.get(host);
  }
  async function next(e) {
    if (e.loading || e.url) return;
    const candidate = e.candidates.find((url) => !e.failed.has(url));
    if (!candidate) return;
    e.loading = true;
    try {
      await load(candidate);
      e.url = candidate;
    } catch {
      e.failed.add(candidate);
    } finally {
      e.loading = false;
      for (const fn of e.listeners) fn();
      if (!e.url) next(e);
    }
  }
  return {
    subscribe(host, fn) {
      const e = entry(host);
      e.listeners.add(fn);
      return () => {
        e.listeners.delete(fn);
        if (entries.size > 512)
          for (const [key, item] of entries) {
            if (!item.listeners.size && !item.loading) entries.delete(key);
            if (entries.size <= 512) break;
          }
      };
    },
    get(host) {
      return entries.get(host)?.url || "";
    },
    add(rows) {
      for (const row of rows) {
        const key = sourceKey(row);
        if (!key) continue;
        const e = entry(new URL(key).host);
        for (const url of sourceIcons(row))
          if (!e.candidates.includes(url)) e.candidates.push(url);
      }
      for (const e of entries.values()) if (e.listeners.size) next(e);
    },
    failed(host, url) {
      const e = entry(host);
      if (e.url !== url) return;
      e.failed.add(url);
      e.url = "";
      for (const fn of e.listeners) fn();
      next(e);
    },
  };
}
export const sourceIconStore = createSourceIconStore(
  (url) =>
    new Promise((resolve, reject) => {
      const img = new Image();
      const timer = setTimeout(() => {
        img.onload = img.onerror = null;
        reject(new Error("Icon timeout"));
      }, 6000);
      img.referrerPolicy = "no-referrer";
      img.onload = () => {
        clearTimeout(timer);
        resolve();
      };
      img.onerror = () => {
        clearTimeout(timer);
        reject(new Error("Icon unavailable"));
      };
      img.src = url;
    }),
);
