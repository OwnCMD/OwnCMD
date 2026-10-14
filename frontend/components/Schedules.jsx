"use client";
import { randomId } from "../lib/id.mjs";
import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { Icon, Modal } from "./UI";
const fresh = () => {
  const date = new Date(Date.now() + 3600000);
  date.setMinutes(Math.ceil(date.getMinutes() / 5) * 5, 0, 0);
  return {
    name: "",
    prompt: "",
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
    recurrence: "daily",
    local_start: new Date(date.getTime() - date.getTimezoneOffset() * 60000)
      .toISOString()
      .slice(0, 16),
    interval_hours: 24,
    weekdays: [1],
    month_day: 1,
    missed: "latest",
    budget: "",
    max_runs: "",
    end_date: "",
    enabled: true,
    inputs: {},
    consent: false,
    skills: { mode: "auto", pins: [] },
  };
};
const label = (status) =>
  ({
    approval: "Needs your input",
    paused: "Paused",
    failed: "Failed",
    queued: "Queued",
    running: "Running",
    completed: "Completed",
    cancelled: "Stopped",
    skipped: "Skipped",
    deleted: "Conversation deleted",
  })[status] || status;
const recurrenceLabel = (row) => {
  const at = row.local_start?.slice(11, 16) || "";
  if (row.recurrence === "once") return "Once";
  if (row.recurrence === "interval") {
    const days = row.interval_hours / 24;
    return Number.isInteger(days)
      ? `Every ${days} ${days === 1 ? "day" : "days"}`
      : `Every ${row.interval_hours} hours`;
  }
  if (row.recurrence === "weekly")
    return (
      (row.weekdays || [])
        .map((d) => ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][d])
        .join(", ") +
      " at " +
      at
    );
  if (row.recurrence === "monthly")
    return `Monthly on day ${row.month_day} at ${at}`;
  return "Daily at " + at;
};
const format = (ts, tz) =>
  new Date(ts * 1000).toLocaleString(undefined, {
    timeZone: tz,
    dateStyle: "medium",
    timeStyle: "short",
  });
