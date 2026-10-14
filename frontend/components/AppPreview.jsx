"use client";
import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { Icon, IconButton } from "./UI";
import { RemoteSurface } from "./RemoteSurface";
import { clientDisplay } from "../lib/browser-display.mjs";
export function AppPreview({
  task,
  port,
  path = "/",
  onClose,
  onPause,
  notify,
}) {
  const [address, setAddress] = useState(path),
    [status, setStatus] = useState("Connecting…"),
    [error, setError] = useState(""),
    [ready, setReady] = useState(false),
    [full, setFull] = useState(false);
  const remote = useRef(),
    opened = useRef(""),
    alive = useRef(true),
    editing = useRef(false);
  const locked =
    ["queued", "running", "approval"].includes(task.status) || task.busy;
  const request = (kind, args = {}) =>
    api(`tasks/${task.id}/workspace`, { op: "preview", kind, args });
  async function open(next = address) {
    if (locked) return;
    setError("");
    setReady(false);
    setStatus("Opening app…");
    try {
      await request("open", {
        port,
        path: next,
        display: remote.current?.display() || clientDisplay(),
      });
      if (alive.current) {
        setReady(true);
        remote.current?.refresh();
      }
    } catch (e) {
      opened.current = "";
      if (alive.current) setError(e.message);
    }
  }
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  useEffect(() => {
    const key = `${task.id}:${port}:${path}`;
    if (!locked && opened.current !== key) {
      opened.current = key;
      setAddress(path);
      open(path);
    }
  }, [task.id, port, path, locked]);
  async function action(kind) {
    try {
      await remote.current?.run(kind);
    } catch (e) {
      setError(e.message);
    }
  }
  return (
    <aside
      className={"app-preview-panel " + (full ? "fullscreen" : "")}
      aria-label="App preview"
    >
      <header>
        <div>
          <Icon name="browser" />
          <strong>App preview</strong>
          <span className="preview-live-status">{status}</span>
        </div>
        <div>
          <IconButton
            name="expand"
            label={full ? "Exit full screen preview" : "Expand preview"}
            onClick={() => setFull(!full)}
          />
          <IconButton
            name="close"
            label="Close app preview"
            onClick={onClose}
          />
        </div>
      </header>
      <div className="preview-address">
        <IconButton
          name="chevron"
          label="App back"
          style={{ transform: "rotate(180deg)" }}
          disabled={locked || !ready}
          onClick={() => action("back")}
        />
        <IconButton
          name="refresh"
          label="Reload app preview"
          disabled={locked}
          onClick={() => (ready ? action("reload") : open())}
        />
        <IconButton
          name="chevron"
          label="App forward"
          disabled={locked || !ready}
          onClick={() => action("forward")}
        />
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            try {
              await remote.current?.drain();
              await open();
            } catch (e) {
              setError(e.message);
            }
          }}
        >
          <span>App · {port}</span>
          <input
            aria-label="App path"
            value={address}
            onFocus={() => {
              editing.current = true;
            }}
            onBlur={() => {
              editing.current = false;
            }}
            onChange={(e) => setAddress(e.target.value)}
            readOnly={locked}
          />
        </form>
      </div>
      {locked && (
        <div className="preview-notice">
          OwnCMD is working. Pause to interact.
          <button
            className="button small"
            disabled={task.status === "approval"}
            onClick={onPause}
          >
            Pause OwnCMD
          </button>
        </div>
      )}
      {error && (
        <div className="preview-error" role="alert">
          {error}
        </div>
      )}
      <RemoteSurface
        ref={remote}
        taskId={task.id}
        frameURL={`/api/tasks/${task.id}/workspace-frame`}
        request={request}
        resizeRequest={(args) => request("resize", args)}
        enabled={!locked && ready}
        drag
        active={ready}
        label="Interactive app preview"
        imageLabel="Live project preview"
        onStatus={setStatus}
        onURL={(url) => {
          if (editing.current) return;
          try {
            const parsed = new URL(url);
            if (["http:", "https:"].includes(parsed.protocol))
              setAddress(parsed.pathname + parsed.search + parsed.hash);
          } catch {}
        }}
        notify={notify}
      />
      <footer>
        <span>Click and type directly · Swipe to scroll</span>
        <button
          className="button small"
          disabled={locked || !ready}
          onClick={() => remote.current?.focusKeyboard()}
        >
          Show keyboard
        </button>
      </footer>
    </aside>
  );
}
