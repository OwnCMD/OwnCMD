"use client";
import { useState } from "react";
const colors = [
  "#6366f1",
  "#14b8a6",
  "#f59e0b",
  "#ec4899",
  "#3b82f6",
  "#a855f7",
  "#84cc16",
  "#f97316",
];
const money = (n) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 6,
  }).format(n || 0);
export function UsageInsights({ data, onFilter }) {
  const [group, setGroup] = useState("model"),
    [metric, setMetric] = useState("charge");
  const buckets = new Map();
  for (const row of data.models || []) {
    const key =
      group === "provider"
        ? row.model.split("/")[0]
        : group === "mode"
          ? row.mode
          : row.model;
    const b = buckets.get(key) || { key, charge: 0, requests: 0, tokens: 0 };
    b.charge += row.charge;
    b.requests += row.requests;
    b.tokens += row.input_tokens + row.output_tokens;
    buckets.set(key, b);
  }
  const all = [...buckets.values()].sort(
      (a, b) => b[metric] - a[metric] || a.key.localeCompare(b.key),
    ),
    total = all.reduce((sum, r) => sum + r[metric], 0);
  const rows =
    all.length > 8
      ? [
          ...all.slice(0, 7),
          {
            key: "Other models",
            other: true,
            [metric]: all.slice(7).reduce((sum, r) => sum + r[metric], 0),
          },
        ]
      : all;
  let offset = 0;
  return (
    <section className="usage-panel model-insights">
      <div className="usage-section-head">
        <div>
          <span className="eyebrow">MODEL INTELLIGENCE</span>
          <h2>Understand your AI usage</h2>
          <p>
            All matching model activity, including Skill models. Select a
            segment to filter.
          </p>
        </div>
        <div className="insight-controls">
          <label>
            Group by
            <select
              aria-label="Chart grouping"
              value={group}
              onChange={(e) => setGroup(e.target.value)}
            >
              <option value="model">Model</option>
              <option value="provider">Model publisher</option>
              <option value="mode">Mode</option>
            </select>
          </label>
          <label>
            Measure
            <select
              aria-label="Chart measure"
              value={metric}
              onChange={(e) => setMetric(e.target.value)}
            >
              <option value="charge">Spend</option>
              <option value="tokens">Tokens</option>
              <option value="requests">Requests</option>
            </select>
          </label>
        </div>
      </div>
      <div className="insight-distribution">
        <div className="donut-wrap">
          <svg
            viewBox="0 0 120 120"
            role="img"
            aria-label={`${group} share of ${metric}`}
          >
            <circle
              cx="60"
              cy="60"
              r="46"
              fill="none"
              stroke="var(--border)"
              strokeWidth="15"
            />
            {total > 0 &&
              rows.map((r, i) => {
                const share = (r[metric] / total) * 100,
                  start = offset;
                offset += share;
                return (
                  <circle
                    key={r.key}
                    cx="60"
                    cy="60"
                    r="46"
                    pathLength="100"
                    fill="none"
                    stroke={colors[i]}
                    strokeWidth="15"
                    strokeDasharray={`${share} ${100 - share}`}
                    strokeDashoffset={-start}
                    transform="rotate(-90 60 60)"
                  >
                    <title>
                      {r.key}: {share.toFixed(1)}%
                    </title>
                  </circle>
                );
              })}
          </svg>
          <div className="donut-center">
            <strong>
              {metric === "charge" ? money(total) : total.toLocaleString()}
            </strong>
            <small>{metric === "charge" ? "model spend" : metric}</small>
          </div>
        </div>
        <div className="donut-legend">
          {rows.map((r, i) => (
            <button
              key={r.key}
              disabled={r.other}
              onClick={() => onFilter(group, r.key)}
            >
              <i style={{ background: colors[i] }} />
              <span>{r.key}</span>
              <strong>
                {metric === "charge"
                  ? money(r[metric])
                  : r[metric].toLocaleString()}
                <small>
                  {total ? ((r[metric] / total) * 100).toFixed(1) : 0}%
                </small>
              </strong>
            </button>
          ))}
          {!rows.length && <p>No model usage matches these filters.</p>}
        </div>
      </div>
      <div className="usage-table-scroll">
        <table>
          <caption>Model comparison · current filters</caption>
          <thead>
            <tr>
              <th>Model / mode</th>
              <th>Requests</th>
              <th>Input</th>
              <th>Output</th>
              <th>Cached input</th>
              <th>Reasoning</th>
              <th>Spend</th>
              <th>Avg / request</th>
            </tr>
          </thead>
          <tbody>
            {(data.models || []).map((r) => (
              <tr key={r.model + ":" + r.mode}>
                <td>
                  <button
                    className="text-action"
                    onClick={() => onFilter("model", r.model)}
                  >
                    {r.model}
                  </button>
                  <small>{r.mode}</small>
                </td>
                <td>{r.requests.toLocaleString()}</td>
                <td>{r.input_tokens.toLocaleString()}</td>
                <td>{r.output_tokens.toLocaleString()}</td>
                <td>{r.cached_tokens.toLocaleString()}</td>
                <td>{r.reasoning_tokens.toLocaleString()}</td>
                <td>{money(r.charge)}</td>
                <td>{money(r.requests ? r.charge / r.requests : 0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="usage-caption">
        Model publisher is derived from the model ID; it is not the underlying
        inference host. Cached input and reasoning are subsets of input/output
        where reported.
      </p>
    </section>
  );
}
