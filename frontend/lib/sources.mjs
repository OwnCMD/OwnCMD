export function sourceKey(row) {
  try {
    const u = new URL(row?.url);
    if (!["http:", "https:"].includes(u.protocol)) return "";
    u.hash = "";
    return u.href;
  } catch {
    return "";
  }
}
export function uniqueSources(rows = []) {
  const seen = new Set();
  return rows.filter((row) => {
    const key = sourceKey(row);
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}
export function remainingSources(rows = [], messages = []) {
  const used = new Set(
    messages
      .filter((m) => m.role === "assistant")
      .flatMap((m) => (m.sources || []).map(sourceKey)),
  );
  return uniqueSources(rows).filter((row) => !used.has(sourceKey(row)));
}
export function sourceIcons(row) {
  const icons = [];
  try {
    const u = new URL(row.favicon);
    if (u.protocol === "https:" && !u.username && !u.password)
      icons.push(u.href);
  } catch {}
  const key = sourceKey(row);
  if (key) icons.push("https://" + new URL(key).host + "/favicon.ico");
  return [...new Set(icons)];
}
