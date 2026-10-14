"use client";
import { sourceIconStore } from "../lib/source-icons.mjs";
import { useEffect, useMemo, useRef, useId, useState } from "react";
import { copyText, safeURL } from "../lib/api";
import { uniqueSources } from "../lib/sources.mjs";
const paths = {
  info: "M12 11v6M12 7h.01M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0",
  help: "M9 9a3 3 0 0 1 6 0c0 2-3 2-3 4M12 17h.01M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0",
  activity: "M3 12h4l3-7 4 14 3-7h4",
  user: "M16 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0M4 21v-3a8 8 0 0 1 16 0v3",
  plus: "M12 5v14M5 12h14",
  search: "M21 21l-5-5M19 10.5a8.5 8.5 0 1 1-17 0 8.5 8.5 0 0 1 17 0",
  arrow: "M12 19V5m-6 6 6-6 6 6",
  chevron: "m9 5 7 7-7 7",
  close: "m6 6 12 12M6 18 18 6",
  menu: "M4 6h16M4 12h16M4 18h16",
  temporary:
    "M8 3.7a9 9 0 0 1 5-.6M17 4.5a9 9 0 0 1 3 3M21 12a9 9 0 0 1-1.5 5M16 20a9 9 0 0 1-5 .8M7 20H3l1.2-4M3.2 12a9 9 0 0 1 1.5-5M9 10h6M9 14h3",
  chat: "M21 11.5a8.5 8.5 0 0 1-8.5 8.5H3l1.8-5A8.5 8.5 0 1 1 21 11.5",
  work: "M8 6V4h8v2M3 7h18v14H3zM3 12h18M10 12v3h4v-3",
  clock: "M12 8v4l3 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0",
  memory: "M9 3H5v4M15 3h4v4M5 17v4h4M19 17v4h-4M8 8h8v8H8z",
  settings: "M4 7h16M4 17h16M8 4v6M16 14v6",
  logout: "M9 4H4v16h5M10 12h11m-4-4 4 4-4 4",
  trash: "M3 6h18M9 6V3h6v3M6 6l1 15h10l1-15M10 10v7M14 10v7",
  attach: "m8 13 7-7a3 3 0 0 1 4 4l-9 9a5 5 0 0 1-7-7l9-9",
  globe:
    "M3 12h18M12 3c6 6 6 12 0 18-6-6-6-12 0-18M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0",
  check: "m5 12 4 4L19 6",
  folder: "M3 6h6l2 2h10v12H3z",
  folderOpen: "M3 18V6h6l2 2h10v3M3 20l3-9h17l-3 9z",
  collapse: "M8 3H3v5M16 3h5v5M21 16v5h-5M3 16v5h5M8 12h8",
  file: "M5 3h9l5 5v13H5zM14 3v6h5M8 13h8M8 17h6",
  copy: "M9 9h12v12H9zM5 15H3V3h12v2",
  external: "M14 3h7v7M21 3 10 14M10 3H3v18h18v-7",
  browser: "M3 4h18v16H3zM3 9h18M6 6.5h.01M9 6.5h.01",
  pause: "M8 5v14M16 5v14",
  play: "m7 4 14 8-14 8z",
  stop: "M6 6h12v12H6z",
  refresh:
    "M20 7V3m0 4h-4M4 17v4m0-4h4M20 7a9 9 0 0 0-16 4M4 17a9 9 0 0 0 16-4",
  expand: "M8 3H3v5M16 3h5v5M21 16v5h-5M3 16v5h5",
  down: "M12 4v16m-6-6 6 6 6-6",
  sun: "M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5 19 19M5 19l1.5-1.5M17.5 6.5 19 5M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0",
  moon: "M20 15A9 9 0 0 1 9 4a9 9 0 1 0 11 11",
  monitor: "M3 4h18v13H3zM8 21h8M12 17v4",
  shield: "m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6z",
  code: "m8 7-5 5 5 5M16 7l5 5-5 5M14 4l-4 16",
  spark: "M12 3v18M3 12h18M5.6 5.6l12.8 12.8M5.6 18.4 18.4 5.6",
};
export function Icon({ name, size = 18, ...props }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.65"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      <path d={paths[name] || paths.spark} />
    </svg>
  );
}
export function Logo({ small = false }) {
  return (
    <span className={"logo " + (small ? "small" : "")}>
      <svg
        width={small ? 24 : 32}
        height={small ? 24 : 32}
        viewBox="0 0 32 32"
        fill="none"
        aria-hidden="true"
      >
        <rect
          x="3"
          y="3"
          width="26"
          height="26"
          rx="8"
          stroke="currentColor"
          strokeWidth="2.5"
        />
        <path
          d="m10 11 5 5-5 5m8 0h5"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </span>
  );
}
export function IconButton({ name, label, ...props }) {
  return (
    <button
      type="button"
      className="icon-button"
      title={label}
      aria-label={label}
      {...props}
    >
      <Icon name={name} />
    </button>
  );
}
export function Modal({ title, children, onClose, wide = false }) {
  const ref = useRef(),
    id = useId();
  useEffect(() => {
    const previous = document.activeElement;
    const node = ref.current;
    node.showModal();
    return () => {
      node.close();
      if (previous?.isConnected) previous.focus();
    };
  }, []);
  return (
    <dialog
      ref={ref}
      className={"modal " + (wide ? "wide" : "")}
      aria-labelledby={id}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      onClick={(e) => {
        if (e.target === ref.current) {
          const r = ref.current.getBoundingClientRect();
          if (
            e.clientX < r.left ||
            e.clientX > r.right ||
            e.clientY < r.top ||
            e.clientY > r.bottom
          )
            onClose();
        }
      }}
    >
      <div className="modal-head">
        <h2 id={id}>{title}</h2>
        <IconButton name="close" label="Close dialog" onClick={onClose} />
      </div>
      {children}
    </dialog>
  );
}
function SourceIcon({ source }) {
  const host = new URL(source.url).host,
    display = host.replace(/^www\./, "");
  const [icon, setIcon] = useState(() => sourceIconStore.get(host));
  useEffect(() => {
    const update = () => setIcon(sourceIconStore.get(host));
    const unsubscribe = sourceIconStore.subscribe(host, update);
    sourceIconStore.add([source]);
    update();
    return unsubscribe;
  }, [host, source.favicon]);
  return (
    <span className="source-symbol" aria-hidden="true">
      {!icon ? (
        display[0].toUpperCase()
      ) : (
        <img
          src={icon}
          alt=""
          loading="lazy"
          referrerPolicy="no-referrer"
          onError={() => sourceIconStore.failed(host, icon)}
        />
      )}
    </span>
  );
}
export function Sources({ rows = [], expanded = false }) {
  rows = uniqueSources(rows);
  if (!rows.length) return null;
  return (
    <details className="sources" open={expanded || undefined}>
      <summary>
        <span className="source-icon-stack">
          {rows
            .filter(
              (s, i, a) =>
                a.findIndex(
                  (x) => new URL(x.url).hostname === new URL(s.url).hostname,
                ) === i,
            )
            .slice(0, 3)
            .map((s) => (
              <SourceIcon key={s.url} source={s} />
            ))}
        </span>
        {rows.length} {rows.length === 1 ? "source" : "sources"}
        <Icon name="chevron" size={14} />
      </summary>
      <div className="source-grid">
        {rows.map((s, i) => (
          <a
            key={i}
            href={safeURL(s.url)}
            target="_blank"
            rel="noopener noreferrer"
          >
            <SourceIcon key={s.url} source={s} />
            <span>
              <strong>{s.title || s.domain || "Source"}</strong>
              <small>{new URL(s.url).hostname.replace(/^www\./, "")}</small>
            </span>
            <Icon name="external" size={14} />
          </a>
        ))}
      </div>
    </details>
  );
}
const SAFE_IMAGE =
  /^data:image\/(?:jpeg|png|webp|gif);base64,[A-Za-z0-9+/=]+$/i;
