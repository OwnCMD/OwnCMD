"use client";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { loadUsage } from "../lib/usage-request.mjs";
import { Icon } from "./UI";
import { Pie } from "./DashboardCharts";
import { UsageInsights } from "./UsageInsights";
const names = {
  model: "AI usage",
  title: "Conversation titles",
  search: "Web search",
  browser: "Browser workspace",
  code: "Coding workspace",
  skill_embedding: "Skill embeddings",
  skill_rerank: "Skill matching",
  skill_generation: "Skill drafting",
};
const label = (r) =>
  r.service === "model"
    ? `${r.mode === "chat" ? "Chat" : "Work"} mode · AI usage`
    : names[r.service] || "Usage";
const money = (n, d = 6) =>
  n == null
    ? "Pending"
    : new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
        minimumFractionDigits: 2,
        maximumFractionDigits: d,
      }).format(n);
const count = (n) => Number(n || 0).toLocaleString("en-US");
const dayLabel = (n) =>
  new Date(n * 1000).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
const defaults = {
  days: "30",
  service: "all",
  mode: "all",
  status: "all",
  query: "",
  start_date: "",
  end_date: "",
  sort: "newest",
  min_charge: "",
  max_charge: "",
  model: "all",
  provider: "all",
  task: "",
  min_tokens: "",
  max_tokens: "",
};
export function Usage({ notify = () => {}, owner = "", global = false }) {
  const [data, setData] = useState(null),
    [pricing, setPricing] = useState(null),
    [pricingError, setPricingError] = useState(""),
    [filters, setFilters] = useState(defaults),
    [offset, setOffset] = useState(0),
    [limit, setLimit] = useState(25),
    [tab, setTab] = useState("overview"),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(true),
    [hover, setHover] = useState(null),
    [chart, setChart] = useState("daily"),
    [advanced, setAdvanced] = useState(false),
    [refresh, setRefresh] = useState(0);
  const params = new URLSearchParams({
    ...filters,
    days: filters.days === "custom" ? "30" : filters.days,
    ...(filters.days !== "custom" ? { start_date: "", end_date: "" } : {}),
    offset: String(offset),
    limit: String(limit),
  }).toString();
  function change(key, value) {
    setFilters((f) => ({ ...f, [key]: value }));
    setOffset(0);
    setHover(null);
  }
  useEffect(() => {
    let active = true;
    api("pricing")
      .then((p) => {
        if (active) setPricing(p);
      })
      .catch((e) => {
        if (active) setPricingError(e.message);
      });
    return () => {
      active = false;
    };
  }, []);
  const dateError =
    filters.days !== "custom"
      ? ""
      : !filters.start_date || !filters.end_date
        ? "Choose both dates to load your custom period."
        : filters.start_date > filters.end_date
          ? "The start date must be on or before the end date."
          : "";
  useEffect(() => {
    if (dateError) {
      setData(null);
      setBusy(false);
      setError("");
      return;
    }
    let active = true,
      inflight = false;
    const controller = new AbortController();
    setBusy(true);
    setData(null);
    setError("");
    async function load(initial = false) {
      if (inflight || (!initial && document.hidden)) return;
      inflight = true;
      setBusy(true);
      try {
        const result = await loadUsage(
          params,
          (path, signal) =>
            api(
              owner
                ? `admin/users/${owner}/${path}`
                : global
                  ? `admin/${path}`
                  : path,
              undefined,
              "GET",
              signal,
            ),
          { signal: controller.signal },
        );
        if (active) {
          setData(result);
          setError("");
        }
      } catch (e) {
        if (active && e.name !== "AbortError") setError(e.message);
      } finally {
        inflight = false;
        if (active) setBusy(false);
      }
    }
    const debounce = setTimeout(() => load(true), 250),
      timer = setInterval(() => load(), 15000);
    const visible = () => {
      if (!document.hidden) load();
    };
    document.addEventListener("visibilitychange", visible);
    return () => {
      active = false;
      controller.abort();
      clearTimeout(debounce);
      clearInterval(timer);
      document.removeEventListener("visibilitychange", visible);
    };
  }, [params, refresh, owner, global, dateError]);
  let cumulative = 0;
  const rows = Array.from({ length: data?.days || 0 }, (_, i) => {
      const day = data.start + i * 86400;
      const r = data.daily.find((r) => r.day === day) || {
        day,
        charge: 0,
        requests: 0,
      };
      cumulative += r.charge;
      return { ...r, cumulative };
    }),
    max = Math.max(
      0.000001,
      ...rows.map((r) => (chart === "daily" ? r.charge : r.cumulative)),
    ),
    focus = hover == null ? null : rows[hover],
    forecast = data?.forecast;
  const page = Math.floor((data?.offset ?? offset) / limit) + 1,
    pages = Math.max(1, Math.ceil((data?.total || 0) / limit));
  const tokens =
    (data?.totals.input_tokens || 0) + (data?.totals.output_tokens || 0);
  return (
    <div className="usage-page">
      <div className="usage-heading">
        <div>
          <span className="eyebrow">
            {global
              ? "ALL ACCOUNTS"
              : owner
                ? "SELECTED ACCOUNT"
                : "YOUR ACCOUNT"}{" "}
            · USD
          </span>
          <h1>{global ? "Instance usage" : "Usage"}</h1>
          <p>Understand your activity and provider costs. No OwnCMD markup.</p>
        </div>
        <span className="usage-live">
          <i className="live-dot" />
          {busy ? "Updating…" : "Refreshes every 15 seconds"}
        </span>
      </div>
      <nav className="usage-tabs" aria-label="Usage sections">
        {[
          ["overview", "Overview"],
          ["activity", "Activity"],

          ["pricing", "Provider rates"],
        ]
          .filter(([key]) => !(owner || global) || key !== "pricing")
          .map(([key, label]) => (
            <button
              key={key}
              aria-current={tab === key ? "page" : undefined}
              onClick={() => setTab(key)}
            >
              {label}
            </button>
          ))}
      </nav>
      {error && (
        <div className="error-card" role="alert">
          {error}{" "}
          <button
            className="button small"
            disabled={busy}
            onClick={() => setRefresh((v) => v + 1)}
          >
            Retry usage
          </button>
        </div>
      )}
      {tab !== "pricing" && (
        <div className="usage-filter-panel">
          <div className="usage-filters">
            <div>
              <label>
                Period
                <select
                  aria-label="Usage period"
                  value={filters.days}
                  onChange={(e) => change("days", e.target.value)}
                >
                  <option value="7">Last 7 days</option>
                  <option value="30">Last 30 days</option>
                  <option value="90">Last 90 days</option>
                  <option value="custom">Custom dates</option>
                </select>
              </label>
              <label>
                Service
                <select
                  aria-label="Usage service"
                  value={filters.service}
                  onChange={(e) => change("service", e.target.value)}
                >
                  <option value="all">All services</option>
                  {Object.entries(names).map(([k, v]) => (
                    <option key={k} value={k}>
                      {v}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Mode
                <select
                  aria-label="Usage mode"
                  value={filters.mode}
                  onChange={(e) => change("mode", e.target.value)}
                >
                  <option value="all">All modes</option>
                  <option value="chat">Chat mode</option>
                  <option value="work">Work mode</option>
                </select>
              </label>
              <button
                className="button small"
                aria-expanded={advanced}
                onClick={() => setAdvanced(!advanced)}
              >
                <Icon name="settings" size={14} />
                More filters
              </button>
            </div>
            <a
              className="button small"
              href={`${owner ? "/api/admin/users/" + owner : global ? "/api/admin" : "/api"}/usage/export.csv?${params}`}
              aria-disabled={!!dateError}
              onClick={(e) => {
                if (dateError) e.preventDefault();
              }}
              download
            >
              <Icon name="down" size={14} />
              Export filtered CSV
            </a>
          </div>
          {filters.days === "custom" && (
            <div className="usage-advanced">
              <label>
                From (UTC)
                <input
                  aria-label="Usage start date"
                  type="date"
                  value={filters.start_date}
                  onChange={(e) => change("start_date", e.target.value)}
                />
              </label>
              <label>
                Through (UTC)
                <input
                  aria-label="Usage end date"
                  type="date"
                  value={filters.end_date}
                  onChange={(e) => change("end_date", e.target.value)}
                />
              </label>
            </div>
          )}
          {dateError && (
            <p className="usage-date-hint" role="status">
              {dateError}
            </p>
          )}
          {advanced && (
            <div className="usage-advanced">
              <label>
                Model
                <select
                  aria-label="Usage model"
                  value={filters.model}
                  onChange={(e) => change("model", e.target.value)}
                >
                  <option value="all">All models</option>
                  {data?.facets?.models.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Model publisher
                <select
                  aria-label="Usage publisher"
                  value={filters.provider}
                  onChange={(e) => change("provider", e.target.value)}
                >
                  <option value="all">All publishers</option>
                  {data?.facets?.providers.map((p) => (
                    <option key={p} value={p}>
                      {p}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Conversation ID
                <input
                  value={filters.task}
                  onChange={(e) => change("task", e.target.value)}
                />
              </label>
              <label>
                Minimum tokens
                <input
                  type="number"
                  min="0"
                  step="1"
                  value={filters.min_tokens}
                  onChange={(e) => change("min_tokens", e.target.value)}
                />
              </label>
              <label>
                Maximum tokens
                <input
                  type="number"
                  min="0"
                  step="1"
                  value={filters.max_tokens}
                  onChange={(e) => change("max_tokens", e.target.value)}
                />
              </label>
              <label>
                Find activity
                <input
                  type="search"
                  aria-label="Search usage"
                  placeholder="Conversation or operation ID"
                  value={filters.query}
                  onChange={(e) => change("query", e.target.value)}
                />
              </label>
              <label>
                Status
                <select
                  aria-label="Usage status"
                  value={filters.status}
                  onChange={(e) => change("status", e.target.value)}
                >
                  <option value="all">All statuses</option>
                  <option value="settled">Settled</option>
                  <option value="reserved">In progress</option>
                  <option value="pending">Pending</option>
                  <option value="provisional">Provisional</option>
                </select>
              </label>
              <label>
                Minimum cost ($)
                <input
                  type="number"
                  aria-label="Minimum cost"
                  min="0"
                  step="any"
                  value={filters.min_charge}
                  onChange={(e) => change("min_charge", e.target.value)}
                />
              </label>
              <label>
                Maximum cost ($)
                <input
                  type="number"
                  aria-label="Maximum cost"
                  min="0"
                  step="any"
                  value={filters.max_charge}
                  onChange={(e) => change("max_charge", e.target.value)}
                />
              </label>
              <button
                className="button small"
                onClick={() => {
                  setFilters(defaults);
                  setOffset(0);
                }}
              >
                Reset filters
              </button>
            </div>
          )}
        </div>
      )}
      {busy && !data && tab !== "pricing" && (
        <p className="usage-loading" role="status">
          Loading usage for your filters…
        </p>
      )}
      {tab === "overview" && data && (
        <>
          <div className="usage-stats">
            {[
              [
                "Recorded cost",
                money(data.totals.charge),
                "Recorded costs · selected filters",
              ],
              [
                "Next 30 days",
                forecast?.sample_count ? money(forecast.amount, 2) : "—",
                `Account-wide estimate · ${forecast?.observed_days || 0} days observed`,
              ],
              [
                "AI tokens",
                count(tokens),
                `${count(data.totals.cached_tokens)} cached · ${count(data.totals.reasoning_tokens)} reasoning`,
              ],
              [
                "Workspace time",
                `${(data.totals.seconds / 60).toFixed(1)} min`,
                "Browser and coding time · selected filters",
              ],
            ].map(([label, value, note]) => (
              <section key={label}>
                <span>{label}</span>
                <strong>{value}</strong>
                <small>{note}</small>
              </section>
            ))}
          </div>
          <section className="usage-chart-card">
            <div className="usage-section-head">
              <div>
                <h2>
                  {chart === "daily" ? "Daily spend" : "Cumulative spend"}
                </h2>
                <p>
                  {focus
                    ? `${dayLabel(focus.day)} · ${money(chart === "daily" ? focus.charge : focus.cumulative)} · ${focus.requests} activities that day`
                    : "Recorded costs for your filters · UTC"}
                </p>
              </div>
              <div className="chart-switch">
                <button
                  aria-pressed={chart === "daily"}
                  onClick={() => {
                    setChart("daily");
                    setHover(null);
                  }}
                >
                  Daily
                </button>
                <button
                  aria-pressed={chart === "cumulative"}
                  onClick={() => {
                    setChart("cumulative");
                    setHover(null);
                  }}
                >
                  Cumulative
                </button>
              </div>
            </div>
            <div
              className="usage-chart"
              role="group"
              aria-label={`${chart} spend chart`}
            >
              {rows.map((r, i) => (
                <button
                  key={r.day}
                  aria-label={`${dayLabel(r.day)}: ${money(chart === "daily" ? r.charge : r.cumulative)}, ${r.requests} activities`}
                  onFocus={() => setHover(i)}
                  onBlur={() => setHover(null)}
                  onMouseEnter={() => setHover(i)}
                  onMouseLeave={() => setHover(null)}
                >
                  <span
                    style={{
                      height: `${(chart === "daily" ? r.charge : r.cumulative) ? Math.max(2, ((chart === "daily" ? r.charge : r.cumulative) / max) * 100) : 1}%`,
                    }}
                  />
                </button>
              ))}
            </div>
            <div className="usage-axis">
              <span>{rows.length ? dayLabel(rows[0].day) : ""}</span>
              <span>
                {data.totals.charge
                  ? `Peak ${chart === "daily" ? "day" : "total"}: ${money(max)}`
                  : "No recorded costs in this period"}
              </span>
              <span>{rows.length ? dayLabel(rows.at(-1).day) : ""}</span>
            </div>
          </section>
          <UsageInsights
            data={data}
            onFilter={(key, value) => {
              change(key, value);
              setAdvanced(true);
            }}
          />
          <div className="usage-two">
            <section className="usage-panel">
              <p className="usage-caption">
                Select a slice or service to explore its recorded costs.
              </p>
              <Pie
                title="Cost by service"
                rows={data.breakdown.map((r) => ({
                  id: r.service + ":" + r.mode,
                  label: label(r),
                  value: r.charge,
                }))}
                valueLabel={money}
                onSelect={(id) => {
                  const r = data.breakdown.find(
                    (r) => r.service + ":" + r.mode === id,
                  );
                  if (!r) return;
                  setFilters((f) => ({
                    ...f,
                    service: r.service,
                    mode: r.service === "model" ? r.mode : f.mode,
                  }));
                  setOffset(0);
                  setTab("activity");
                }}
              />
            </section>
            <section className="usage-panel">
              <h2>Plan ahead</h2>
              <p className="usage-caption">
                Based on all settled usage over the last 30 days, or since
                signup if newer.
              </p>
              <div className="forecast-number">
                {forecast?.sample_count
                  ? money(forecast.amount, 2)
                  : "Not enough activity yet"}
                <small>projected for the next 30 days</small>
              </div>
              <div className="forecast-detail">
                <span>Average daily spend</span>
                <strong>{money(forecast?.daily_average || 0)}</strong>
              </div>
              <p className="usage-explainer">
                An estimate, not a charge. Assumes your daily usage stays
                similar. Pending charges are excluded.{" "}
                {forecast?.observed_days < 7
                  ? "Early estimate: less than a week of account history."
                  : ""}
              </p>
            </section>
          </div>
          <div className="usage-two">
            <section className="usage-panel">
              <h2>AI token mix</h2>
              <p className="usage-caption">
                Input and output volume for your filters. Token volume is not
                the same as spending.
              </p>
              <div
                className="token-mix"
                role="img"
                aria-label={`${count(data.totals.input_tokens)} input tokens and ${count(data.totals.output_tokens)} output tokens`}
              >
                <span
                  style={{
                    width: `${tokens ? (data.totals.input_tokens / tokens) * 100 : 0}%`,
                  }}
                />
                <i
                  style={{
                    width: `${tokens ? (data.totals.output_tokens / tokens) * 100 : 0}%`,
                  }}
                />
              </div>
              <div className="token-legend">
                <span>
                  Input <b>{count(data.totals.input_tokens)}</b>
                </span>
                <span>
                  Output <b>{count(data.totals.output_tokens)}</b>
                </span>
              </div>
              <p className="usage-explainer">
                Cached tokens are included in input; reasoning tokens are
                included in output where reported.
              </p>
            </section>
            <section className="usage-panel">
              <h2>How costs are recorded</h2>
              <p className="usage-caption">
                Provider usage is recorded at cost, without an OwnCMD
                multiplier. Your provider invoice remains authoritative.
              </p>
              <div className="usage-explainer">
                <strong>Pending and provisional usage</strong>
                <p>
                  Some providers report final costs later. Pending estimates and
                  provisional entries can change after reconciliation. These
                  estimates are not credit reservations.
                </p>
              </div>
              <div className="usage-explainer">
                <strong>Your infrastructure</strong>
                <p>
                  Browser and coding time is always tracked. Local runtime cost
                  defaults to zero; any configured rate is your operator’s
                  infrastructure estimate, not an OwnCMD fee.
                </p>
              </div>
            </section>
          </div>
        </>
      )}
      {tab === "activity" && (
        <section className="usage-panel usage-activity" aria-busy={busy}>
          <div className="usage-section-head">
            <div>
              <h2>Activity ledger</h2>
              <p>Every operation, with a record you can inspect.</p>
            </div>
            <label className="usage-sort">
              Sort
              <select
                aria-label="Sort usage"
                value={filters.sort}
                onChange={(e) => change("sort", e.target.value)}
              >
                <option value="newest">Newest first</option>
                <option value="oldest">Oldest first</option>
                <option value="highest">Highest cost</option>
                <option value="lowest">Lowest cost</option>
              </select>
            </label>
          </div>
          <div className="usage-table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Activity / time</th>
                  <th>Conversation</th>
                  <th>Usage</th>
                  <th>Cost (USD)</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {data?.rows.map((r) => (
                  <tr key={r.id}>
                    <td>
                      <strong>{label(r)}</strong>
                      {r.model && <small>{r.model}</small>}
                      <small>
                        {new Date(r.created * 1000).toLocaleString()}
                      </small>
                      <details>
                        <summary>Details</summary>
                        <p>
                          Operation: {r.id}
                          <br />
                          Conversation ID: {r.task}
                          <br />
                          Initial estimate: {money(r.reserved, 9)}
                          <br />
                          Input: {count(r.metadata.prompt_tokens)} · Output:{" "}
                          {count(r.metadata.completion_tokens)}
                          <br />
                          Cached: {count(r.metadata.cached_tokens)} · Reasoning:{" "}
                          {count(r.metadata.reasoning_tokens)}
                        </p>
                      </details>
                    </td>
                    <td>
                      {r.conversation === "Deleted conversation" ? (
                        <span className="muted">Deleted conversation</span>
                      ) : (
                        <a href={`#chat/${r.task}`}>{r.conversation}</a>
                      )}
                    </td>
                    <td>
                      {r.service === "browser" || r.service === "code"
                        ? `${Number(r.metadata.seconds || 0).toFixed(2)} s`
                        : r.service === "search"
                          ? `${r.metadata.result_count || 0} results`
                          : `${count((r.metadata.prompt_tokens || 0) + (r.metadata.completion_tokens || 0))} tokens`}
                    </td>
                    <td>
                      <strong>{money(r.charge, 9)}</strong>
                    </td>
                    <td>
                      <span className={"usage-status " + r.status}>
                        {r.status === "reserved"
                          ? "In progress"
                          : r.status === "pending"
                            ? "Pending"
                            : r.metadata.provisional
                              ? "Provisional"
                              : "Settled"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {data && !data.rows.length && (
              <div className="dev-empty">
                <Icon name="activity" size={28} />
                <h3>No matching activity</h3>
                <p>Try another date range or reset your filters.</p>
              </div>
            )}
          </div>
          <div className="usage-pagination">
            <label>
              Rows per page
              <select
                aria-label="Rows per page"
                value={limit}
                onChange={(e) => {
                  setLimit(Number(e.target.value));
                  setOffset(0);
                }}
              >
                {[10, 25, 50, 100].map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </label>
            <span>
              {data?.total
                ? `${data.offset + 1}–${Math.min(data.offset + limit, data.total)} of ${data.total}`
                : "0 records"}
            </span>
            <div>
              <button
                className="button small"
                aria-label="First page"
                disabled={page <= 1 || busy}
                onClick={() => setOffset(0)}
              >
                First
              </button>
              <button
                className="button small"
                disabled={page <= 1 || busy}
                onClick={() => setOffset(Math.max(0, (page - 2) * limit))}
              >
                Previous
              </button>
              <span>
                Page {page} of {pages}
              </span>
              <button
                className="button small"
                disabled={page >= pages || busy}
                onClick={() => setOffset(page * limit)}
              >
                Next
              </button>
              <button
                className="button small"
                aria-label="Last page"
                disabled={page >= pages || busy}
                onClick={() => setOffset((pages - 1) * limit)}
              >
                Last
              </button>
            </div>
          </div>
        </section>
      )}
      {tab === "pricing" && (
        <>
          <section className="usage-panel">
            <h2>Provider rates, without markup.</h2>
            <p>
              All values are in USD. Pay your providers directly; OwnCMD
              Community does not collect payment.
            </p>
            <div className="usage-rate-grid">
              <article>
                <Icon name="globe" />
                <h3>Web search</h3>
                <strong>
                  Provider-reported <small>/ request</small>
                </strong>
                <p>{pricing?.search?.basis}</p>
              </article>
              <article>
                <Icon name="browser" />
                <h3>Browser workspace</h3>
                <strong>
                  {pricing ? money(pricing.browser_per_hour) : "…"}{" "}
                  <small>/ hour</small>
                </strong>
                <p>
                  Optional local infrastructure estimate. Defaults to zero;
                  browser time is still recorded.
                </p>
              </article>
              <article>
                <Icon name="code" />
                <h3>Coding workspace</h3>
                <strong>
                  {pricing ? money(pricing.code_per_hour) : "…"}{" "}
                  <small>/ hour</small>
                </strong>
                <p>
                  Optional local infrastructure estimate. Defaults to zero;
                  includes running apps, installs and previews.
                </p>
              </article>
            </div>
            <p className="usage-explainer">{pricing?.runtime_basis}</p>
          </section>
          {
            <section className="usage-panel">
              <h2>AI usage rates</h2>
              <p>
                Token rates per million tokens. Cached input and additional
                processing are included where applicable.
              </p>
              {pricing?.models?.length ? (
                <div className="usage-table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>Mode / model</th>
                        <th>Input / 1M</th>
                        <th>Output / 1M</th>
                        <th>Cached input / 1M</th>
                        <th>Cache write / 1M</th>
                        <th>Image / request extras</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pricing.models.map((m) => (
                        <tr key={m.mode + "-" + m.model}>
                          <td>
                            <strong>
                              {m.mode === "work" ? "Work mode" : "Chat mode"}
                            </strong>
                            <small style={{ display: "block" }}>
                              {m.name}
                              {m.auto ? " · Auto default" : ""}
                            </small>
                          </td>
                          <td>
                            {m.pricing.prompt != null
                              ? money(m.pricing.prompt * 1e6)
                              : "—"}
                          </td>
                          <td>
                            {m.pricing.completion != null
                              ? money(m.pricing.completion * 1e6)
                              : "—"}
                          </td>
                          <td>
                            {m.pricing.input_cache_read != null
                              ? money(m.pricing.input_cache_read * 1e6)
                              : "Standard input rate"}
                          </td>
                          <td>
                            {m.pricing.input_cache_write != null
                              ? money(m.pricing.input_cache_write * 1e6)
                              : "Standard input rate"}
                          </td>
                          <td>
                            {money(m.pricing.image || 0)} /{" "}
                            {money(m.pricing.request || 0)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="usage-explainer">
                  {pricingError
                    ? "Unable to load provider rates: " + pricingError
                    : "The AI rate card is updating."}{" "}
                  <button
                    className="button small"
                    onClick={() =>
                      api("pricing")
                        .then((result) => {
                          setPricing(result);
                          setPricingError("");
                        })
                        .catch((e) => {
                          setPricingError(e.message);
                          notify(e.message);
                        })
                    }
                  >
                    Refresh rates
                  </button>
                </p>
              )}
              {pricing?.rates_updated && (
                <p className="usage-caption">
                  Rates last updated{" "}
                  {new Date(pricing.rates_updated * 1000).toLocaleString()}.
                </p>
              )}
            </section>
          }
          <section className="usage-panel">
            <h2>Included with OwnCMD</h2>
            <p>
              {pricing?.policy ||
                "No OwnCMD fees. You pay your infrastructure and provider accounts directly."}
            </p>
          </section>
        </>
      )}
    </div>
  );
}
