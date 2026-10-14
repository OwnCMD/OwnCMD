"use client";
import { useState } from "react";
export const chartColors = [
  "#6875f5",
  "#16b8a6",
  "#e8a23c",
  "#de6aa5",
  "#4698df",
  "#9a7bd5",
  "#72ac54",
  "#db7853",
];
export const humanLabel = (s) =>
  String(s || "Unknown")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
const count = (n) => Number(n || 0).toLocaleString();
export function Donut({ title, rows = [], onSelect, valueLabel = count }) {
  const data = rows.map((r) => ({
      ...r,
      value: Math.max(0, Number(r.value) || 0),
    })),
    total = data.reduce((n, r) => n + r.value, 0);
  let offset = 0;
  return (
    <section className="dashboard-chart">
      <h3>{title}</h3>
      <div className="chart-distribution">
        <div className="chart-ring">
          <svg
            viewBox="0 0 120 120"
            role="img"
            aria-label={`${title}: ${valueLabel(total)} total`}
          >
            <circle
              cx="60"
              cy="60"
              r="45"
              fill="none"
              stroke="var(--border)"
              strokeWidth="14"
            />
            {total > 0 &&
              data.map((r, i) => {
                const n = (r.value / total) * 100,
                  start = offset;
                offset += n;
                return (
                  <circle
                    key={r.label}
                    cx="60"
                    cy="60"
                    r="45"
                    pathLength="100"
                    fill="none"
                    stroke={chartColors[i % chartColors.length]}
                    strokeWidth="14"
                    strokeDasharray={`${n} ${100 - n}`}
                    strokeDashoffset={-start}
                    transform="rotate(-90 60 60)"
                  >
                    <title>
                      {humanLabel(r.label)}: {valueLabel(r.value)} (
                      {n.toFixed(1)}%)
                    </title>
                  </circle>
                );
              })}
          </svg>
          <div>
            <strong>{valueLabel(total)}</strong>
            <small>Total</small>
          </div>
        </div>
        <div className="chart-legend">
          {data.map((r, i) => (
            <button
              key={r.label}
              className="chart-legend-row"
              disabled={!onSelect}
              onClick={() => onSelect?.(r.label)}
            >
              <i style={{ background: chartColors[i % chartColors.length] }} />
              <span>{humanLabel(r.label)}</span>
              <strong>{valueLabel(r.value)}</strong>
              <small>{total ? ((r.value / total) * 100).toFixed(0) : 0}%</small>
            </button>
          ))}
          {!data.length && <p className="muted">No data in this view.</p>}
        </div>
      </div>
    </section>
  );
}
export function Trend({
  title,
  rows = [],
  series = [{ key: "value", name: "Activity" }],
  percent = false,
}) {
  const [hover, setHover] = useState(null),
    width = 700,
    height = 170;
  const max = percent
      ? 100
      : Math.max(
          1,
          ...rows.flatMap((r) => series.map((s) => Number(r[s.key]) || 0)),
        ),
    x = (i) => 36 + (i * (width - 48)) / Math.max(1, rows.length - 1),
    y = (n) => height - 20 - (n / max) * (height - 40);
  return (
    <section className="dashboard-chart chart-trend">
      <div className="chart-heading">
        <h3>{title}</h3>
        <div className="chart-keys">
          {series.map((s, i) => (
            <span key={s.key}>
              <i style={{ background: chartColors[i] }} />
              {s.name}
            </span>
          ))}
        </div>
      </div>
      {rows.length ? (
        <>
          <svg
            viewBox={`0 0 ${width} ${height}`}
            role="img"
            aria-label={title}
            onPointerLeave={() => setHover(null)}
            onPointerMove={(e) => {
              const rect = e.currentTarget.getBoundingClientRect();
              setHover(
                Math.max(
                  0,
                  Math.min(
                    rows.length - 1,
                    Math.round(
                      ((((e.clientX - rect.left) / rect.width) * width - 36) /
                        (width - 48)) *
                        (rows.length - 1),
                    ),
                  ),
                ),
              );
            }}
          >
            {[0, 0.5, 1].map((n) => (
              <g key={n}>
                <line
                  x1="36"
                  x2={width - 12}
                  y1={y(n * max)}
                  y2={y(n * max)}
                  stroke="var(--border)"
                  strokeDasharray="3 5"
                />
                <text
                  x="28"
                  y={y(n * max) + 4}
                  textAnchor="end"
                  fill="var(--muted)"
                  fontSize="10"
                >
                  {Math.round(n * max)}
                  {percent ? "%" : ""}
                </text>
              </g>
            ))}
            {series.map((s, i) => {
              let active = false;
              const d = rows
                .map((r, index) => {
                  if (r[s.key] == null) {
                    active = false;
                    return "";
                  }
                  const segment = `${active ? "L" : "M"}${x(index)},${y(r[s.key])}`;
                  active = true;
                  return segment;
                })
                .join(" ");
              return (
                <g key={s.key}>
                  <path
                    d={d}
                    fill="none"
                    stroke={chartColors[i]}
                    strokeWidth="2.5"
                    strokeLinecap="round"
                  />
                  {rows.length === 1 && rows[0][s.key] != null && (
                    <circle
                      cx={x(0)}
                      cy={y(rows[0][s.key])}
                      r="3"
                      fill={chartColors[i]}
                    />
                  )}
                </g>
              );
            })}
            {hover != null && (
              <line
                x1={x(hover)}
                x2={x(hover)}
                y1="12"
                y2={height - 20}
                stroke="var(--muted)"
                strokeDasharray="3 4"
              />
            )}
          </svg>
          <div className="chart-axis">
            <span>{rows[0].label}</span>
            <span>{rows.at(-1).label}</span>
          </div>
          {hover != null && rows[hover] && (
            <div className="chart-tooltip" role="status">
              <strong>{rows[hover].label}</strong>
              {series.map((s) => (
                <span key={s.key}>
                  {s.name}:{" "}
                  {rows[hover][s.key] == null
                    ? "Unavailable"
                    : count(rows[hover][s.key]) + (percent ? "%" : "")}
                </span>
              ))}
            </div>
          )}
        </>
      ) : (
        <div className="chart-empty">
          No samples yet. Live history builds as data arrives.
        </div>
      )}
      <details className="chart-data">
        <summary>View chart data</summary>
        <div className="usage-table-scroll">
          <table>
            <thead>
              <tr>
                <th>Time</th>
                {series.map((s) => (
                  <th key={s.key}>{s.name}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  <td>{r.label}</td>
                  {series.map((s) => (
                    <td key={s.key}>
                      {r[s.key] == null ? "Unavailable" : count(r[s.key])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  );
}
export function Gauge({ title, percent, detail, icon }) {
  const available = Number.isFinite(percent),
    value = available ? Math.min(100, Math.max(0, percent)) : 0,
    color = value >= 90 ? "#e66969" : value >= 75 ? "#e8a23c" : "#16b8a6";
  return (
    <section className="health-gauge">
      <div className="health-ring">
        <svg
          viewBox="0 0 100 100"
          role="img"
          aria-label={`${title}: ${available ? value.toFixed(1) + "%" : "unavailable"}`}
        >
          <circle
            cx="50"
            cy="50"
            r="40"
            fill="none"
            stroke="var(--border)"
            strokeWidth="8"
          />
          <circle
            cx="50"
            cy="50"
            r="40"
            pathLength="100"
            fill="none"
            stroke={color}
            strokeWidth="8"
            strokeLinecap="round"
            strokeDasharray={`${value} ${100 - value}`}
            transform="rotate(-90 50 50)"
          />
        </svg>
        <strong>{available ? Math.round(value) + "%" : "—"}</strong>
      </div>
      <div>
        <h3>{title}</h3>
        <p>{detail || "Waiting for a host sample"}</p>
        <small>
          {available
            ? value >= 90
              ? "High utilization"
              : value >= 75
                ? "Elevated utilization"
                : "Within capacity"
            : "Unavailable"}
        </small>
      </div>
    </section>
  );
}

export function Pie({ title, rows = [], onSelect, valueLabel = count }) {
  const data = rows.map((r) => ({
      ...r,
      value: Math.max(0, Number(r.value) || 0),
    })),
    total = data.reduce((n, r) => n + r.value, 0);
  let angle = -Math.PI / 2;
  return (
    <section className="dashboard-chart credit-pie">
      <h3>{title}</h3>
      <div className="chart-distribution">
        <div className="pie-graphic">
          <svg
            viewBox="0 0 200 200"
            role="img"
            aria-label={`${title}: ${valueLabel(total)} total`}
          >
            <circle cx="100" cy="100" r="92" fill="var(--border)" />
            {total > 0 &&
              data.map((r, i) => {
                const start = angle,
                  sweep = (r.value / total) * Math.PI * 2;
                angle += sweep;
                const x = (a) => 100 + 92 * Math.cos(a),
                  y = (a) => 100 + 92 * Math.sin(a);
                if (!r.value) return null;
                const d =
                  sweep >= Math.PI * 2 - 0.00001
                    ? "M100 8 A92 92 0 1 1 100 192 A92 92 0 1 1 100 8 Z"
                    : `M100 100 L${x(start)} ${y(start)} A92 92 0 ${sweep > Math.PI ? 1 : 0} 1 ${x(angle)} ${y(angle)} Z`;
                return (
                  <path
                    key={r.id || r.label}
                    d={d}
                    fill={chartColors[i % chartColors.length]}
                    stroke="var(--surface)"
                    strokeWidth="2"
                    onClick={() => onSelect?.(r.id || r.label)}
                  >
                    <title>
                      {r.label}: {valueLabel(r.value)} (
                      {((r.value / total) * 100).toFixed(1)}%)
                    </title>
                  </path>
                );
              })}
          </svg>
          <strong>{valueLabel(total)}</strong>
          <small>Recorded provider cost</small>
        </div>
        <div className="chart-legend">
          {data.map((r, i) => (
            <button
              key={r.id || r.label}
              className="chart-legend-row"
              disabled={!onSelect}
              onClick={() => onSelect?.(r.id || r.label)}
            >
              <i style={{ background: chartColors[i % chartColors.length] }} />
              <span>{r.label}</span>
              <strong>{valueLabel(r.value)}</strong>
              <small>{total ? ((r.value / total) * 100).toFixed(1) : 0}%</small>
            </button>
          ))}
          {!data.length && (
            <p className="muted">No usage matches these filters.</p>
          )}
        </div>
      </div>
    </section>
  );
}