function escapeHTML(value) {
  return String(value || "").replace(
    /[&<>\"']/g,
    (c) =>
      ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '\"': "&quot;",
        "'": "&#39;",
      })[c],
  );
}
function streamingMarkdown(value) {
  const lines = String(value || "")
      .replace(/\r/g, "")
      .split("\n"),
    out = [];
  let code = false,
    codeLines = [];
  const inline = (line) =>
    escapeHTML(line)
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/\*([^*]+)\*/g, "<em>$1</em>")
      .replace(
        /\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g,
        (_, label, url) =>
          `<a href=\"${escapeHTML(url)}\" target=\"_blank\" rel=\"noopener noreferrer\">${label}</a>`,
      );
  for (const line of lines) {
    if (/^```/.test(line)) {
      if (code) {
        out.push(`<pre><code>${escapeHTML(codeLines.join("\n"))}</code></pre>`);
        codeLines = [];
      }
      code = !code;
      continue;
    }
    if (code) {
      codeLines.push(line);
      continue;
    }
    if (!line.trim()) continue;
    const heading = line.match(/^(#{1,3})\s+(.+)/);
    if (heading) {
      out.push(
        `<h${heading[1].length}>${inline(heading[2])}</h${heading[1].length}>`,
      );
      continue;
    }
    if (/^[-*]\s+/.test(line)) {
      out.push(`<ul><li>${inline(line.replace(/^[-*]\s+/, ""))}</li></ul>`);
      continue;
    }
    if (/^\d+\.\s+/.test(line)) {
      out.push(`<ol><li>${inline(line.replace(/^\d+\.\s+/, ""))}</li></ol>`);
      continue;
    }
    out.push(`<p>${inline(line)}</p>`);
  }
  if (code)
    out.push(`<pre><code>${escapeHTML(codeLines.join("\n"))}</code></pre>`);
  return out.join("");
}
export function ImageStrip({ images = [] }) {
  const [selected, setSelected] = useState(null),
    [zoom, setZoom] = useState(false);
  const valid = images
    .map((item) =>
      typeof item === "string" ? item : item?.url || item?.dataUrl,
    )
    .filter((url) => SAFE_IMAGE.test(url || ""));
  function move(amount) {
    setSelected((n) => (n + amount + valid.length) % valid.length);
    setZoom(false);
  }
  useEffect(() => {
    if (selected === null) return;
    const key = (event) => {
      if (event.key === "ArrowRight") {
        event.preventDefault();
        move(1);
      }
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        move(-1);
      }
    };
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, [selected, valid.length]);
  if (!valid.length) return null;
  return (
    <>
      <div
        className={"image-strip " + (valid.length === 1 ? "single" : "gallery")}
        aria-label={`${valid.length} attached images`}
      >
        {valid.map((url, i) => (
          <button
            type="button"
            className="image-tile"
            key={i}
            aria-label={`View attached image ${i + 1}`}
            onClick={() => {
              setSelected(i);
              setZoom(false);
            }}
          >
            <img src={url} alt={`Attached image ${i + 1}`} loading="lazy" />
            <span>
              <Icon name="expand" size={15} /> View image
            </span>
          </button>
        ))}
      </div>
      {selected !== null && (
        <Modal
          title={`Image ${selected + 1} of ${valid.length}`}
          wide
          onClose={() => setSelected(null)}
        >
          <div className="image-viewer-toolbar">
            <span>Use arrow keys to browse</span>
            <div>
              <button className="button small" onClick={() => setZoom(!zoom)}>
                {zoom ? "Fit to window" : "Actual size"}
              </button>
              <a
                className="button small"
                href={valid[selected]}
                download={`aster-image-${selected + 1}`}
              >
                Download
              </a>
            </div>
          </div>
          <div className={"image-viewer-stage " + (zoom ? "zoom" : "")}>
            <img src={valid[selected]} alt={`Attached image ${selected + 1}`} />
          </div>
          {valid.length > 1 && (
            <div className="image-viewer-nav">
              <IconButton
                name="chevron"
                label="Previous image"
                style={{ transform: "rotate(180deg)" }}
                onClick={() => move(-1)}
              />
              <div>
                {valid.map((url, i) => (
                  <button
                    className={selected === i ? "selected" : ""}
                    key={i}
                    aria-label={`Show image ${i + 1}`}
                    aria-pressed={selected === i}
                    onClick={() => {
                      setSelected(i);
                      setZoom(false);
                    }}
                  >
                    <img src={url} alt="" />
                  </button>
                ))}
              </div>
              <IconButton
                name="chevron"
                label="Next image"
                onClick={() => move(1)}
              />
            </div>
          )}
        </Modal>
      )}
    </>
  );
}
export function Markdown({ html, text, onPreview }) {
  const ref = useRef();
  const streamedHTML = useMemo(
    () => (html || !text ? "" : streamingMarkdown(text)),
    [html, text],
  );
  useEffect(() => {
    const root = ref.current;
    if (!root) return;
    root.querySelectorAll("a").forEach((a) => {
      if (!a.getAttribute("href")) {
        a.removeAttribute("target");
        return;
      }
      a.href = safeURL(a.getAttribute("href"));
      const resolved = new URL(a.href, location.origin);
      if (
        resolved.origin === location.origin &&
        /^\/api\/tasks\/[^/]+\/download$/.test(resolved.pathname)
      ) {
        a.removeAttribute("target");
        a.setAttribute("download", "");
        a.onclick = null;
        a.rel = "noopener noreferrer";
        return;
      }
      let port = null,
        path = "/";
      try {
        const url = new URL(a.href, location.origin);
        if (
          ["127.0.0.1", "localhost", "0.0.0.0", "[::1]"].includes(url.hostname)
        ) {
          port = Number(url.port || 80);
          path = url.pathname + url.search + url.hash;
        } else if (
          url.origin === location.origin &&
          url.hash.includes("?preview=")
        ) {
          const query = new URLSearchParams(
            url.hash.slice(url.hash.indexOf("?") + 1),
          );
          port = Number(query.get("preview"));
          path = query.get("path") || "/";
        }
      } catch {}
      if (
        onPreview &&
        Number.isInteger(port) &&
        port >= 1024 &&
        port <= 65535 &&
        port !== 8001
      ) {
        a.removeAttribute("target");
        a.onclick = (event) => {
          event.preventDefault();
          onPreview(port, path);
        };
        a.title = "Open in your private OwnCMD workspace";
      } else a.target = "_blank";
      a.rel = "noopener noreferrer";
    });
    const clean = [];
    root.querySelectorAll("pre").forEach((pre) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "code-copy";
      button.textContent = "Copy code";
      const click = async () => {
        try {
          await copyText(pre.querySelector("code")?.textContent || text || "");
          button.textContent = "Copied";
        } catch {
          button.textContent = "Select to copy";
        }
      };
      button.addEventListener("click", click);
      pre.append(button);
      clean.push(() => button.remove());
    });
    return () => clean.forEach((f) => f());
  }, [html, text, onPreview]);
  return html || streamedHTML ? (
    <div
      ref={ref}
      className="markdown"
      dangerouslySetInnerHTML={{ __html: html || streamedHTML }}
    />
  ) : (
    <div ref={ref} className="markdown plain">
      {text}
    </div>
  );
}
export function CodeViewer({
  html = "",
  content = "",
  language = "File",
  truncated = false,
}) {
  const [wrap, setWrap] = useState(false),
    [copied, setCopied] = useState(false);
  return (
    <div className="code-viewer">
      <div className="code-viewer-toolbar">
        <div className="code-viewer-file">
          <Icon name="code" size={15} />
          <strong>{language || "Plain text"}</strong>
          <span>Read only</span>
          {truncated && <span>Preview truncated</span>}
        </div>
        <div className="code-viewer-actions">
          <button
            type="button"
            className="code-tool"
            onClick={() => setWrap(!wrap)}
            aria-pressed={wrap}
          >
            {wrap ? "Unwrap lines" : "Wrap lines"}
          </button>
          <button
            type="button"
            className="code-tool"
            onClick={async () => {
              try {
                await copyText(content);
                setCopied(true);
                setTimeout(() => setCopied(false), 1600);
              } catch {}
            }}
          >
            {copied ? "Copied" : "Copy"}
          </button>
        </div>
      </div>
      <div className={"code-viewer-scroll " + (wrap ? "wrap" : "")}>
        {html ? (
          <div
            className="code-html"
            dangerouslySetInnerHTML={{ __html: html }}
          />
        ) : (
          <pre>
            <code>{content}</code>
          </pre>
        )}
      </div>
    </div>
  );
}
export function CopyButton({ text, notify }) {
  const [copied, setCopied] = useState(false);
  return (
    <IconButton
      name={copied ? "check" : "copy"}
      label={copied ? "Copied" : "Copy response"}
      onClick={async () => {
        try {
          await copyText(text || "");
          setCopied(true);
        } catch (e) {
          notify(e.message);
        }
      }}
    />
  );
}
export function Empty({ icon, title, children }) {
  return (
    <div className="empty">
      <span className="empty-icon">
        <Icon name={icon} size={26} />
      </span>
      <h2>{title}</h2>
      <p>{children}</p>
    </div>
  );
}
