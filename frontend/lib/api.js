import { clientDisplay } from "./browser-display.mjs";
let csrf = "";
export const setCSRF = (value) => {
  csrf = value;
};
export async function uploadSupport(file) {
  const response = await fetch(
    "/api/support/uploads?name=" + encodeURIComponent(file.name),
    {
      method: "PUT",
      credentials: "same-origin",
      headers: { "Content-Type": "application/octet-stream", "X-CSRF": csrf },
      body: file,
    },
  );
  const data = await response.json();
  if (!response.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : "Attachment upload failed",
    );
  return data;
}
export async function api(path, body, method = "POST", signal) {
  if (path === "tasks" && body?.prompt)
    body = { ...body, browser_display: clientDisplay() };
  const response = await fetch("/api/" + path, {
    credentials: "same-origin",
    cache: "no-store",
    signal,
    ...(body === undefined
      ? {}
      : {
          method,
          headers: { "Content-Type": "application/json", "X-CSRF": csrf },
          body: JSON.stringify(body),
        }),
  });
  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error(
      "The server returned an unreadable response. Please try again.",
    );
  }
  if (!response.ok) {
    if (
      response.status === 401 &&
      !["login", "change-password", "me"].includes(path)
    )
      window.dispatchEvent(new Event("aster:signout"));
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : "This request could not be completed.",
    );
  }
  return data;
}
export const defaults = {
  theme: "system",
  font: "inter",
  font_size: "medium",
  density: "comfortable",
  send_enter: true,
  reduce_motion: false,
  sources_expanded: false,
  activity_expanded: false,
};
export function safeURL(value) {
  try {
    const u = new URL(
      value,
      typeof location === "undefined" ? "https://localhost" : location.origin,
    );
    return ["https:", "http:"].includes(u.protocol) ? u.href : "#";
  } catch {
    return "#";
  }
}
export async function copyText(value) {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(value);
      return;
    } catch {
      /* Browser policy may deny clipboard; try selection-based copy. */
    }
  }
  const node = document.createElement("textarea");
  node.value = value;
  node.style.position = "fixed";
  node.style.opacity = "0";
  document.body.append(node);
  node.select();
  const ok = document.execCommand("copy");
  node.remove();
  if (!ok)
    throw new Error(
      "Copy is unavailable in this browser. Select the text and copy it.",
    );
}

// Best-effort close on navigation/page exit. The server also expires abandoned chats.
export function discardTemporary(id) {
  if (!id?.startsWith("tmp-")) return;
  fetch("/api/tasks/" + encodeURIComponent(id), {
    method: "DELETE",
    credentials: "same-origin",
    cache: "no-store",
    keepalive: true,
    headers: { "Content-Type": "application/json", "X-CSRF": csrf },
    body: "{}",
  }).catch(() => {});
}
export async function uploadPart(id, ordinal, blob, signal) {
  const r = await fetch(
    `/api/attachments/${encodeURIComponent(id)}/parts/${ordinal}`,
    {
      method: "PUT",
      credentials: "same-origin",
      headers: { "Content-Type": "application/octet-stream", "X-CSRF": csrf },
      body: blob,
      signal,
    },
  );
  const data = await r.json();
  if (!r.ok) throw new Error(data.detail || "Upload failed");
  return data;
}
