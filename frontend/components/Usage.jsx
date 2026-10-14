"use client";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { loadUsage } from "../lib/usage-request.mjs";
import { Pie } from "./DashboardCharts";
const money = (n) =>
  n == null
    ? "Pending"
    : new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
        maximumFractionDigits: 6,
      }).format(n);
export function Usage() {
  const [data, setData] = useState(null),
    [days, setDays] = useState("30"),
    [mode, setMode] = useState("all"),
    [offset, setOffset] = useState(0),
    [error, setError] = useState("");
  const query = new URLSearchParams({
    days,
    mode,
    offset: String(offset),
    limit: "50",
  }).toString();
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    loadUsage(
      query,
      (path, signal) => api(path, undefined, undefined, signal),
      { signal: controller.signal },
    )
      .then(setData)
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      });
    return () => controller.abort();
  }, [query]);
  return (
    <section className="community-page">
      <span className="eyebrow">TRANSPARENT PROVIDER COSTS</span>
      <h1>Usage</h1>
      <p>
        Tokens, requests and provider cost estimates. No credits, top-ups or
        OwnCMD markup. Your provider invoice is authoritative; pending costs may
        settle later. Local runtime cost defaults to zero.
      </p>
      <div className="community-tabs">
        <select
          aria-label="Date range"
          value={days}
          onChange={(e) => {
            setDays(e.target.value);
            setOffset(0);
          }}
        >
          {[7, 30, 90, 365].map((n) => (
            <option key={n} value={n}>
              Last {n} days
            </option>
          ))}
        </select>
        <select
          aria-label="Mode"
          value={mode}
          onChange={(e) => {
            setMode(e.target.value);
            setOffset(0);
          }}
        >
          <option value="all">All modes</option>
          <option value="chat">Chat</option>
          <option value="work">Work</option>
        </select>
        <a className="button" href={"/api/usage/export.csv?" + query}>
          Export CSV
        </a>
      </div>
      {error && <p role="alert">{error}</p>}
      {data && (
        <>
          <div className="community-stats">
            {[
              ["Provider cost", money(data.totals.charge)],
              ["Requests", data.totals.requests],
              ["Input tokens", data.totals.input_tokens],
              ["Output tokens", data.totals.output_tokens],
            ].map(([label, value]) => (
              <div className="community-card" key={label}>
                <small>{label}</small>
                <h2>{value}</h2>
              </div>
            ))}
          </div>
          <Pie
            title="Cost by service"
            rows={data.breakdown.map((r) => ({
              id: r.service + ":" + r.mode,
              label: r.service + " · " + r.mode,
              value: r.charge,
            }))}
            valueLabel={money}
          />
          <div className="community-table">
            <table>
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Conversation</th>
                  <th>Service / model</th>
                  <th>Tokens in / out</th>
                  <th>Cost (USD)</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r) => (
                  <tr key={r.id}>
                    <td>{new Date(r.created * 1000).toLocaleString()}</td>
                    <td>{r.conversation}</td>
                    <td>
                      {r.service}
                      <small>{r.model}</small>
                    </td>
                    <td>
                      {r.metadata.prompt_tokens || 0} /{" "}
                      {r.metadata.completion_tokens || 0}
                    </td>
                    <td>
                      {money(r.charge)}
                      {r.metadata.provisional && " (estimated)"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="community-tabs">
            <button
              className="button"
              disabled={!offset}
              onClick={() => setOffset(Math.max(0, offset - 50))}
            >
              Previous
            </button>
            <span>{data.total} operations</span>
            <button
              className="button"
              disabled={offset + 50 >= data.total}
              onClick={() => setOffset(offset + 50)}
            >
              Next
            </button>
          </div>
        </>
      )}
    </section>
  );
}
