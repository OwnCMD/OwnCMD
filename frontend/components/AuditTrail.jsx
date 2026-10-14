"use client";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { Icon, Modal } from "./UI";
import { Pagination } from "./Pagination";
import { humanLabel } from "./DashboardCharts";
const initial = {
  q: "",
  actor: "",
  target: "",
  action: "",
  category: "",
  period: "30",
  from: "",
  to: "",
  sort: "newest",
};
function params(filters) {
  const p = { ...filters };
  delete p.period;
  if (filters.period !== "custom") {
    delete p.from;
    delete p.to;
    if (filters.period !== "all")
      p.from = Date.now() / 1000 - Number(filters.period) * 86400;
  } else {
    for (const k of ["from", "to"])
      p[k] = p[k] ? new Date(p[k]).getTime() / 1000 : "";
  }
  return p;
}
function flatten(value, prefix = "", out = {}) {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    for (const [k, v] of Object.entries(value))
      flatten(v, prefix ? prefix + "." + k : k, out);
  } else out[prefix] = JSON.stringify(value) ?? "—";
  return out;
}
function Details({ event, onClose }) {
  const before = flatten(event.body.before || {}),
    after = flatten(event.body.after || {}),
    keys = [...new Set([...Object.keys(before), ...Object.keys(after)])].filter(
      (k) => before[k] !== after[k],
    );
  return (
    <Modal title={humanLabel(event.action)} onClose={onClose} wide>
      <div className="audit-detail">
        <p>
          {new Date(event.created * 1000).toLocaleString()} ·{" "}
          {event.actor_email || event.actor}
        </p>
        <dl>
          <dt>Target</dt>
          <dd>{event.target_email || event.target}</dd>
          <dt>Event ID</dt>
          <dd>
            <code>{event.id}</code>
          </dd>
        </dl>
        {event.body.reason && <p>{event.body.reason}</p>}
        {keys.length > 0 && (
          <div className="usage-table-wrap">
            <table>
              <caption>Changed fields</caption>
              <thead>
                <tr>
                  <th>Field</th>
                  <th>Before</th>
                  <th>After</th>
                </tr>
              </thead>
              <tbody>
                {keys.map((k) => (
                  <tr key={k}>
                    <td>{humanLabel(k)}</td>
                    <td>
                      <code>{before[k] ?? "Not set"}</code>
                    </td>
                    <td>
                      <code>{after[k] ?? "Removed"}</code>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <details open={!keys.length}>
          <summary>Full event details</summary>
          <pre>{JSON.stringify(event.body, null, 2)}</pre>
        </details>
      </div>
    </Modal>
  );
}
export function AuditTrail() {
  const [draft, setDraft] = useState(initial),
    [filters, setFilters] = useState(() => params(initial)),
    [data, setData] = useState(null),
    [offset, setOffset] = useState(0),
    [limit, setLimit] = useState(25),
    [snapshot, setSnapshot] = useState(""),
    [refresh, setRefresh] = useState(0),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [selected, setSelected] = useState(null),
    [advanced, setAdvanced] = useState(false),
    [exporting, setExporting] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    setBusy(true);
    setError("");
    api(
      "admin/audit?" +
        new URLSearchParams({
          ...filters,
          offset,
          limit,
          ...(snapshot ? { snapshot } : {}),
        }),
      undefined,
      undefined,
      controller.signal,
    )
      .then((d) => {
        setData(d);
        setSnapshot(d.snapshot);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setBusy(false);
      });
    return () => controller.abort();
  }, [filters, offset, limit, refresh]);
  function apply(value = draft) {
    setFilters(params(value));
    setOffset(0);
    setSnapshot("");
    setRefresh((v) => v + 1);
  }
  async function download() {
    setExporting(true);
    setError("");
    try {
      const response = await fetch(
        "/api/admin/audit/export.csv?" +
          new URLSearchParams({ ...filters, snapshot }),
        { credentials: "same-origin" },
      );
      if (!response.ok) {
        const d = await response.json();
        throw Error(d.detail || "Export failed");
      }
      const url = URL.createObjectURL(await response.blob()),
        a = document.createElement("a");
      a.href = url;
      a.download = "owncmd-audit.csv";
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) {
      setError(e.message);
    } finally {
      setExporting(false);
    }
  }
  const set = (key, value) => setDraft((f) => ({ ...f, [key]: value }));
  return (
    <section className="audit-workspace">
      <div className="audit-heading">
        <div>
          <span className="eyebrow">ACTIVITY & GOVERNANCE</span>
          <h2>Audit trail</h2>
          <p>
            Find who changed what, review the details, and export a filtered
            record.
          </p>
        </div>
        <div className="inline-actions">
          <button className="button" disabled={busy} onClick={() => apply()}>
            Refresh
          </button>
          <button
            className="button"
            disabled={busy || exporting || !data?.total}
            onClick={download}
          >
            {exporting ? "Exporting…" : "Export filtered CSV"}
          </button>
        </div>
      </div>
      <form
        className="audit-filter-panel"
        onSubmit={(e) => {
          e.preventDefault();
          apply();
        }}
      >
        <div className="audit-filter-main">
          <label className="audit-search">
            Search audit events
            <input
              type="search"
              placeholder="Account email, action, resource or event ID"
              value={draft.q}
              onChange={(e) => set("q", e.target.value)}
            />
          </label>
          <label>
            Period
            <select
              value={draft.period}
              onChange={(e) => set("period", e.target.value)}
            >
              {[
                ["1", "Last 24 hours"],
                ["7", "Last 7 days"],
                ["30", "Last 30 days"],
                ["90", "Last 90 days"],
                ["all", "All time"],
                ["custom", "Custom range"],
              ].map(([v, t]) => (
                <option key={v} value={v}>
                  {t}
                </option>
              ))}
            </select>
          </label>
          <label>
            Category
            <select
              value={draft.category}
              onChange={(e) => set("category", e.target.value)}
            >
              <option value="">All categories</option>
              {(data?.categories || []).map((v) => (
                <option key={v} value={v}>
                  {humanLabel(v)}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="button"
            aria-expanded={advanced}
            onClick={() => setAdvanced((v) => !v)}
          >
            More filters
          </button>
          <button className="button primary">Apply filters</button>
        </div>
        {draft.period === "custom" && (
          <div className="audit-filter-extra">
            {["from", "to"].map((k) => (
              <label key={k}>
                {k === "from" ? "From · local time" : "To · local time"}
                <input
                  type="datetime-local"
                  value={draft[k]}
                  onChange={(e) => set(k, e.target.value)}
                />
              </label>
            ))}
          </div>
        )}
        {advanced && (
          <div className="audit-filter-extra">
            <label>
              Action
              <select
                aria-label="Audit action"
                value={draft.action}
                onChange={(e) => set("action", e.target.value)}
              >
                <option value="">All actions</option>
                {data?.actions.map((v) => (
                  <option value={v} key={v}>
                    {humanLabel(v)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Actor ID
              <input
                aria-label="Audit actor"
                placeholder="Exact administrator or system ID"
                value={draft.actor}
                onChange={(e) => set("actor", e.target.value)}
              />
            </label>
            <label>
              Target ID
              <input
                aria-label="Audit target"
                placeholder="Exact account, resource ID or global"
                value={draft.target}
                onChange={(e) => set("target", e.target.value)}
              />
            </label>
            <label>
              Sort order
              <select
                value={draft.sort}
                onChange={(e) => set("sort", e.target.value)}
              >
                <option value="newest">Newest first</option>
                <option value="oldest">Oldest first</option>
              </select>
            </label>
          </div>
        )}
        <div className="audit-filter-foot">
          <span>
            Search matches identities and event metadata. Details are available
            for each event.
          </span>
          <button
            type="button"
            className="text-action"
            onClick={() => {
              setDraft(initial);
              apply(initial);
            }}
          >
            Reset filters
          </button>
        </div>
      </form>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      <div className="audit-result-heading">
        <strong>{data?.total?.toLocaleString() || 0} matching events</strong>
        <span role="status">
          {busy
            ? "Updating…"
            : snapshot
              ? "Snapshot at " + new Date(snapshot * 1000).toLocaleTimeString()
              : ""}
        </span>
      </div>
      <div className="admin-table-wrap audit-table-wrap" aria-busy={busy}>
        <table className="admin-table">
          <thead>
            <tr>
              <th>When</th>
              <th>Action</th>
              <th>Performed by</th>
              <th>Target</th>
              <th>Details</th>
            </tr>
          </thead>
          <tbody>
            {data?.events.map((e) => (
              <tr key={e.id}>
                <td>
                  <time dateTime={new Date(e.created * 1000).toISOString()}>
                    {new Date(e.created * 1000).toLocaleDateString()}
                    <small>
                      {new Date(e.created * 1000).toLocaleTimeString()}
                    </small>
                  </time>
                </td>
                <td>
                  <strong>{humanLabel(e.action)}</strong>
                  <small className="audit-category">
                    {humanLabel(e.category)}
                  </small>
                </td>
                <td>
                  <button
                    className="text-action"
                    onClick={() => {
                      const v = { ...draft, actor: e.actor };
                      setDraft(v);
                      apply(v);
                    }}
                  >
                    {e.actor_email || e.actor}
                  </button>
                </td>
                <td>
                  <button
                    className="text-action"
                    onClick={() => {
                      const v = { ...draft, target: e.target };
                      setDraft(v);
                      apply(v);
                    }}
                  >
                    {e.target_email || e.target}
                  </button>
                </td>
                <td>
                  <button
                    className="button small"
                    onClick={() => setSelected(e)}
                  >
                    View details
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!busy && !data?.events.length && (
          <div className="audit-empty">
            <Icon name="search" />
            <h3>No matching events</h3>
            <p>Try a broader date range or clear a filter.</p>
          </div>
        )}
      </div>
      <Pagination
        total={data?.total || 0}
        offset={offset}
        limit={limit}
        onPage={setOffset}
        onLimit={(n) => {
          setLimit(n);
          setOffset(0);
        }}
        busy={busy}
        label="audit events"
      />
      {selected && (
        <Details event={selected} onClose={() => setSelected(null)} />
      )}
    </section>
  );
}
