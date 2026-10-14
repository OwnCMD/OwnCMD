"use client";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { Modal, Icon } from "./UI";
import { humanLabel } from "./DashboardCharts";
const fresh = () => ({
  name: "",
  description: "",
  tags: [],
  when_to_use: [],
  when_not_to_use: [],
  capabilities: [],
  version: 1,
  instructions: "",
  resources: [],
});
const lists = {
  tags: "Tags (one per line)",
  when_to_use: "When to use (one per line)",
  when_not_to_use: "When not to use (one per line)",
};
const capabilities = {
  search_web: "Web search",
  browse: "Browser",
  run_code: "Code sandbox",
  files: "Files",
};
function encode(bytes) {
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s);
}
export function SkillSelector({
  value = { mode: "auto", pins: [] },
  onChange,
  disabled = false,
}) {
  const [items, setItems] = useState([]),
    [q, setQ] = useState(""),
    [error, setError] = useState("");
  useEffect(() => {
    api("skills")
      .then((r) => setItems(r.skills))
      .catch((e) => setError(e.message));
  }, []);
  const pins = value.pins || [];
  return (
    <div className="skill-selector">
      <label>
        Skills{" "}
        <select
          aria-label="Skills mode"
          disabled={disabled}
          value={value.mode}
          onChange={(e) => onChange({ mode: e.target.value, pins: [] })}
        >
          <option value="auto">Auto</option>
          <option value="selected">Selected</option>
          <option value="none">None</option>
        </select>
      </label>
      {value.mode === "selected" && (
        <details>
          <summary>Choose Skills ({pins.length}/3)</summary>
          <input
            aria-label="Search Skills to select"
            placeholder="Search enabled Skills"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <div className="skill-options">
            {items
              .filter(
                (x) =>
                  x.enabled &&
                  !x.archived &&
                  (x.name + " " + x.description)
                    .toLowerCase()
                    .includes(q.toLowerCase()),
              )
              .map((x) => {
                const p = pins.find((p) => p.id === x.id),
                  latest = {
                    id: x.id,
                    version_id: x.active_version,
                    name: x.name,
                    version: x.version,
                  };
                return (
                  <div key={x.id}>
                    <label>
                      <input
                        type="checkbox"
                        checked={!!p}
                        disabled={disabled || (!p && pins.length >= 3)}
                        onChange={(e) =>
                          onChange({
                            ...value,
                            pins: e.target.checked
                              ? [...pins, latest]
                              : pins.filter((p) => p.id !== x.id),
                          })
                        }
                      />
                      {x.name} · v{p?.version || x.version}
                    </label>
                    {p && p.version_id !== x.active_version && (
                      <button
                        type="button"
                        className="button small"
                        disabled={disabled}
                        onClick={() =>
                          onChange({
                            ...value,
                            pins: pins.map((p) => (p.id === x.id ? latest : p)),
                          })
                        }
                      >
                        Upgrade to v{x.version}
                      </button>
                    )}
                  </div>
                );
              })}
          </div>
        </details>
      )}
      {pins.length > 0 && (
        <div className="skill-chips">
          {pins.map((p) => (
            <span key={p.id}>
              {p.name} · v{p.version}
            </span>
          ))}
        </div>
      )}
      {error && <small role="alert">{error}</small>}
    </div>
  );
}
export function SkillEditor({ initial, onClose, onSaved }) {
  const [d, setD] = useState(initial?.package || fresh()),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [versions, setVersions] = useState([]),
    [step, setStep] = useState(0),
    [aiGoal, setAiGoal] = useState(""),
    [aiDraft, setAiDraft] = useState(null),
    [resource, setResource] = useState(null);
  const wizard = !!initial?.manual;
  function next() {
    if (step === 0 && (!d.name.trim() || !d.description.trim())) {
      setError("Add a name and description to continue.");
      return;
    }
    if (step === 2 && !d.instructions.trim()) {
      setError("Add instructions to continue.");
      return;
    }
    setError("");
    setStep(Math.min(3, step + 1));
  }
  const patch = (k, v) => setD((x) => ({ ...x, [k]: v }));
  async function action(fn) {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  async function save(e) {
    e.preventDefault();
    if (wizard && step < 3) {
      next();
      return;
    }
    await action(async () => {
      const data = {
        ...d,
        ...Object.fromEntries(
          Object.keys(lists).map((k) => [k, d[k].filter((x) => x.trim())]),
        ),
      };
      await api(
        initial?.id ? "skills/" + initial.id : "skills",
        { package: data, expected_revision: initial?.revision },
        initial?.id ? "PUT" : "POST",
      );
      onSaved();
    });
  }
  async function files(e) {
    const selected = [...e.target.files];
    e.target.value = "";
    await action(async () => {
      const resources = [...d.resources];
      for (const f of selected) {
        if (f.size > 524288)
          throw Error("Each resource must be at most 512 KB");
        const path = window.prompt(
          "Resource path (scripts/, references/, templates/, assets/):",
          "references/" + f.name,
        );
        if (path)
          resources.push({
            path,
            data: encode(new Uint8Array(await f.arrayBuffer())),
          });
      }
      patch("resources", resources);
    });
  }
  function content(r) {
    try {
      return new TextDecoder("utf-8", { fatal: true }).decode(
        Uint8Array.from(atob(r.data), (c) => c.charCodeAt(0)),
      );
    } catch {
      return null;
    }
  }
  return (
    <Modal
      title={
        initial?.id
          ? "Edit Skill"
          : wizard
            ? "Create Skill"
            : "Review Skill draft"
      }
      onClose={onClose}
      wide
    >
      <form
        className="skill-form"
        onSubmit={save}
        noValidate={wizard && step < 3}
      >
        {wizard && (
          <ol className="wizard-steps" aria-label="Skill setup steps">
            {["Basics", "Matching & tools", "Instructions", "Review"].map(
              (label, i) => (
                <li
                  key={label}
                  className={
                    i === step ? "current" : i < step ? "complete" : ""
                  }
                  aria-current={i === step ? "step" : undefined}
                >
                  <span>{i < step ? "✓" : i + 1}</span>
                  {label}
                </li>
              ),
            )}
          </ol>
        )}
        <p className="muted">
          Saving creates a version and indexes matching metadata using your
          model provider. Review instructions and resources before saving.
          Scripts run only through Work’s code sandbox.
        </p>
        <fieldset disabled={busy}>
          {initial?.id && (
            <details className="ai-draft-panel">
              <summary>
                <Icon name="spark" />
                Improve with AI
              </summary>
              <p>
                Describe changes to the saved version. AI uses your model
                provider and preserves existing resource files. Review before
                applying; applying replaces unsaved editor changes, and does not
                save automatically.
              </p>
              <label>
                Requested changes
                <textarea
                  value={aiGoal}
                  onChange={(e) => setAiGoal(e.target.value)}
                  maxLength={4000}
                />
              </label>
              <button
                type="button"
                className="button"
                disabled={busy || !aiGoal.trim()}
                onClick={() =>
                  action(async () =>
                    setAiDraft(
                      (
                        await api("skills/" + initial.id + "/edit-draft", {
                          goal: aiGoal,
                          expected_revision: initial.revision,
                        })
                      ).draft,
                    ),
                  )
                }
              >
                Draft improvements
              </button>
              {aiDraft && (
                <div className="ai-draft-review">
                  <h3>{humanLabel(aiDraft.name)}</h3>
                  <p>{aiDraft.description}</p>
                  <details>
                    <summary>Review all proposed changes</summary>
                    <pre>
                      {JSON.stringify(
                        {
                          ...aiDraft,
                          resources: aiDraft.resources.map((r) => r.path),
                        },
                        null,
                        2,
                      )}
                    </pre>
                  </details>
                  <button
                    className="button primary"
                    type="button"
                    onClick={() => {
                      setD(aiDraft);
                      setAiDraft(null);
                    }}
                  >
                    Apply draft to editor
                  </button>
                  <button
                    className="button"
                    type="button"
                    onClick={() => setAiDraft(null)}
                  >
                    Discard draft
                  </button>
                </div>
              )}
            </details>
          )}
          <div hidden={wizard && step !== 0} className="wizard-fields">
            <label>
              Name
              <input
                aria-label="Name"
                required
                maxLength={100}
                value={d.name}
                onChange={(e) => patch("name", e.target.value)}
              />
            </label>
            <label>
              Description
              <textarea
                aria-label="Description"
                required
                maxLength={600}
                value={d.description}
                onChange={(e) => patch("description", e.target.value)}
              />
            </label>
          </div>
          <div hidden={wizard && step !== 1} className="wizard-fields">
            {Object.entries(lists).map(([k, label]) => (
              <label key={k}>
                {label}
                <textarea
                  aria-label={label}
                  value={d[k].join("\n")}
                  onChange={(e) => patch(k, e.target.value.split("\n"))}
                />
              </label>
            ))}
            <div className="skill-capabilities">
              {Object.entries(capabilities).map(([k, label]) => (
                <label key={k}>
                  <input
                    type="checkbox"
                    checked={d.capabilities.includes(k)}
                    onChange={(e) =>
                      patch(
                        "capabilities",
                        e.target.checked
                          ? [...d.capabilities, k]
                          : d.capabilities.filter((x) => x !== k),
                      )
                    }
                  />
                  {label}
                </label>
              ))}
            </div>
          </div>
          <div hidden={wizard && step !== 2} className="wizard-fields">
            <label>
              Instructions
              <textarea
                aria-label="Instructions"
                required
                rows={12}
                maxLength={12000}
                value={d.instructions}
                onChange={(e) => patch("instructions", e.target.value)}
              />
            </label>
            <div className="skill-resources">
              <strong>Resources</strong>
              <label className="button small">
                Add resource
                <input type="file" hidden multiple onChange={files} />
              </label>
              {d.resources.map((r, i) => (
                <div key={i}>
                  <button
                    type="button"
                    className="button small"
                    onClick={() => setResource(resource === i ? null : i)}
                  >
                    {r.path}
                  </button>
                  <button
                    type="button"
                    className="button small"
                    onClick={() =>
                      patch(
                        "resources",
                        d.resources.filter((_, j) => i !== j),
                      )
                    }
                  >
                    Remove
                  </button>
                  {resource === i &&
                    (content(r) === null ? (
                      <p>Binary resource. Included in ZIP export.</p>
                    ) : (
                      <textarea
                        aria-label={"Resource content: " + r.path}
                        rows={8}
                        value={content(r)}
                        onChange={(e) =>
                          patch(
                            "resources",
                            d.resources.map((r, j) =>
                              i === j
                                ? {
                                    ...r,
                                    data: encode(
                                      new TextEncoder().encode(e.target.value),
                                    ),
                                  }
                                : r,
                            ),
                          )
                        }
                      />
                    ))}
                </div>
              ))}
            </div>
          </div>
          {wizard && step === 3 && (
            <section className="skill-review">
              <span className="eyebrow">READY TO SAVE</span>
              <h2>{humanLabel(d.name)}</h2>
              <p>{d.description}</p>
              <div className="skill-chips">
                {d.capabilities.map((c) => (
                  <span key={c}>{capabilities[c]}</span>
                ))}
              </div>
              <h3>When to use</h3>
              <p>
                {d.when_to_use.filter(Boolean).join(" · ") ||
                  "Automatic selection uses the description and tags."}
              </p>
              <h3>Instructions</h3>
              <pre>{d.instructions}</pre>
              <p>
                {d.resources.length} resource files · Saving indexes this skill
                and uses your model provider.
              </p>
            </section>
          )}
          {initial?.id && (
            <details
              onToggle={(e) => {
                if (e.currentTarget.open && !versions.length)
                  api("skills/" + initial.id + "/versions")
                    .then((r) => setVersions(r.versions))
                    .catch((e) => setError(e.message));
              }}
            >
              <summary>Version history</summary>
              {versions.map((v) => (
                <div className="skill-version" key={v.id}>
                  <span>
                    v{v.number} · {new Date(v.created * 1000).toLocaleString()}
                  </span>
                  <a
                    href={
                      "/api/skills/" + initial.id + "/export?version=" + v.id
                    }
                  >
                    Export
                  </a>
                  <button
                    type="button"
                    className="button small"
                    onClick={() =>
                      action(async () => {
                        await api("skills/" + initial.id + "/restore", {
                          version_id: v.id,
                          expected_revision: initial.revision,
                        });
                        onSaved();
                      })
                    }
                  >
                    Restore as new version
                  </button>
                </div>
              ))}
            </details>
          )}
        </fieldset>
        {error && (
          <p role="alert" className="form-error">
            {error}
          </p>
        )}
        <div className="inline-actions">
          {wizard && step > 0 && (
            <button
              className="button"
              type="button"
              disabled={busy}
              onClick={() => {
                setError("");
                setStep(step - 1);
              }}
            >
              Back
            </button>
          )}
          <button className="button primary" disabled={busy}>
            {busy ? "Saving…" : wizard && step < 3 ? "Next" : "Save Skill"}
          </button>
          <button
            type="button"
            className="button"
            disabled={busy}
            onClick={onClose}
          >
            Cancel
          </button>
        </div>
      </form>
    </Modal>
  );
}
export function SaveAsSkill({ task, notify, onSaved }) {
  const [draft, setDraft] = useState(null),
    [busy, setBusy] = useState(false);
  return (
    <>
      <button
        className="button small"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          try {
            setDraft(
              (await api("tasks/" + task.id + "/skill-draft", {})).draft,
            );
          } catch (e) {
            notify(e.message);
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? "Preparing draft…" : "Save as Skill"}
      </button>
      {draft && (
        <SkillEditor
          initial={{ package: draft }}
          onClose={() => setDraft(null)}
          onSaved={() => {
            setDraft(null);
            notify("Skill saved");
            onSaved?.();
          }}
        />
      )}
    </>
  );
}
export function Skills({ notify }) {
  const [items, setItems] = useState([]),
    [q, setQ] = useState(""),
    [searchResult, setSearchResult] = useState(null),
    [filter, setFilter] = useState("all"),
    [editor, setEditor] = useState(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [goal, setGoal] = useState(""),
    [match, setMatch] = useState(null),
    [runs, setRuns] = useState([]),
    [run, setRun] = useState(""),
    [loading, setLoading] = useState(true);
  const load = () =>
    api("skills")
      .then((r) => setItems(r.skills))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  useEffect(() => {
    load();
  }, []);
  async function action(fn) {
    setBusy(true);
    setError("");
    try {
      await fn();
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  async function importFile(e) {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (f)
      await action(async () => {
        if (f.size > 8 * 1024 * 1024) throw Error("ZIP must be at most 8 MB");
        setEditor({
          package: (
            await api("skills/import", {
              data: encode(new Uint8Array(await f.arrayBuffer())),
            })
          ).draft,
        });
      });
  }
  const visible = (searchResult?.skills || items).filter(
    (x) =>
      (searchResult ||
        (x.name + " " + x.description + " " + x.tags.join(" "))
          .toLowerCase()
          .includes(q.toLowerCase())) &&
      (filter === "all" ||
        (filter === "archived" && x.archived) ||
        (filter === "enabled" && x.enabled && !x.archived) ||
        (filter === "disabled" && !x.enabled && !x.archived)),
  );
  return (
    <section className="skills-page">
      <header className="skills-hero">
        <div>
          <span className="eyebrow">YOUR EXPERTISE, ON REPEAT</span>
          <h1>Skills</h1>
          <p>
            Turn the way you work into a process OwnCMD can follow. Build it
            once, use it whenever it fits.
          </p>
          <div className="skill-actions">
            <button
              className="button primary"
              disabled={busy}
              onClick={() => setEditor({ package: fresh(), manual: true })}
            >
              <Icon name="plus" size={16} />
              Create Skill
            </button>
            <label className="button">
              <Icon name="folder" size={16} />
              Import ZIP
              <input
                type="file"
                hidden
                accept=".zip"
                disabled={busy}
                onChange={importFile}
              />
            </label>
          </div>
        </div>
        <aside className="skills-auto">
          <span className="skills-auto-icon">
            <Icon name="spark" size={23} />
          </span>
          <strong>Ready when you need it</strong>
          <p>
            OwnCMD automatically finds relevant Skills in Work. You stay focused
            on the outcome.
          </p>
          <span>
            {items.filter((x) => x.enabled && !x.archived).length} active ·
            Automatically selected
          </span>
        </aside>
      </header>
      <div className="skill-launch-grid">
        <details className="skill-ai">
          <summary>
            <span className="skill-launch-icon">
              <Icon name="spark" />
            </span>
            <span>
              <strong>Create with AI or test matching</strong>
              <small>Describe your process. Review the result.</small>
            </span>
            <Icon name="chevron" size={16} />
          </summary>
          <div className="skill-panel-content">
            <p>
              AI drafts and matching checks use your model provider. Nothing is
              saved until you review it.
            </p>
            <label>
              Describe a reusable process or matching query
              <textarea
                aria-label="Describe a reusable process or matching query"
                placeholder="For example: research a company, compare its competitors and create an evidence-backed brief…"
                value={goal}
                maxLength={4000}
                onChange={(e) => setGoal(e.target.value)}
              />
            </label>
            <div className="inline-actions">
              <button
                className="button primary"
                disabled={busy || !goal.trim()}
                onClick={() =>
                  action(async () =>
                    setEditor({
                      package: (await api("skills/generate", { goal })).draft,
                    }),
                  )
                }
              >
                Create with AI
              </button>
              <button
                className="button"
                disabled={busy || !goal.trim()}
                onClick={() =>
                  action(async () =>
                    setMatch(await api("skills/match", { query: goal })),
                  )
                }
              >
                Test matching
              </button>
            </div>
            {match && (
              <div className="skill-match-result">
                <p>
                  {match.pins.length
                    ? "Selected: " + match.pins.map((p) => p.name).join(", ")
                    : "No Skill selected"}
                </p>
                <details>
                  <summary>Matching diagnostics</summary>
                  <pre>{JSON.stringify(match, null, 2)}</pre>
                </details>
              </div>
            )}
          </div>
        </details>
        <details
          className="skill-ai"
          onToggle={(e) => {
            if (e.currentTarget.open)
              api("tasks")
                .then((rows) =>
                  setRuns(
                    rows.filter(
                      (x) => x.mode === "work" && x.status === "completed",
                    ),
                  ),
                )
                .catch((e) => setError(e.message));
          }}
        >
          <summary>
            <span className="skill-launch-icon">
              <Icon name="work" />
            </span>
            <span>
              <strong>Create from completed Work</strong>
              <small>Keep a successful workflow for next time.</small>
            </span>
            <Icon name="chevron" size={16} />
          </summary>
          <div className="skill-panel-content">
            <p>
              Choose a completed conversation to turn its process into a
              reusable draft.
            </p>
            <select
              aria-label="Completed Work conversation"
              value={run}
              onChange={(e) => setRun(e.target.value)}
            >
              <option value="">Choose a completed conversation</option>
              {runs.map((x) => (
                <option key={x.id} value={x.id}>
                  {x.title}
                </option>
              ))}
            </select>
            {run && (
              <SaveAsSkill task={{ id: run }} notify={notify} onSaved={load} />
            )}
          </div>
        </details>
      </div>
      <div className="skill-library-heading">
        <h2>
          Your Skills <span>{items.length}</span>
        </h2>
        <details className="skill-library-tools">
          <summary>
            <Icon name="settings" size={15} />
            Library tools
          </summary>
          <button
            className="button small"
            disabled={busy}
            onClick={() =>
              action(async () => {
                const r = await api("skills/reindex", {});
                notify(`Reindexed ${r.indexed} Skills`);
              })
            }
          >
            Rebuild search index
          </button>
        </details>
      </div>
      <div className="skill-filters">
        <label className="skill-search">
          <Icon name="search" size={17} />
          <input
            aria-label="Search Skills"
            placeholder="Search your Skills…"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setSearchResult(null);
            }}
          />
        </label>
        <button
          className="button"
          disabled={busy || !q.trim()}
          onClick={() =>
            action(async () =>
              setSearchResult(await api("skills/search", { query: q })),
            )
          }
        >
          Search by meaning
        </button>
        <div
          className="skill-status-tabs"
          role="group"
          aria-label="Skill status filter"
        >
          {Object.entries({
            all: "All Skills",
            enabled: "Enabled",
            disabled: "Disabled",
            archived: "Archived",
          }).map(([key, label]) => (
            <button
              type="button"
              key={key}
              aria-pressed={filter === key}
              onClick={() => setFilter(key)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      <p className="muted">
        Typing filters by name and description. Search by meaning uses your
        skill vectors and provider usage; Work’s automatic matching is
        unchanged.
        {searchResult &&
          (searchResult.notice
            ? " " + searchResult.notice
            : searchResult.semantic
              ? " Showing semantic and keyword matches."
              : " Showing keyword matches.")}
      </p>
      {error && (
        <p role="alert" className="form-error">
          {error}
        </p>
      )}
      {loading ? (
        <div className="skills-empty" role="status">
          Loading your Skills…
        </div>
      ) : (
        <div className="skill-grid">
          {visible.map((x) => (
            <article className="skill-card" key={x.id}>
              <div className="skill-card-top">
                <span className="skill-card-icon">
                  <Icon name="work" size={21} />
                </span>
                <span
                  className={
                    "skill-state " +
                    (x.archived
                      ? "archived"
                      : x.enabled
                        ? "enabled"
                        : "disabled")
                  }
                >
                  {x.archived ? "Archived" : x.enabled ? "Enabled" : "Disabled"}
                </span>
              </div>
              <div className="skill-card-head">
                <h2>{humanLabel(x.name)}</h2>
              </div>
              <p>{x.description}</p>
              <div className="skill-chips">
                {x.tags.slice(0, 3).map((t) => (
                  <span key={t}>{t}</span>
                ))}
                {x.tags.length > 3 && <span>+{x.tags.length - 3}</span>}
              </div>
              <small className="skill-card-meta">
                v{x.version}
                <span>
                  Updated {new Date(x.updated * 1000).toLocaleDateString()}
                </span>
              </small>
              <div className="skill-card-footer">
                <button
                  className="button small"
                  disabled={busy}
                  onClick={() =>
                    action(async () => setEditor(await api("skills/" + x.id)))
                  }
                >
                  <Icon name="file" size={14} />
                  Edit
                </button>
                <a
                  className="button small"
                  href={"/api/skills/" + x.id + "/export"}
                >
                  <Icon name="down" size={14} />
                  Export
                </a>
                <details className="skill-card-menu">
                  <summary aria-label={"More actions for " + x.name}>
                    <Icon name="menu" size={16} />
                  </summary>
                  <div>
                    <button
                      disabled={busy}
                      onClick={() =>
                        action(() => api("skills/" + x.id + "/duplicate", {}))
                      }
                    >
                      Duplicate
                    </button>
                    <button
                      disabled={busy}
                      onClick={() =>
                        action(() =>
                          api("skills/" + x.id + "/status", {
                            expected_revision: x.revision,
                            enabled: !x.enabled,
                          }),
                        )
                      }
                    >
                      {x.enabled ? "Disable" : "Enable"}
                    </button>
                    <button
                      disabled={busy}
                      onClick={() =>
                        action(() =>
                          api("skills/" + x.id + "/status", {
                            expected_revision: x.revision,
                            archived: !x.archived,
                          }),
                        )
                      }
                    >
                      {x.archived ? "Unarchive" : "Archive"}
                    </button>
                    <button
                      className="skill-delete"
                      disabled={busy}
                      onClick={() => {
                        if (
                          window.confirm(
                            "Delete this Skill? Pinned work and schedules will require your attention.",
                          )
                        )
                          action(() =>
                            api(
                              "skills/" + x.id,
                              { expected_revision: x.revision },
                              "DELETE",
                            ),
                          );
                      }}
                    >
                      Delete
                    </button>
                  </div>
                </details>
              </div>
            </article>
          ))}
        </div>
      )}
      {!loading && !visible.length && (
        <div className="skills-empty">
          <span className="skills-empty-icon">
            <Icon name={items.length ? "search" : "spark"} size={28} />
          </span>
          <h3>
            {items.length
              ? "No matching Skills"
              : "Make your best work repeatable"}
          </h3>
          <p>
            {items.length
              ? "Try another search or status filter."
              : "Save your methods, instructions and resources in one place. OwnCMD will bring them into the right tasks."}
          </p>
          {!items.length && (
            <button
              className="button primary"
              onClick={() => setEditor({ package: fresh() })}
            >
              Create your first Skill
              <Icon name="plus" size={16} />
            </button>
          )}
        </div>
      )}
      {editor && (
        <SkillEditor
          initial={editor}
          onClose={() => setEditor(null)}
          onSaved={() => {
            setEditor(null);
            load();
            notify("Skill saved");
          }}
        />
      )}
    </section>
  );
}
