"use client";
import { useEffect, useState, useRef } from "react";
import { api } from "../lib/api";
import { Icon, Modal } from "./UI";
import { Editor } from "./Editor";
import { FileExplorer } from "./FileExplorer";
import { WorkspaceTerminal } from "./Terminal";
const duration = (n) => {
  n = Math.max(0, Math.floor(n || 0));
  return `${Math.floor(n / 3600)}h ${Math.floor((n % 3600) / 60)}m ${n % 60}s`;
};
export function Development({
  task,
  onClose,
  onPause,
  notify,
  onPreview,
  onStopped,
}) {
  const [tab, setTab] = useState("files"),
    [files, setFiles] = useState([]),
    [filter, setFilter] = useState(""),
    [path, setPath] = useState(""),
    [preview, setPreview] = useState(null),
    [content, setContent] = useState(""),
    [edit, setEdit] = useState(false),
    [dirty, setDirty] = useState(false),
    [busy, setBusy] = useState(false),
    [services, setServices] = useState([]),
    [serverName, setServerName] = useState("app"),
    [serverCommand, setServerCommand] = useState(
      "npm run dev -- --host 127.0.0.1",
    ),
    [port, setPort] = useState(3000),
    [loading, setLoading] = useState(true),
    [fileLoading, setFileLoading] = useState(false),
    [error, setError] = useState(""),
    [fileError, setFileError] = useState(""),
    [status, setStatus] = useState(null),
    [now, setNow] = useState(Date.now());
  const [openFiles, setOpenFiles] = useState([]),
    [explorerWidth, setExplorerWidth] = useState(245),
    editorRef = useRef();
  const revision = useRef(0),
    mounted = useRef(true),
    refreshing = useRef(false);
  const locked =
    ["queued", "running", "approval"].includes(task.status) || task.busy;
  async function refresh() {
    if (refreshing.current) return;
    refreshing.current = true;
    try {
      const [f, s, w] = await Promise.all([
        api(`tasks/${task.id}/files`),
        api(`tasks/${task.id}/workspace`, { op: "services" }),
        api(`tasks/${task.id}/workspace-status`),
      ]);
      if (!mounted.current) return;
      setFiles(f.files || []);
      setServices(s.services || []);
      setStatus(w);
      setError("");
    } catch (e) {
      if (mounted.current) setError(e.message);
    } finally {
      refreshing.current = false;
      if (mounted.current) setLoading(false);
    }
  }
  useEffect(() => {
    mounted.current = true;
    refresh();
    const t = setInterval(refresh, 5000),
      clock = setInterval(() => setNow(Date.now()), 1000);
    return () => {
      mounted.current = false;
      clearInterval(t);
      clearInterval(clock);
      revision.current++;
    };
  }, [task.id]);
  useEffect(() => {
    const warn = (e) => {
      if (dirty) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  async function perform(body) {
    setBusy(true);
    try {
      return await api(`tasks/${task.id}/workspace`, body);
    } catch (e) {
      notify(e.message);
      return null;
    } finally {
      setBusy(false);
    }
  }
  async function view(file) {
    if (busy) {
      notify("Wait for the current save to finish.");
      return;
    }
    if (dirty) {
      notify("Save or discard your edits before opening another file.");
      return;
    }
    const seq = ++revision.current;
    setPath(file);
    setPreview(null);
    setFileLoading(true);
    setFileError("");
    try {
      const result = await api(
        `tasks/${task.id}/file?path=${encodeURIComponent(file)}`,
      );
      if (seq === revision.current) {
        setOpenFiles((old) => (old.includes(file) ? old : [...old, file]));
        setPreview({ ...result, path: file });
        setContent(result.content || "");
        setEdit(false);
      }
    } catch (e) {
      if (seq === revision.current) setFileError(e.message);
    } finally {
      if (seq === revision.current) setFileLoading(false);
    }
  }
  async function save() {
    if (locked || busy || !edit || !path.trim()) return;
    const result = await perform({ op: "save", path, content });
    if (result) {
      setDirty(false);
      setEdit(false);
      setPreview({ ...preview, path, content, html: "" });
      setOpenFiles((old) => (old.includes(path) ? old : [...old, path]));
      refresh();
      notify("File saved");
    }
  }
  function close() {
    if (dirty) {
      notify("Save or discard your edits before closing the workspace.");
      return;
    }
    onClose();
  }
  async function stop() {
    if (dirty) {
      notify("Save or discard your edits before stopping the workspace.");
      setTab("files");
      return;
    }
    setBusy(true);
    try {
      await api(`tasks/${task.id}/workspace-stop`, {});
      setStatus({ status: "stopped", billing_active: false });
      setServices([]);
      onStopped?.();
      notify("Workspace stopped. Saved project files are preserved.");
    } catch (e) {
      notify(e.message);
    } finally {
      setBusy(false);
    }
  }
  function open(port) {
    if (dirty) {
      notify("Save or discard your edits first.");
      return;
    }
    onPreview(
      port,
      task.app_preview?.port === port ? task.app_preview.path || "/" : "/",
    );
  }
  function newFile() {
    revision.current++;
    setFileLoading(false);
    setFileError("");
    setPath("");
    setContent("");
    setPreview({ content: "" });
    setEdit(true);
    setDirty(true);
  }
  function closeFile(file) {
    if (busy) return;
    if (path === file && dirty) {
      notify("Save or discard your edits before closing this file.");
      return;
    }
    const next = openFiles.filter((p) => p !== file);
    setOpenFiles(next);
    if (path === file) {
      revision.current++;
      setFileLoading(false);
      setFileError("");
      setPreview(null);
      setPath("");
      setEdit(false);
      if (next.length) view(next.at(-1));
    }
  }
  const running = services.filter((s) => s.status === "running");
  const tabs = [
    ["files", "Files", "code"],
    ["terminal", "Terminal", "work"],
    ["services", "Services", "play"],
    ["preview", "Live preview", "browser"],
    ["status", "Status", "activity"],
  ];
  return (
    <Modal title="Project workspace" wide onClose={close}>
      <div className="dev-intro">
        <span>
          <i
            className={
              status?.status === "running" ? "live-dot" : "offline-dot"
            }
          />
          {status
            ? status.status === "running"
              ? "Workspace running"
              : "Workspace stopped"
            : "Checking workspace…"}
          <b>·</b>
          {files.length} files
        </span>
        <div className="inline-actions">
          <button
            className="button small"
            disabled={loading}
            onClick={() => {
              setLoading(true);
              refresh();
            }}
          >
            <Icon name="refresh" size={14} />
            Refresh
          </button>
          <a
            className="button small"
            href={`/api/tasks/${task.id}/project.zip`}
            download
          >
            <Icon name="down" size={14} />
            Export project
          </a>
        </div>
      </div>
      {locked && (
        <div className="dev-notice">
          OwnCMD is working. Pause to edit files or interact with the workspace.
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
        <div className="error-card" role="alert">
          {error}
          <button onClick={refresh}>Retry</button>
        </div>
      )}
      <div className="dev-tabs" role="tablist" aria-label="Workspace panels">
        {tabs.map(([id, label, icon], i) => (
          <button
            key={id}
            id={`tab-${id}`}
            role="tab"
            aria-controls={`panel-${id}`}
            aria-selected={tab === id}
            tabIndex={tab === id ? 0 : -1}
            onClick={() => setTab(id)}
            onKeyDown={(e) => {
              if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) {
                e.preventDefault();
                const next =
                  e.key === "Home"
                    ? 0
                    : e.key === "End"
                      ? tabs.length - 1
                      : (i + (e.key === "ArrowRight" ? 1 : -1) + tabs.length) %
                        tabs.length;
                setTab(tabs[next][0]);
                document.getElementById(`tab-${tabs[next][0]}`)?.focus();
              }
            }}
          >
            <Icon name={icon} size={15} />
            {label}
            {id === "files" && dirty && <i className="unsaved-dot" />}
          </button>
        ))}
      </div>
      <div id={`panel-${tab}`} role="tabpanel" aria-labelledby={`tab-${tab}`}>
        {tab === "files" && (
          <div
            className="dev-files ide-workspace"
            style={{ "--explorer-width": `${explorerWidth}px` }}
          >
            <FileExplorer
              files={files}
              path={path}
              filter={filter}
              onFilter={setFilter}
              onOpen={view}
              loading={loading}
              error={error}
              onNew={newFile}
              newDisabled={locked || busy || dirty}
            />
            <div
              className="explorer-resizer"
              role="separator"
              aria-label="Resize file explorer"
              aria-orientation="vertical"
              aria-valuemin={160}
              aria-valuemax={480}
              aria-valuenow={explorerWidth}
              tabIndex={0}
              onKeyDown={(e) => {
                if (["ArrowLeft", "ArrowRight"].includes(e.key)) {
                  e.preventDefault();
                  setExplorerWidth((w) =>
                    Math.max(
                      160,
                      Math.min(480, w + (e.key === "ArrowRight" ? 20 : -20)),
                    ),
                  );
                }
              }}
              onPointerDown={(e) => {
                e.currentTarget.setPointerCapture(e.pointerId);
                e.preventDefault();
              }}
              onPointerMove={(e) => {
                if (e.currentTarget.hasPointerCapture(e.pointerId)) {
                  const box =
                    e.currentTarget.parentElement.getBoundingClientRect();
                  setExplorerWidth(
                    Math.max(
                      160,
                      Math.min(480, box.width * 0.5, e.clientX - box.left),
                    ),
                  );
                }
              }}
              onPointerUp={(e) =>
                e.currentTarget.releasePointerCapture(e.pointerId)
              }
            />
            <section>
              <div className="file-tabs" role="tablist" aria-label="Open files">
                {openFiles.map((file) => (
                  <div key={file} className={path === file ? "active" : ""}>
                    <button
                      role="tab"
                      aria-selected={path === file}
                      title={file}
                      onClick={() => view(file)}
                    >
                      <Icon name="file" size={14} />
                      <span>{file.split("/").at(-1)}</span>
                      {path === file && dirty && <i className="unsaved-dot" />}
                    </button>
                    <button
                      aria-label={`Close ${file}`}
                      title="Close file"
                      onClick={() => closeFile(file)}
                    >
                      <Icon name="close" size={12} />
                    </button>
                  </div>
                ))}
                {preview && !preview.path && (
                  <div className="active">
                    <span className="untitled-tab">
                      Untitled
                      <i className="unsaved-dot" />
                    </span>
                  </div>
                )}
                {!openFiles.length && !preview && (
                  <span className="empty-tabs">
                    Select a file to get started
                  </span>
                )}
              </div>
              {path && (
                <div className="file-breadcrumbs" aria-label="File location">
                  {path.split("/").map((part, i, parts) => (
                    <span key={i}>
                      {i > 0 && <Icon name="chevron" size={12} />}
                      <Icon
                        name={i === parts.length - 1 ? "file" : "folder"}
                        size={13}
                      />
                      {part}
                    </span>
                  ))}
                </div>
              )}
              {fileLoading ? (
                <div className="dev-empty" role="status">
                  <Icon name="file" size={28} />
                  <h3>Opening {path}…</h3>
                  <p>Loading file contents.</p>
                </div>
              ) : fileError ? (
                <div className="dev-empty">
                  <p role="alert">{fileError}</p>
                  <a
                    className="button"
                    href={`/api/tasks/${task.id}/download?path=${encodeURIComponent(path)}`}
                    download
                  >
                    Download file
                  </a>
                  <button className="button" onClick={() => view(path)}>
                    Retry
                  </button>
                </div>
              ) : preview ? (
                <>
                  <div className="dev-file-bar">
                    {edit ? (
                      <input
                        aria-label="File path"
                        value={path}
                        onChange={(e) => {
                          setPath(e.target.value);
                          setDirty(true);
                        }}
                        placeholder="src/App.jsx"
                      />
                    ) : (
                      <strong title={path}>{path}</strong>
                    )}
                    <div>
                      {dirty && <span className="file-dirty">Unsaved</span>}
                      {path && (
                        <a
                          className="button small"
                          href={`/api/tasks/${task.id}/download?path=${encodeURIComponent(path)}`}
                          download
                          aria-label="Download file"
                        >
                          <Icon name="down" size={14} />
                        </a>
                      )}
                      {edit ? (
                        <>
                          <button
                            className="button small"
                            disabled={busy}
                            onClick={() => {
                              setContent(preview.content || "");
                              if (preview.path != null) setPath(preview.path);
                              setDirty(false);
                              setEdit(false);
                            }}
                          >
                            Discard
                          </button>
                          <button
                            className="button primary small"
                            disabled={locked || busy || !path.trim()}
                            onClick={save}
                          >
                            {busy ? "Saving…" : "Save file"}
                          </button>
                        </>
                      ) : (
                        <button
                          className="button small"
                          disabled={locked || preview.truncated}
                          onClick={() => editorRef.current?.beginEdit()}
                        >
                          Edit file
                        </button>
                      )}
                    </div>
                  </div>
                  {preview.truncated && (
                    <p className="dev-notice">
                      Large file preview is truncated. Download it to see the
                      full file.
                    </p>
                  )}
                  <Editor
                    ref={editorRef}
                    key={preview.path || "editor"}
                    path={path}
                    truncated={!!preview.truncated}
                    onEdit={(value) => {
                      setContent(value);
                      setDirty(value !== (preview.content || ""));
                      setEdit(true);
                    }}
                    value={content}
                    readOnly={!edit || locked || busy}
                    onChange={(value) => {
                      setContent(value);
                      if (edit) setDirty(value !== (preview.content || ""));
                    }}
                    onSave={save}
                  />
                </>
              ) : (
                <div className="dev-empty">
                  <Icon name="code" size={36} />
                  <h3>Your project, ready to explore</h3>
                  <p>
                    Choose a file to view its source. Edit with syntax
                    highlighting, search, line numbers and keyboard shortcuts.
                  </p>
                </div>
              )}
            </section>
          </div>
        )}
        {tab === "terminal" && (
          <WorkspaceTerminal
            task={task}
            locked={locked}
            onRefresh={refresh}
            notify={notify}
          />
        )}
        {tab === "services" && (
          <div className="dev-services">
            <div className="workspace-section-heading">
              <h3>App services</h3>
              <p>
                Start your app, API or database. View logs and open a preview
                from each running service.
              </p>
            </div>
            <form
              onSubmit={async (e) => {
                e.preventDefault();
                const r = await perform({
                  op: "service",
                  action: "start",
                  name: serverName,
                  command: serverCommand,
                  port: Number(port),
                });
                if (r) {
                  setServices(r.services || []);
                  refresh();
                }
              }}
            >
              <label>
                Name
                <input
                  aria-label="Service name"
                  value={serverName}
                  onChange={(e) => setServerName(e.target.value)}
                  required
                />
              </label>
              <label>
                Port
                <input
                  type="number"
                  min="1024"
                  max="65535"
                  aria-label="Service port"
                  value={port}
                  onChange={(e) => setPort(e.target.value)}
                  required
                />
              </label>
              <label className="dev-service-command">
                Start command
                <input
                  aria-label="Service command"
                  value={serverCommand}
                  onChange={(e) => setServerCommand(e.target.value)}
                  required
                />
              </label>
              <button className="button primary" disabled={locked || busy}>
                Start service
              </button>
            </form>
            <p>
              Common database ports: MongoDB 27017 · PostgreSQL 5432 · Redis
              6379
            </p>
            {loading ? (
              <p role="status">Loading services…</p>
            ) : services.length ? (
              services.map((s) => (
                <div className="dev-service" key={s.name}>
                  <div>
                    <strong>{s.name}</strong>
                    <span>
                      {s.status} · port {s.port}
                    </span>
                    <div>
                      <button
                        className="button small"
                        disabled={locked || busy || s.status !== "running"}
                        onClick={() => open(s.port)}
                      >
                        Preview
                      </button>
                      <button
                        className="button small"
                        disabled={locked || busy || s.status !== "running"}
                        onClick={async () => {
                          const r = await perform({
                            op: "service",
                            action: "stop",
                            name: s.name,
                          });
                          if (r) {
                            setServices(r.services || []);
                            refresh();
                            onStopped?.(false);
                          }
                        }}
                      >
                        Stop
                      </button>
                    </div>
                  </div>
                  <code>{s.command}</code>
                  <pre>{s.output || "Waiting for output…"}</pre>
                </div>
              ))
            ) : (
              <div className="dev-empty">
                <Icon name="play" size={28} />
                <h3>No running services</h3>
                <p>
                  Use the form above to start your app. Saved project files are
                  restored automatically.
                </p>
              </div>
            )}
          </div>
        )}
        {tab === "preview" && (
          <div className="dev-empty">
            <Icon name="browser" size={36} />
            <h3>
              {running.length
                ? "Your app is ready to try"
                : "Start your app to preview it"}
            </h3>
            <p>
              Interact with your app in the side preview. Click, type, paste and
              scroll directly.
            </p>
            {running.map((s) => (
              <button
                className="button primary"
                disabled={locked}
                key={s.name}
                onClick={() => open(s.port)}
              >
                {s.name} · Open preview
              </button>
            ))}
            <button className="button" onClick={() => setTab("services")}>
              Open services
            </button>
          </div>
        )}
        {tab === "status" && (
          <div className="workspace-status">
            <div className="workspace-section-heading">
              <h3>Workspace health</h3>
              <p>Control your runtime and keep track of your resources.</p>
            </div>
            <div className="workspace-metrics">
              <article>
                <span>Current status</span>
                <strong>{status?.status || "Checking…"}</strong>
                <small>
                  {locked
                    ? "OwnCMD is working"
                    : status?.status === "running"
                      ? "Ready for you"
                      : "Saved files are available"}
                </small>
              </article>
              <article>
                <span>Uptime</span>
                <strong>
                  {status?.status === "running"
                    ? duration(
                        status.started_at
                          ? now / 1000 - status.started_at
                          : status.uptime_seconds,
                      )
                    : "—"}
                </strong>
                <small>Current workspace session</small>
              </article>
              <article>
                <span>Running services</span>
                <strong>{running.length}</strong>
                <small>{files.length} project files</small>
              </article>
              <article>
                <span>Workspace rate</span>
                <strong>
                  {status
                    ? `$${Number(status.hourly_rate || 0).toFixed(2)}/hr`
                    : "—"}
                </strong>
                <small>
                  {status?.billing_active
                    ? "Meter is running"
                    : "Meter is stopped"}
                </small>
              </article>
            </div>
            <div className="workspace-stop-card">
              <div>
                <h3>Stop workspace</h3>
                <p>
                  Stops services and active terminal sessions. Source files and
                  database exports are saved for your next session.
                </p>
              </div>
              <button
                className="button danger"
                disabled={locked || busy || status?.status !== "running"}
                onClick={stop}
              >
                {busy ? "Stopping…" : "Stop workspace"}
              </button>
            </div>
            <div className="workspace-info-grid">
              <div>
                <strong>Automatic idle stop</strong>
                <p>
                  After 15 minutes without use. Services may stop sooner when
                  capacity is needed.
                </p>
              </div>
              <div>
                <strong>Your work is saved</strong>
                <p>
                  Export your project at any time. Dependencies can be
                  reinstalled from your saved manifests.
                </p>
              </div>
            </div>
          </div>
        )}
      </div>
      <div className="dev-footer">
        <span>
          {dirty
            ? "You have unsaved changes."
            : "Source files and database exports are checkpointed."}{" "}
          Closing this panel keeps running services active.
        </span>
        {tab !== "status" && (
          <button className="button small" onClick={() => setTab("status")}>
            Manage workspace
          </button>
        )}
      </div>
    </Modal>
  );
}