function ScheduleEditor({ initial, onClose, onSaved, notify }) {
  const [draft, setDraft] = useState(() =>
      initial
        ? {
            ...fresh(),
            ...initial,
            budget: initial.budget ?? "",
            max_runs: initial.max_runs ?? "",
            consent: initial.consent === true,
          }
        : fresh(),
    ),
    [step, setStep] = useState(0),
    [check, setCheck] = useState(null),
    [times, setTimes] = useState(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const original = useRef(JSON.stringify(draft));
  const patch = (k, v) => {
    setDraft((d) => ({
      ...d,
      [k]: v,
      ...(k === "prompt" ? { consent: false } : {}),
    }));
    setTimes(null);
  };
  function close() {
    if (
      JSON.stringify(draft) !== original.current &&
      !window.confirm("Discard unsaved schedule changes?")
    )
      return;
    onClose();
  }
  async function next() {
    setBusy(true);
    setError("");
    try {
      if (step === 0) {
        if (draft.prompt.trim().length < 3)
          throw Error("Describe the work you want OwnCMD to do.");
        setStep(1);
      } else if (step === 1) {
        const c = await api("schedules/readiness", {
          prompt: draft.prompt,
          id: draft.id,
        });
        setCheck(c);
        setDraft((d) => ({
          ...d,
          inputs: Object.fromEntries(
            c.fields.map((f) => [f.key, d.inputs[f.key] ?? f.value]),
          ),
        }));
        setStep(2);
      } else if (step === 2) {
        const r = await api("schedules/preview", draft);
        setTimes(r.times);
        setStep(3);
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  async function save() {
    setBusy(true);
    setError("");
    try {
      await api(
        draft.id ? "schedules/" + draft.id : "schedules",
        draft,
        draft.id ? "PUT" : "POST",
      );
      notify(draft.enabled ? "Schedule saved" : "Draft saved");
      onSaved();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      title={draft.id ? "Edit scheduled work" : "Schedule your next win"}
      wide
      onClose={close}
    >
      <div className="schedule-wizard-steps">
        {["Work", "Timing", "Readiness", "Review"].map((s, i) => (
          <span
            key={s}
            className={step === i ? "current" : i < step ? "done" : ""}
          >
            <b>{i < step ? "✓" : i + 1}</b>
            {s}
          </span>
        ))}
      </div>
      {error && (
        <div className="error-card" role="alert">
          {error}
        </div>
      )}
      <fieldset className="schedule-form" disabled={busy}>
        {step === 0 && (
          <>
            <p className="modal-copy">
              Give OwnCMD a clear outcome. Each run creates its own Work
              conversation with results, files and activity.
            </p>
            <label>
              Schedule name
              <input
                aria-label="Schedule name"
                maxLength={100}
                placeholder="My morning research brief"
                value={draft.name}
                onChange={(e) => patch("name", e.target.value)}
              />
            </label>
            <label>
              What should OwnCMD do?
              <textarea
                aria-label="Scheduled work instructions"
                rows={6}
                maxLength={24000}
                value={draft.prompt}
                onChange={(e) => patch("prompt", e.target.value)}
                placeholder="Every morning, research… Include sources, highlight what changed, and save a concise report."
              />
            </label>
            <div className="schedule-templates">
              {[
                [
                  "Research brief",
                  "Research the latest news about my industry. Summarize the important changes with dated sources.",
                ],
                [
                  "Website check",
                  "Visit https://example.com and check for changes. Summarize what you find with evidence.",
                ],
                [
                  "Recurring report",
                  "Create a weekly report on the topic below, including sources and a downloadable summary.",
                ],
              ].map(([name, prompt]) => (
                <button
                  className="button small"
                  key={name}
                  onClick={() => {
                    patch("name", name);
                    patch("prompt", prompt);
                  }}
                >
                  {name}
                </button>
              ))}
            </div>
          </>
        )}
        {step === 1 && (
          <>
            <div className="details-grid">
              <label>
                Repeat
                <select
                  aria-label="Schedule recurrence"
                  value={draft.recurrence}
                  onChange={(e) => patch("recurrence", e.target.value)}
                >
                  {[
                    ["once", "Once"],
                    ["interval", "Every few hours"],
                    ["daily", "Daily"],
                    ["weekly", "Selected weekdays"],
                    ["monthly", "Monthly"],
                  ].map(([k, l]) => (
                    <option key={k} value={k}>
                      {l}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Time zone
                <input
                  aria-label="Schedule time zone"
                  list="schedule-zones"
                  value={draft.timezone}
                  onChange={(e) => patch("timezone", e.target.value)}
                />
                <datalist id="schedule-zones">
                  {[
                    "America/Toronto",
                    "America/New_York",
                    "America/Los_Angeles",
                    "Europe/London",
                    "Europe/Paris",
                    "Asia/Kolkata",
                    "Asia/Dubai",
                    "Asia/Singapore",
                    "Australia/Sydney",
                    "UTC",
                  ].map((z) => (
                    <option key={z}>{z}</option>
                  ))}
                </datalist>
              </label>
              <label>
                {draft.recurrence === "once"
                  ? "Run at"
                  : "Start from (local time)"}
                <input
                  aria-label="Schedule start"
                  type="datetime-local"
                  value={draft.local_start}
                  onChange={(e) => patch("local_start", e.target.value)}
                />
              </label>
              {draft.recurrence === "interval" && (
                <label>
                  Every (hours)
                  <input
                    type="number"
                    min="1"
                    max="8760"
                    step=".5"
                    aria-label="Schedule interval hours"
                    value={draft.interval_hours}
                    onChange={(e) =>
                      patch("interval_hours", Number(e.target.value))
                    }
                  />
                </label>
              )}
              {draft.recurrence === "monthly" && (
                <label>
                  Day of month
                  <input
                    type="number"
                    min="1"
                    max="31"
                    value={draft.month_day}
                    onChange={(e) => patch("month_day", Number(e.target.value))}
                  />
                </label>
              )}
              <label>
                End date (optional)
                <input
                  aria-label="Schedule end date"
                  type="date"
                  value={draft.end_date || ""}
                  onChange={(e) => patch("end_date", e.target.value)}
                />
              </label>
            </div>
            {draft.recurrence === "weekly" && (
              <div
                className="weekday-picker"
                role="group"
                aria-label="Run on weekdays"
              >
                {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map(
                  (day, i) => (
                    <button
                      key={day}
                      aria-pressed={draft.weekdays?.includes(i)}
                      onClick={() =>
                        patch(
                          "weekdays",
                          draft.weekdays?.includes(i)
                            ? draft.weekdays.filter((x) => x !== i)
                            : [...(draft.weekdays || []), i],
                        )
                      }
                    >
                      {day}
                    </button>
                  ),
                )}
              </div>
            )}
            <p className="schedule-hint">
              Calendar runs follow the selected time zone. A missing
              daylight-saving time is skipped; a repeated time runs once.
              Monthly dates beyond a month’s length use its last day.
            </p>
            <details>
              <summary>Run controls</summary>
              <div className="details-grid">
                <label>
                  Provider cost limit per run ($, optional)
                  <input
                    aria-label="Scheduled run cost limit"
                    type="number"
                    min=".01"
                    step=".01"
                    value={draft.budget}
                    onChange={(e) => patch("budget", e.target.value)}
                  />
                </label>
                <label>
                  Maximum runs (optional)
                  <input
                    aria-label="Maximum scheduled runs"
                    type="number"
                    min="1"
                    max="10000"
                    value={draft.max_runs}
                    onChange={(e) => patch("max_runs", e.target.value)}
                  />
                </label>
                <label>
                  If the server misses a run
                  <select
                    aria-label="Missed run policy"
                    value={draft.missed}
                    onChange={(e) => patch("missed", e.target.value)}
                  >
                    <option value="latest">Catch up once when available</option>
                    <option value="skip">
                      Skip if more than 15 minutes late
                    </option>
                  </select>
                </label>
              </div>
              <p className="schedule-hint">
                The cost limit pauses work between actions. An action already in
                progress may exceed it. Runs never overlap; outstanding input,
                paused work or a configured usage limit can delay the next run.
              </p>
            </details>
          </>
        )}
        {step === 2 && check && (
          <>
            <div className="readiness-heading">
              <Icon name="shield" size={28} />
              <div>
                <h3>Set this work up for success</h3>
                <p>Review the details OwnCMD may need while you’re away.</p>
              </div>
            </div>
            <div className="details-grid">
              {check.fields
                .filter((f) => f.source !== "optional" || draft.inputs[f.key])
                .map((f) => (
                  <label key={f.key}>
                    {f.label}
                    {f.required ? " *" : " (optional)"}
                    <small>
                      {f.source === "personal"
                        ? "Prefilled from personal details — editable"
                        : ""}
                    </small>
                    <textarea
                      aria-label={f.label}
                      rows={f.key.startsWith("task_") ? 3 : 2}
                      value={draft.inputs[f.key] || ""}
                      maxLength={1000}
                      onChange={(e) =>
                        setDraft((d) => ({
                          ...d,
                          consent: false,
                          skills: { mode: "auto", pins: [] },
                          inputs: { ...d.inputs, [f.key]: e.target.value },
                        }))
                      }
                    />
                  </label>
                ))}
            </div>
            {check.fields.some(
              (f) => f.source === "optional" && !draft.inputs[f.key],
            ) && (
              <label className="schedule-extra-detail">
                Include another saved detail (optional)
                <select
                  aria-label="Include a saved detail"
                  value=""
                  onChange={(e) => {
                    const f = check.fields.find(
                      (f) => f.key === e.target.value,
                    );
                    if (f)
                      setDraft((d) => ({
                        ...d,
                        consent: false,
                        inputs: { ...d.inputs, [f.key]: f.suggested },
                      }));
                  }}
                >
                  <option value="">Choose only what this task needs…</option>
                  {check.fields
                    .filter(
                      (f) => f.source === "optional" && !draft.inputs[f.key],
                    )
                    .map((f) => (
                      <option key={f.key} value={f.key}>
                        {f.label}
                      </option>
                    ))}
                </select>
              </label>
            )}
            {check.warnings.map((w) => (
              <p className="schedule-warning" key={w}>
                {w}
              </p>
            ))}
            <p className="schedule-hint">{check.note}</p>
            <label className="schedule-consent">
              <input
                type="checkbox"
                checked={draft.consent}
                onChange={(e) => patch("consent", e.target.checked)}
              />
              <span>
                I confirm these details and allow this schedule to use them for
                the stated task. Final consequential actions still require
                approval.
              </span>
            </label>
            <label className="schedule-consent">
              <input
                type="checkbox"
                checked={!draft.enabled}
                onChange={(e) => patch("enabled", !e.target.checked)}
              />
              <span>
                Save as a paused draft. I’ll finish preparing it later.
              </span>
            </label>
          </>
        )}
        {step === 3 && (
          <div className="schedule-review">
            <span className="eyebrow">
              {draft.enabled ? "READY TO SCHEDULE" : "PAUSED DRAFT"}
            </span>
            <h3>{draft.name || draft.prompt.slice(0, 80)}</h3>
            <p>{draft.prompt}</p>
            <dl>
              <div>
                <dt>Timing</dt>
                <dd>
                  {recurrenceLabel(draft)} · {draft.timezone}
                </dd>
              </div>
              <div>
                <dt>Cost limit</dt>
                <dd>
                  {draft.budget
                    ? `$${draft.budget} per run`
                    : "No per-run cost limit"}
                </dd>
              </div>
              <div>
                <dt>Confirmed details</dt>
                <dd>
                  {Object.values(draft.inputs).filter(Boolean).length} · saved
                  only for this schedule
                </dd>
              </div>
            </dl>
            <h4>Upcoming run times</h4>
            <ol>
              {times?.map((t) => (
                <li key={t}>{format(t, draft.timezone)}</li>
              ))}
            </ol>
            <p className="schedule-hint">
              Results and requests for input appear in Scheduled work and the
              run’s conversation. No email or push notifications are sent.
              Deleting or pausing a schedule does not stop a run already in
              progress.
            </p>
          </div>
        )}
      </fieldset>
      <div className="modal-actions schedule-wizard-actions">
        <button
          className="button"
          disabled={busy}
          onClick={step ? () => setStep(step - 1) : close}
        >
          {step ? "Back" : "Cancel"}
        </button>
        {step < 3 ? (
          <button className="button primary" disabled={busy} onClick={next}>
            {busy
              ? "Checking…"
              : step === 1
                ? "Check readiness"
                : step === 2
                  ? "Review schedule"
                  : "Next"}
          </button>
        ) : (
          <button className="button primary" disabled={busy} onClick={save}>
            {busy
              ? "Saving…"
              : draft.enabled
                ? "Activate schedule"
                : "Save draft"}
          </button>
        )}
      </div>
    </Modal>
  );
}
export function Schedules({ notify }) {
  const [rows, setRows] = useState(null),
    [error, setError] = useState(""),
    [edit, setEdit] = useState(undefined),
    [remove, setRemove] = useState(null),
    [filter, setFilter] = useState("all"),
    [query, setQuery] = useState(""),
    [busy, setBusy] = useState("");
  const active = useRef(true),
    loading = useRef(false),
    tokens = useRef({});
  async function load() {
    if (loading.current) return;
    loading.current = true;
    try {
      const r = await api("schedules");
      if (active.current) {
        setRows(r);
        setError("");
      }
    } catch (e) {
      if (active.current) setError(e.message);
    } finally {
      loading.current = false;
    }
  }
  useEffect(() => {
    active.current = true;
    load();
    const t = setInterval(load, 10000);
    return () => {
      active.current = false;
      clearInterval(t);
    };
  }, []);
  const attention = (r) =>
    r.blocked ||
    ["approval", "paused", "failed"].includes(r.history?.[0]?.status);
  async function action(row, name) {
    if (busy) return;
    setBusy(row.id);
    try {
      const token =
        tokens.current[row.id] || (tokens.current[row.id] = randomId());
      const r = await api(`schedules/${row.id}/action`, {
        action: name,
        version: row.version,
        token,
      });
      delete tokens.current[row.id];
      await load();
      notify(
        name === "run"
          ? "Scheduled work started"
          : name === "pause"
            ? "Schedule paused"
            : "Schedule resumed",
      );
      if (r.tasks?.[0]) location.hash = "#chat/" + r.tasks[0];
    } catch (e) {
      notify(e.message);
    } finally {
      setBusy("");
    }
  }
  const visible = (rows || []).filter(
    (r) =>
      (r.name + " " + r.prompt).toLowerCase().includes(query.toLowerCase()) &&
      (filter === "all" ||
        (filter === "active" && r.enabled) ||
        (filter === "paused" && !r.enabled) ||
        (filter === "attention" && attention(r))),
  );
  return (
    <div className="page schedules-page">
      <div className="schedule-page-heading">
        <div className="page-heading">
          <span className="eyebrow">WORK THAT RUNS ON YOUR TIME</span>
          <h1>Scheduled work</h1>
          <p>Set the outcome. Choose the rhythm. Come back to progress.</p>
        </div>
        <button className="button primary" onClick={() => setEdit(null)}>
          <Icon name="plus" size={16} />
          New schedule
        </button>
      </div>
      <div className="schedule-stats">
        <div>
          <span>Active schedules</span>
          <strong>{rows?.filter((r) => r.enabled).length ?? "—"}</strong>
        </div>
        <div>
          <span>Needs attention</span>
          <strong>{rows?.filter(attention).length ?? "—"}</strong>
        </div>
        <div>
          <span>Next scheduled run</span>
          <strong className="schedule-next">
            {rows?.find((r) => r.enabled)
              ? format(
                  rows.find((r) => r.enabled).next,
                  rows.find((r) => r.enabled).timezone,
                )
              : "Your next idea"}
          </strong>
        </div>
      </div>
      <div className="schedule-toolbar">
        <input
          type="search"
          aria-label="Search scheduled work"
          placeholder="Find a schedule…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <select
          aria-label="Schedule status filter"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        >
          {[
            ["all", "All schedules"],
            ["active", "Active"],
            ["paused", "Paused / finished"],
            ["attention", "Needs attention"],
          ].map(([v, l]) => (
            <option key={v} value={v}>
              {l}
            </option>
          ))}
        </select>
        <span>Updates every 10 seconds</span>
      </div>
      {error && (
        <div className="error-card" role="alert">
          {error}
          <button onClick={load}>Retry</button>
        </div>
      )}
      {rows === null ? (
        <p role="status">Loading scheduled work…</p>
      ) : !visible.length ? (
        <div className="schedule-empty">
          <Icon name="clock" size={38} />
          <h2>
            {rows.length
              ? "No matching schedules"
              : "Put repeat work on your calendar"}
          </h2>
          <p>
            Research briefs, website checks and recurring reports—with the
            details prepared ahead of time.
          </p>
          <button className="button" onClick={() => setEdit(null)}>
            Create a schedule
          </button>
        </div>
      ) : (
        <div className="schedule-list">
          {visible.map((row) => (
            <article className="schedule-card" key={row.id}>
              <div className="schedule-card-heading">
                <div>
                  <span
                    className={
                      "schedule-badge " +
                      (attention(row)
                        ? "attention"
                        : row.enabled
                          ? "active"
                          : "paused")
                    }
                  >
                    {attention(row)
                      ? "Needs attention"
                      : row.enabled
                        ? "Active"
                        : row.recurrence === "once" && row.run_count
                          ? "Finished"
                          : "Paused"}
                  </span>
                  <h2>{row.name}</h2>
                </div>
                <Icon name="clock" size={22} />
              </div>
              <p className="schedule-prompt">{row.prompt}</p>
              <div className="schedule-metadata">
                <span>
                  {recurrenceLabel(row)} · {row.timezone}
                </span>
                <span>
                  {row.enabled
                    ? "Next: " + format(row.next, row.timezone)
                    : "Not scheduled to run"}
                </span>
                <span>
                  {row.run_count} {row.run_count === 1 ? "run" : "runs"}
                </span>
              </div>
              {row.blocked && <p className="schedule-warning">{row.blocked}</p>}
              {row.history?.[0] && (
                <div className="schedule-latest">
                  <span>Latest run · {label(row.history[0].status)}</span>
                  {row.history[0].task && (
                    <a href={"#chat/" + row.history[0].task}>
                      {["approval", "paused", "failed"].includes(
                        row.history[0].status,
                      )
                        ? "Review & continue"
                        : "Open results"}{" "}
                      →
                    </a>
                  )}
                </div>
              )}
              <div className="schedule-card-actions">
                <button className="button small" onClick={() => setEdit(row)}>
                  Edit
                </button>
                <button
                  className="button small"
                  disabled={!!busy}
                  onClick={() => action(row, row.enabled ? "pause" : "resume")}
                >
                  {row.enabled ? "Pause schedule" : "Resume schedule"}
                </button>
                <button
                  className="button small"
                  disabled={!!busy || !row.enabled}
                  onClick={() => action(row, "run")}
                >
                  Run now
                </button>
                <button
                  className="button small"
                  onClick={() =>
                    setEdit({
                      ...row,
                      id: undefined,
                      version: undefined,
                      name: row.name + " copy",
                      local_start: fresh().local_start,
                      enabled: false,
                      consent: false,
                      skills: { mode: "auto", pins: [] },
                      history: [],
                    })
                  }
                >
                  Duplicate
                </button>
                <button
                  className="button subtle small"
                  onClick={() => setRemove(row)}
                >
                  Delete
                </button>
              </div>
              {row.history?.length > 0 && (
                <details className="schedule-history">
                  <summary>Run history · latest {row.history.length}</summary>
                  <div>
                    {row.history.map((h) => (
                      <div key={h.id}>
                        <span>{format(h.created, row.timezone)}</span>
                        <strong>{label(h.status)}</strong>
                        {h.task ? (
                          <a href={"#chat/" + h.task}>Open run</a>
                        ) : (
                          <small>{h.reason}</small>
                        )}
                      </div>
                    ))}
                  </div>
                </details>
              )}
            </article>
          ))}
        </div>
      )}
      {edit !== undefined && (
        <ScheduleEditor
          key={edit?.id || "new"}
          initial={edit}
          notify={notify}
          onClose={() => setEdit(undefined)}
          onSaved={() => {
            setEdit(undefined);
            load();
          }}
        />
      )}
      {remove && (
        <Modal title="Delete scheduled work?" onClose={() => setRemove(null)}>
          <p className="modal-copy">
            Future runs of “{remove.name}” will stop. Existing conversations and
            any run already in progress remain available.
          </p>
          <div className="modal-actions">
            <button className="button" onClick={() => setRemove(null)}>
              Keep it
            </button>
            <button
              className="button danger"
              disabled={!!busy}
              onClick={async () => {
                setBusy(remove.id);
                try {
                  await api("schedules/" + remove.id, {}, "DELETE");
                  setRemove(null);
                  await load();
                } catch (e) {
                  notify(e.message);
                } finally {
                  setBusy("");
                }
              }}
            >
              Delete schedule
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}
