"use client";
import { useEffect, useState, useRef } from "react";
import { api } from "../lib/api";
import { Icon, Empty, Modal } from "./UI";
export function Settings({ prefs, onSave, me, notify }) {
  const [tab, setTab] = useState("appearance"),
    [saving, setSaving] = useState(false),
    [status, setStatus] = useState(""),
    [passwordBusy, setPasswordBusy] = useState(false),
    [passwordStatus, setPasswordStatus] = useState("");
  async function save(patch) {
    if (saving) return;
    setSaving(true);
    setStatus("Saving…");
    try {
      await onSave(patch);
      setStatus("Changes saved");
    } catch (e) {
      setStatus(e.message);
    } finally {
      setSaving(false);
    }
  }
  async function password(e) {
    e.preventDefault();
    if (passwordBusy) return;
    const form = e.currentTarget,
      fields = new FormData(form);
    if (fields.get("new") !== fields.get("confirm")) {
      setPasswordStatus("New passwords do not match.");
      return;
    }
    setPasswordBusy(true);
    setPasswordStatus("");
    try {
      await api("change-password", Object.fromEntries(fields));
      form.reset();
      setPasswordStatus(
        "Password updated. Other sessions have been signed out.",
      );
    } catch (e) {
      setPasswordStatus(e.message);
    } finally {
      setPasswordBusy(false);
    }
  }
  return (
    <div className="page settings-page">
      <div className="page-heading">
        <span className="eyebrow">YOUR WORKSPACE</span>
        <h1>Settings</h1>
        <p>Make OwnCMD feel like your own.</p>
      </div>
      <div className="tabs" role="tablist" aria-label="Settings sections">
        {["appearance", "preferences", "account", "browser"].map((t) => (
          <button
            key={t}
            role="tab"
            aria-selected={tab === t}
            onClick={() => setTab(t)}
          >
            {t === "browser"
              ? "Browser & privacy"
              : t[0].toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>
      <div className="settings-content" role="tabpanel" aria-label={tab}>
        {tab === "appearance" && (
          <>
            <section className="settings-section">
              <h2>Appearance</h2>
              <p>Choose a theme for your workspace.</p>
              <fieldset disabled={saving} className="theme-options">
                <legend className="sr-only">Color theme</legend>
                {[
                  ["light", "sun", "Light"],
                  ["dark", "moon", "Dark"],
                  ["system", "monitor", "System"],
                ].map(([value, icon, label]) => (
                  <label
                    key={value}
                    className={
                      "theme-option " +
                      value +
                      (prefs.theme === value ? " selected" : "")
                    }
                  >
                    <input
                      type="radio"
                      name="theme"
                      value={value}
                      checked={prefs.theme === value}
                      onChange={() => save({ theme: value })}
                    />
                    <span className="theme-preview">
                      <i />
                      <b>
                        <i />
                        <i />
                        <i />
                      </b>
                    </span>
                    <span>
                      <Icon name={icon} />
                      {label}
                      {prefs.theme === value && <Icon name="check" size={16} />}
                    </span>
                  </label>
                ))}
              </fieldset>
            </section>
            <section className="settings-section">
              <h2>Typography & spacing</h2>
              {[
                [
                  "font",
                  "Font",
                  [
                    ["inter", "Modern sans"],
                    ["system", "System default"],
                    ["serif", "Serif"],
                    ["mono", "Monospace"],
                  ],
                ],
                [
                  "font_size",
                  "Text size",
                  [
                    ["small", "Small"],
                    ["medium", "Medium"],
                    ["large", "Large"],
                  ],
                ],
                [
                  "density",
                  "Layout density",
                  [
                    ["comfortable", "Comfortable"],
                    ["compact", "Compact"],
                  ],
                ],
              ].map(([key, label, options]) => (
                <label className="setting-row" key={key}>
                  <span>{label}</span>
                  <select
                    disabled={saving}
                    value={prefs[key]}
                    onChange={(e) => save({ [key]: e.target.value })}
                  >
                    {options.map(([v, l]) => (
                      <option key={v} value={v}>
                        {l}
                      </option>
                    ))}
                  </select>
                </label>
              ))}
            </section>
          </>
        )}
        {tab === "preferences" && (
          <section className="settings-section">
            <h2>Conversation preferences</h2>
            <p>Small details that fit the way you work.</p>
            {[
              [
                "send_enter",
                "Enter to send",
                "Use Shift + Enter for a new line. Ctrl / ⌘ + Enter always sends.",
              ],
              [
                "reduce_motion",
                "Reduce motion",
                "Keep transitions and animation to a minimum.",
              ],
              [
                "sources_expanded",
                "Expand sources",
                "Show source cards automatically.",
              ],
              [
                "activity_expanded",
                "Expand activity",
                "Keep the Work activity timeline open.",
              ],
            ].map(([key, label, help]) => (
              <label className="setting-row" key={key}>
                <span>
                  <strong>{label}</strong>
                  <small>{help}</small>
                </span>
                <input
                  className="switch"
                  type="checkbox"
                  role="switch"
                  checked={prefs[key]}
                  disabled={saving}
                  onChange={(e) => save({ [key]: e.target.checked })}
                />
              </label>
            ))}
          </section>
        )}
        {tab === "preferences" && (
          <section className="settings-section">
            <h2>Ways to work</h2>
            <p>Choose the mode that fits your task.</p>
            <div className="setting-row">
              <span>
                <strong>Chat</strong>
                <small>Conversation and current web research</small>
              </span>
              <strong>Fast answers and everyday assistance</strong>
            </div>
            <div className="setting-row">
              <span>
                <strong>Work</strong>
                <small>Browser, code, files, and task execution</small>
              </span>
              <strong>Research, coding and multi-step work</strong>
            </div>
            <p className="model-note">
              Your mode determines the capabilities available in a conversation.
            </p>
          </section>
        )}
        {tab === "browser" && (
          <section className="settings-section privacy-card">
            <div className="privacy-symbol">
              <Icon name="shield" size={28} />
            </div>
            <h2>Saved browser sign-ins</h2>
            <p>
              Website sessions are stored privately for your account for up to
              30 days. Websites may expire sessions sooner.
            </p>
            <div className="privacy-facts">
              <div>
                <strong>Account isolated</strong>
                <span>Other users cannot access your saved sessions.</span>
              </div>
              <div>
                <strong>You stay in control</strong>
                <span>
                  Clearing signs you out of saved websites and closes your
                  active cloud browsers. It does not delete your OwnCMD account.
                </span>
              </div>
            </div>
            <button
              className="button"
              disabled={saving}
              onClick={async () => {
                if (
                  !window.confirm(
                    "Clear your saved website sign-ins and close your cloud browser sessions?",
                  )
                )
                  return;
                setSaving(true);
                try {
                  await api("browser-session/clear", {});
                  notify("Saved website sign-ins cleared");
                } catch (e) {
                  notify(e.message);
                } finally {
                  setSaving(false);
                }
              }}
            >
              Clear saved sign-ins
            </button>
          </section>
        )}
        {tab === "account" && (
          <>
            <section className="settings-section">
              <h2>Account</h2>
              <div className="setting-row">
                <span>Email address</span>
                <strong className="account-email">{me.email}</strong>
              </div>
              <div className="setting-row">
                <span>Role</span>
                <strong>
                  {me.account?.role === "admin" ? "Owner" : "Member"}{" "}
                  <a href="#usage" className="muted">
                    View usage
                  </a>
                </strong>
              </div>
            </section>
            <section className="settings-section">
              <h2>Change password</h2>
              <p>
                Use 12–128 characters. Your other sessions will be signed out.
              </p>
              <form className="password-form" onSubmit={password}>
                {[
                  ["current", "Current password", "current-password"],
                  ["new", "New password", "new-password"],
                  ["confirm", "Confirm new password", "new-password"],
                ].map(([name, label, auto]) => (
                  <label key={name}>
                    {label}
                    <input
                      type="password"
                      name={name}
                      autoComplete={auto}
                      required
                      minLength={name === "current" ? 1 : 12}
                      maxLength={128}
                    />
                  </label>
                ))}
                <p className="form-status" role="status">
                  {passwordStatus}
                </p>
                <button className="button primary" disabled={passwordBusy}>
                  {passwordBusy ? "Updating…" : "Update password"}
                </button>
              </form>
            </section>
          </>
        )}
      </div>
      <p className="save-status" role="status">
        {status}
      </p>
    </div>
  );
}
export function Collection({ kind, notify }) {
  const [rows, setRows] = useState(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [remove, setRemove] = useState(null),
    [text, setText] = useState("");
  const generation = useRef(0);
  const memory = kind === "memory";
  async function load() {
    const version = ++generation.current;
    try {
      const data = await api(kind);
      if (version === generation.current) {
        setRows(data);
        setError("");
      }
    } catch (e) {
      if (version === generation.current) setError(e.message);
    }
  }
  useEffect(() => {
    setRows(null);
    load();
    return () => {
      generation.current++;
    };
  }, [kind]);
  async function add(e) {
    e.preventDefault();
    if (busy || !text.trim()) return;
    setBusy(true);
    try {
      await api("memory", { text });
      setText("");
      await load();
      notify("Memory saved");
    } catch (e) {
      notify(e.message);
    } finally {
      setBusy(false);
    }
  }
  async function del() {
    setBusy(true);
    try {
      await api(kind + "/" + remove.id, {}, "DELETE");
      setRemove(null);
      await load();
    } catch (e) {
      notify(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="page">
      <div className="page-heading">
        <span className="eyebrow">YOUR WORKSPACE</span>
        <h1>{memory ? "Memory" : "Scheduled work"}</h1>
        <p>
          {memory
            ? "The details OwnCMD remembers, managed by you."
            : "Keep track of the work you’ve asked OwnCMD to repeat."}
        </p>
      </div>
      {memory && (
        <form className="memory-form" onSubmit={add}>
          <label htmlFor="memory-text">
            What would you like OwnCMD to remember?
          </label>
          <textarea
            id="memory-text"
            placeholder="A preference, a detail, or helpful context…"
            maxLength={2000}
            value={text}
            onChange={(e) => setText(e.target.value)}
            required
          />
          <div>
            <small>Used to personalize future conversations.</small>
            <button className="button primary" disabled={busy}>
              Save memory
            </button>
          </div>
        </form>
      )}
      {error ? (
        <div className="error-card" role="alert">
          {error}
          <button className="button" onClick={load}>
            Try again
          </button>
        </div>
      ) : rows === null ? (
        <p className="loading-copy" role="status">
          Loading {kind}…
        </p>
      ) : rows.length === 0 ? (
        <Empty
          icon={memory ? "memory" : "clock"}
          title={memory ? "A fresh start" : "Nothing scheduled yet"}
        >
          {memory
            ? "Add useful context above, or ask OwnCMD to remember something in a conversation."
            : "Start a Work conversation and ask OwnCMD to schedule a task."}
        </Empty>
      ) : (
        <div className="collection-list">
          <div className="collection-label">
            {rows.length} {memory ? "saved memories" : "scheduled tasks"}
          </div>
          {rows.map((row) => (
            <article key={row.id}>
              <Icon name={memory ? "memory" : "clock"} />
              <div>
                <p>{memory ? row.text : row.prompt}</p>
                {!memory && (
                  <small>
                    Next: {new Date(row.next * 1000).toLocaleString()}
                    {row.interval
                      ? " · Every " + row.interval / 3600 + " hours"
                      : ""}
                  </small>
                )}
              </div>
              <button className="button subtle" onClick={() => setRemove(row)}>
                {memory ? "Forget" : "Delete"}
              </button>
            </article>
          ))}
        </div>
      )}
      {remove && (
        <Modal
          title={memory ? "Forget this memory?" : "Delete scheduled work?"}
          onClose={() => !busy && setRemove(null)}
        >
          <p className="modal-copy">
            {memory
              ? "OwnCMD will no longer use this saved detail."
              : "This task will no longer run on its schedule."}
          </p>
          <div className="modal-actions">
            <button
              className="button"
              onClick={() => setRemove(null)}
              disabled={busy}
            >
              Keep it
            </button>
            <button className="button danger" onClick={del} disabled={busy}>
              {busy
                ? "Deleting…"
                : memory
                  ? "Forget memory"
                  : "Delete schedule"}
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}
