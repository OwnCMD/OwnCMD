"use client";
import { useState, useEffect, useRef, useId } from "react";
import { api } from "../lib/api";
import { RemoteSurface } from "./RemoteSurface";
import { activitySteps } from "../lib/activity.mjs";
import { Icon, IconButton, Modal, CodeViewer } from "./UI";
export function Approval({ approval, onCommand, onControl, busy, id }) {
  const fields = approval?.fields || approval?.prefill || [];
  const [answer, setAnswer] = useState(""),
    [values, setValues] = useState(() =>
      Object.fromEntries(fields.map((f) => [f.key, f.value || ""])),
    ),
    [revealed, setRevealed] = useState({});
  const inputId = useId();
  if (!approval) return null;
  const args = approval.arguments || {},
    ask = approval.name === "ask_user";
  const inputType = (f) =>
    ({ secret: "password", phone: "tel", otp: "text", textarea: "text" })[
      f.type
    ] || (["email", "date", "number"].includes(f.type) ? f.type : "text");
  return (
    <section className="approval" id={id} tabIndex={-1}>
      <div className="approval-heading">
        <Icon name="shield" />
        <strong>
          {ask ? "Your input is needed" : "Review before continuing"}
        </strong>
      </div>
      <p>
        {args.question ||
          args.confirmation_reason ||
          "Please confirm this action."}
      </p>
      {ask ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (busy) return;
            onCommand(
              "answer",
              fields.length
                ? {
                    field_values: values,
                    text: answer,
                    approval_id: approval.id,
                  }
                : { text: answer, approval_id: approval.id },
            );
          }}
        >
          {fields.some((f) => f.prefilled || f.value) && (
            <p className="prefill-note">
              <Icon name="check" size={14} />
              <span>
                Prefilled from your personal details. Review and change anything
                before continuing.
              </span>
            </p>
          )}
          {fields.length ? (
            <div className="prefill-fields">
              {fields.map((f) => {
                const id = inputId + "-" + f.key,
                  secret = f.type === "secret" || f.sensitive;
                const props = {
                  id,
                  name: f.key,
                  value: values[f.key] || "",
                  required: f.required !== false,
                  disabled: busy,
                  autoComplete: f.type === "otp" ? "one-time-code" : "off",
                  onChange: (e) =>
                    setValues((v) => ({ ...v, [f.key]: e.target.value })),
                };
                return (
                  <div className="prefill-field" key={f.key}>
                    <label htmlFor={id}>
                      {f.label}
                      {f.required === false ? " (optional)" : ""}
                    </label>
                    <div className={secret ? "secret-answer" : ""}>
                      {f.type === "textarea" ? (
                        <textarea {...props} />
                      ) : (
                        <input
                          {...props}
                          type={
                            secret
                              ? revealed[f.key]
                                ? "text"
                                : "password"
                              : inputType(f)
                          }
                          spellCheck={secret ? false : undefined}
                        />
                      )}
                      {secret && (
                        <button
                          type="button"
                          className="button small"
                          disabled={busy}
                          aria-label={
                            (revealed[f.key] ? "Hide " : "Show ") + f.label
                          }
                          aria-pressed={!!revealed[f.key]}
                          onClick={() =>
                            setRevealed((v) => ({ ...v, [f.key]: !v[f.key] }))
                          }
                        >
                          {revealed[f.key] ? "Hide" : "Show"}
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}
              <label className="additional-answer">
                Additional details (optional)
                <textarea
                  aria-label="Additional answer details"
                  value={answer}
                  disabled={busy}
                  onChange={(e) => setAnswer(e.target.value)}
                />
              </label>
            </div>
          ) : (
            <>
              <label className="sr-only" htmlFor={inputId}>
                Your answer
              </label>
              {!args.input_type || args.input_type === "text" ? (
                <textarea
                  id={inputId}
                  value={answer}
                  disabled={busy}
                  onChange={(e) => setAnswer(e.target.value)}
                  required
                  placeholder="Your answer…"
                />
              ) : (
                <input
                  id={inputId}
                  type={args.input_type === "secret" ? "password" : "text"}
                  autoComplete={
                    args.input_type === "otp" ? "one-time-code" : "off"
                  }
                  value={answer}
                  disabled={busy}
                  onChange={(e) => setAnswer(e.target.value)}
                  required
                  placeholder="Your answer…"
                />
              )}
            </>
          )}
          <div className="inline-actions">
            <button className="button primary" disabled={busy}>
              Continue
            </button>
            {args.browser_takeover && (
              <button
                type="button"
                className="button"
                disabled={busy}
                onClick={() => onControl("human")}
              >
                Take browser control
              </button>
            )}
          </div>
        </form>
      ) : (
        <div className="inline-actions">
          <button
            className="button primary"
            disabled={busy}
            onClick={() => onCommand("approve")}
          >
            Approve action
          </button>
          <button
            className="button"
            disabled={busy}
            onClick={() => onCommand("deny")}
          >
            Decline
          </button>
        </div>
      )}
    </section>
  );
}
export function Activity({ task, expanded }) {
  const events = activitySteps(task.events || []);
  const [open, setOpen] = useState(
    expanded || ["queued", "running", "approval"].includes(task.status),
  );
  const active = ["queued", "running", "approval"].includes(task.status);
  const turnKey =
    [...(task.events || [])].reverse().find((e) => e.kind === "followup")?.id ||
    0;
  const previousRun = useRef({ active: false, turn: turnKey });
  useEffect(() => {
    if (
      active &&
      (!previousRun.current.active || previousRun.current.turn !== turnKey)
    )
      setOpen(true);
    previousRun.current = { active, turn: turnKey };
  }, [active, turnKey]);
  const latest = events.at(-1),
    done = task.status === "completed",
    current = ["queued", "running", "approval"].includes(task.status)
      ? [...events].reverse().find((event) => event.status === "running")
      : null;
  const label = done
    ? "Work completed"
    : task.status === "approval"
      ? "Waiting for you"
      : task.status === "paused"
        ? "Work paused"
        : task.status === "cancelled"
          ? "Work stopped"
          : task.status === "failed"
            ? "Needs attention"
            : "Working on your request";
  return (
    <details
      className="activity"
      open={open}
      onToggle={(e) => setOpen(e.currentTarget.open)}
    >
      <summary>
        <span className={"activity-mark " + (done ? "done" : "")}>
          <Icon name={done ? "check" : "work"} size={17} />
        </span>
        <span>
          <strong>{label}</strong>
          <small>
            {current
              ? "Current: " +
                (current.body?.summary ||
                  current.body?.text ||
                  current.body?.name?.replaceAll("_", " ") ||
                  "Working")
              : `${events.filter((event) => event.kind !== "thinking").length || task.steps || 0} activities · $${Number(task.cost || 0).toFixed(3)}`}
          </small>
        </span>
        <Icon name="chevron" size={16} />
      </summary>
      <div className="timeline">
        {events.length ? (
          events.slice(-50).map((e) => (
            <div
              key={e.id}
              className={`timeline-item ${e.status} ${e === current ? "current" : ""}`}
              aria-current={e === current ? "step" : undefined}
            >
              <span className="timeline-dot">
                {e.status === "completed" ? (
                  <Icon name="check" size={12} />
                ) : e.status === "failed" ? (
                  "!"
                ) : (
                  <span className="timeline-pulse" />
                )}
              </span>
              <div>
                <div className="timeline-title">
                  <strong>
                    {e.body?.summary ||
                      e.body?.question ||
                      e.body?.text ||
                      e.body?.name?.replaceAll("_", " ") ||
                      e.kind.replaceAll("_", " ")}
                  </strong>
                  <span className="timeline-status">
                    {e.status === "running"
                      ? "Current"
                      : e.status === "failed"
                        ? "Needs attention"
                        : "Completed"}
                  </span>
                </div>
                {e.body?.error && <small>{e.body.error}</small>}
              </div>
              <time>
                {new Date(e.created * 1000).toLocaleTimeString([], {
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </time>
            </div>
          ))
        ) : (
          <p className="muted">Preparing the first action…</p>
        )}
      </div>
    </details>
  );
}
export function BrowserPanel({
  task,
  onControl,
  onCommand,
  busy,
  notify,
  onClose,
  onRequestInput,
}) {
  const [full, setFull] = useState(false),
    [url, setURL] = useState(""),
    [status, setStatus] = useState("Browser is starting…"),
    [payment, setPayment] = useState(null),
    [sending, setSending] = useState(false),
    [stopped, setStopped] = useState(false);
  const remote = useRef(),
    editing = useRef(false);
  const human = task.control === "human";
  const request = (kind, args = {}, approval_token) =>
    api(`tasks/${task.id}/browser`, { kind, args, approval_token });
  const agentWorking =
    ["queued", "running"].includes(task.status) && task.control !== "human";
  const pendingRequest = task.status === "approval" ? task.approval : null;
  const needsDetails = pendingRequest?.name === "ask_user";
  async function hidePreview(openRequest = false) {
    try {
      const pending = await remote.current?.drain();
      if (pending?.approval_required) return;
    } catch (e) {
      notify(e.message);
    }
    if (openRequest) onRequestInput();
    else onClose();
  }
  async function stopBrowser() {
    setSending(true);
    try {
      await remote.current?.drain();
      const result = await api(`tasks/${task.id}/browser-stop`, {});
      if (result.session_warning) notify(result.session_warning);
      setStopped(true);
      setStatus("Browser stopped · runtime stopped");
    } catch (e) {
      notify(e.message);
    } finally {
      setSending(false);
    }
  }
  async function startBrowser() {
    setSending(true);
    setStatus("Browser is starting…");
    setStopped(false);
    try {
      if (!human) await onControl("human");
      const result = await request("start");
      if (result.url) setURL(result.url === "about:blank" ? "" : result.url);
      setStopped(false);
      setStatus("Browser is starting…");
    } catch (e) {
      setStopped(true);
      setStatus("Browser could not start");
      notify(e.message);
    } finally {
      setSending(false);
    }
  }
  useEffect(() => {
    // Agent progress may explicitly allocate a new browser after an idle stop.
    if (agentWorking) setStopped(false);
  }, [agentWorking, task.updated]);
  async function action(kind, args = {}, token) {
    setSending(true);
    try {
      return await remote.current?.run(kind, args, token);
    } catch (e) {
      notify(e.message);
    } finally {
      setSending(false);
    }
  }
  useEffect(() => {
    const esc = (e) => {
      if (e.key === "Escape" && !e.defaultPrevented) setFull(false);
    };
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, []);
  async function ownership() {
    setSending(true);
    try {
      if (human) await remote.current?.drain();
      await onControl(human ? "ai" : "human");
    } catch (e) {
      notify(e.message);
    } finally {
      setSending(false);
    }
  }
  return (
    <aside
      className={"computer direct-browser " + (full ? "fullscreen" : "")}
      aria-label="OwnCMD Computer"
    >
      <div className="computer-heading">
        <div>
          <Icon name="browser" />
          <strong>OwnCMD Computer</strong>
        </div>
        <div>
          <IconButton
            name="expand"
            label={full ? "Exit full screen" : "Full screen"}
            onClick={() => setFull(!full)}
          />
          <IconButton
            name="close"
            label="Hide preview"
            onClick={() => hidePreview()}
          />
        </div>
      </div>
      <div className="computer-ownership">
        <span>
          <i className={status === "Live view" ? "live-dot" : "offline-dot"} />
          {task.control === "taking_over"
            ? "Finishing current action…"
            : human
              ? "You have control"
              : "OwnCMD has control"}
        </span>
        <button
          className="button small"
          disabled={busy || sending || task.control === "taking_over"}
          onClick={ownership}
        >
          {human ? "Return to OwnCMD" : "Take control"}
        </button>
      </div>
      {pendingRequest && (
        <div
          className="browser-request-notice"
          role="status"
          aria-live="polite"
        >
          <strong>
            {needsDetails ? "Your input is needed" : "Your review is needed"}
          </strong>
          <p>
            {pendingRequest.arguments?.question ||
              pendingRequest.arguments?.confirmation_reason ||
              "OwnCMD is waiting for your response before continuing."}
          </p>
          <button
            className="button primary small"
            onClick={() => hidePreview(true)}
          >
            {needsDetails ? "Enter details in chat" : "Review request in chat"}
          </button>
          <small>
            {stopped
              ? "Browser stopped. You can still respond in chat."
              : "Hiding this preview keeps the browser open. Idle limit while waiting: 15 minutes."}
          </small>
        </div>
      )}
      <div className="address-bar">
        <IconButton
          name="chevron"
          label="Browser back"
          style={{ transform: "rotate(180deg)" }}
          disabled={!human || sending}
          onClick={() => action("back")}
        />
        <IconButton
          name="chevron"
          label="Browser forward"
          disabled={!human || sending}
          onClick={() => action("forward")}
        />
        <IconButton
          name="refresh"
          label="Reload page"
          disabled={!human || sending}
          onClick={() => action("reload")}
        />
        <form
          onSubmit={(e) => {
            e.preventDefault();
            action("navigate", { url });
          }}
        >
          <input
            aria-label="Browser address"
            value={url}
            onChange={(e) => setURL(e.target.value)}
            onFocus={() => {
              editing.current = true;
            }}
            onBlur={() => {
              editing.current = false;
            }}
            readOnly={!human}
            placeholder="Waiting for a page…"
          />
          <button aria-label="Go to address" disabled={!human || sending}>
            <Icon name="arrow" size={15} />
          </button>
        </form>
      </div>
      <RemoteSurface
        ref={remote}
        taskId={task.id}
        frameURL={`/api/tasks/${task.id}/browser-frame`}
        request={request}
        resizeRequest={(args) => request("resize", args)}
        enabled={human && !payment && !stopped}
        active={!stopped}
        starting={agentWorking || sending || task.busy}
        label="Interactive remote browser"
        imageLabel="Live remote browser"
        onURL={(u) => {
          if (!editing.current) setURL(u);
        }}
        onStatus={(value) => {
          setStatus(value);
          if (value.includes("stopped")) setStopped(true);
        }}
        notify={notify}
        onApproval={(r, kind, args) =>
          setPayment({
            ...r,
            kind,
            args: r.pending_events ? { events: r.pending_events } : args,
          })
        }
      />
      <div className="computer-foot">
        <span aria-live="polite">{status}</span>
        {!stopped && (
          <button
            className="button small"
            disabled={sending || busy || agentWorking}
            onClick={stopBrowser}
            title="Stop the browser"
          >
            Stop browser
          </button>
        )}
        {stopped ? (
          <button
            className="button small"
            disabled={sending || busy}
            onClick={startBrowser}
          >
            Start browser
          </button>
        ) : human ? (
          <button
            className="button small"
            onClick={() => remote.current?.focusKeyboard()}
          >
            Show keyboard
          </button>
        ) : (
          <span>
            {pendingRequest
              ? "Waiting for your response"
              : "Sign-ins saved · idle stop after 15 min"}
          </span>
        )}
      </div>
      {human && (
        <p className="remote-help">
          Click and type directly · Swipe or scroll to move · Paste supported ·
          Alt + Esc releases focus
        </p>
      )}
      {payment && (
        <Modal title="Review payment" onClose={() => setPayment(null)}>
          <p className="modal-copy">{payment.confirmation_reason}</p>
          <div className="modal-actions">
            <button className="button" onClick={() => setPayment(null)}>
              Cancel
            </button>
            <button
              className="button primary"
              disabled={sending}
              onClick={async () => {
                const p = payment;
                setPayment(null);
                await new Promise((r) => setTimeout(r, 0));
                await action(p.kind, p.args, p.approval_token);
              }}
            >
              Approve this payment
            </button>
          </div>
        </Modal>
      )}
    </aside>
  );
}
export function Files({ task, notify }) {
  const [files, setFiles] = useState([]),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(false),
    [selected, setSelected] = useState(null),
    [preview, setPreview] = useState(null);
  const sequence = useRef(0),
    viewSequence = useRef(0);
  const revision = [...(task.events || [])]
    .reverse()
    .find(
      (e) =>
        ["tool_started", "tool_finished"].includes(e.kind) &&
        [
          "write_file",
          "read_file",
          "list_files",
          "preview",
          "run_code",
        ].includes(e.body?.name),
    )?.id;
  async function load() {
    const seq = ++sequence.current;
    setLoading(true);
    try {
      const data = await api("tasks/" + task.id + "/files");
      if (seq === sequence.current) {
        setFiles(data.files || []);
        setError("");
      }
    } catch (e) {
      if (seq === sequence.current) setError(e.message);
    } finally {
      if (seq === sequence.current) setLoading(false);
    }
  }
  useEffect(() => {
    load();
    return () => {
      sequence.current++;
      viewSequence.current++;
    };
  }, [task.id, revision]);
  async function view(path) {
    const seq = ++viewSequence.current;
    setSelected(path);
    setPreview(null);
    try {
      const data = await api(
        "tasks/" + task.id + "/file?path=" + encodeURIComponent(path),
      );
      if (seq === viewSequence.current) setPreview(data);
    } catch (e) {
      if (seq === viewSequence.current) setPreview({ error: e.message });
    }
  }
  function close() {
    viewSequence.current++;
    setSelected(null);
    setPreview(null);
  }
  return (
    <section className="files">
      <div className="section-heading">
        <h3>
          <Icon name="file" />
          Workspace files <span>{files.length}</span>
        </h3>
        <IconButton
          name="refresh"
          label="Refresh files"
          onClick={load}
          disabled={loading}
        />
      </div>
      {error ? (
        <p role="alert">{error}</p>
      ) : files.length ? (
        <div className="file-grid">
          {files.map((path) => (
            <button key={path} onClick={() => view(path)}>
              <Icon name="file" />
              <span>{path}</span>
              <Icon name="chevron" size={14} />
            </button>
          ))}
        </div>
      ) : (
        <p className="muted">
          {loading
            ? "Loading files…"
            : "Files created during this task will appear here."}
        </p>
      )}
      {selected && (
        <Modal title={selected} wide onClose={close}>
          <div className="file-meta">
            <span>
              {preview?.language || "File"} · Read only
              {preview?.truncated ? " · Preview truncated at 50 KB" : ""}
            </span>
            <a
              className="button small"
              href={
                "/api/tasks/" +
                task.id +
                "/download?path=" +
                encodeURIComponent(selected)
              }
              download
            >
              <Icon name="down" size={15} />
              Download
            </a>
          </div>
          <div className="file-preview">
            {!preview ? (
              <p>Loading preview…</p>
            ) : preview.error ? (
              <p role="alert">Preview unavailable: {preview.error}</p>
            ) : (
              <CodeViewer
                html={preview.html}
                content={preview.content}
                language={preview.language}
                truncated={preview.truncated}
              />
            )}
          </div>
        </Modal>
      )}
    </section>
  );
}
