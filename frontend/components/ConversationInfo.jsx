"use client";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { IconButton, Modal, Icon } from "./UI";
import { Donut, humanLabel } from "./DashboardCharts";
const serviceName = (s) =>
  ({
    model: "AI responses",
    search: "Web search & page reads",
    browser: "Browser workspace",
    code: "Coding sandbox",
    title: "Conversation titles",
    skill_embedding: "Skill embeddings",
    skill_rerank: "Skill matching",
    skill_generation: "Skill drafting",
    knowledge_embedding: "Knowledge search & indexing",
    knowledge_generation: "Knowledge drafting",
  })[s] || humanLabel(s);
const money = (n) => "$" + Number(n || 0).toFixed(6),
  count = (n) => Number(n || 0).toLocaleString();
function UsageDialog({ task, onClose, onChanged }) {
  const [data, setData] = useState(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [revision, setRevision] = useState(0);
  useEffect(() => {
    let alive = true,
      timer;
    async function load() {
      try {
        const d = await api(`tasks/${task.id}/usage`);
        if (alive) {
          setData(d);
          setError("");
        }
      } catch (e) {
        if (alive) setError(e.message);
      } finally {
        if (alive) timer = setTimeout(load, 5000);
      }
    }
    load();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [task.id, revision]);
  async function action(kind) {
    setBusy(true);
    setError("");
    try {
      const r =
        kind === "pause"
          ? await api(`tasks/${task.id}/command`, { action: "pause" })
          : await api(`tasks/${task.id}/runtime-stop`, { kind });
      if (r.session_warning) setError(r.session_warning);
      setRevision((v) => v + 1);
      onChanged?.(kind);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal title="Conversation information" onClose={onClose} wide>
      {error && <p role="alert">{error}</p>}
      {!data ? (
        <p>Loading usage…</p>
      ) : (
        <div className="conversation-info">
          <p>
            {data.mode === "work" ? "Work" : "Chat"} ·{" "}
            {data.model_choice === "auto"
              ? "Auto model selection"
              : data.model_choice}
          </p>
          <p className="muted">
            Last execution model: {data.selected_model || "No model run yet"}.
            All models used appear below.
          </p>
          <div className="info-metrics">
            <div>
              <small>Input tokens</small>
              <strong>{count(data.totals.input_tokens)}</strong>
            </div>
            <div>
              <small>Output tokens</small>
              <strong>{count(data.totals.output_tokens)}</strong>
            </div>
            <div>
              <small>Cost · USD</small>
              <strong>{money(data.totals.charge)}</strong>
            </div>
            <div>
              <small>Pending estimate · USD</small>
              <strong>{money(data.totals.reserved)}</strong>
            </div>
          </div>
          <p className="muted">
            All-time conversation usage, including AI responses, web search,
            page reads, conversation titles, tools and any configured
            infrastructure estimates. No OwnCMD markup is applied. Cached input:{" "}
            {count(data.totals.cached_tokens)} · Reasoning output:{" "}
            {count(data.totals.reasoning_tokens)}. These are subsets of the
            token totals. Pending estimates are separate from recorded costs.
          </p>
          <Donut
            title="Cost by service"
            rows={data.services.map((r) => ({
              label: serviceName(r.service),
              value: r.charge,
            }))}
            valueLabel={money}
          />
          <div className="usage-table-wrap">
            <table>
              <caption>All service costs · USD</caption>
              <thead>
                <tr>
                  <th>Service</th>
                  <th>Activities</th>
                  <th>Cost</th>
                  <th>Pending estimate</th>
                </tr>
              </thead>
              <tbody>
                {data.services.map((r) => (
                  <tr key={r.service}>
                    <td>
                      {serviceName(r.service)}
                      {r.seconds > 0 && (
                        <small className="service-duration">
                          {(r.seconds / 60).toFixed(2)} minutes
                        </small>
                      )}
                    </td>
                    <td data-label="Activities">{count(r.requests)}</td>
                    <td data-label="Cost">{money(r.charge)}</td>
                    <td data-label="Pending estimate">{money(r.reserved)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!data.services.length && <p>No provider costs recorded yet.</p>}
          </div>
          <details className="info-charge-details">
            <summary>Cost status details</summary>
            <p className="muted">
              Every recorded service is included. Pending costs may change when
              providers settle; estimates are not additional costs.
            </p>
            <div className="usage-table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Service / model</th>
                    <th>Status</th>
                    <th>Activities</th>
                    <th>Provider cost USD</th>
                  </tr>
                </thead>
                <tbody>
                  {data.details?.map((r, i) => (
                    <tr key={i}>
                      <td>
                        {serviceName(r.service)}
                        <small className="service-duration">{r.model}</small>
                      </td>
                      <td data-label="Status">{humanLabel(r.status)}</td>
                      <td data-label="Activities">{count(r.requests)}</td>
                      <td data-label="Cost">{money(r.charge)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
          <div className="usage-table-wrap">
            <table>
              <caption>Models used in this conversation</caption>
              <thead>
                <tr>
                  <th>Model</th>
                  <th>Input</th>
                  <th>Output</th>
                  <th>Provider cost USD</th>
                </tr>
              </thead>
              <tbody>
                {data.models.map((m) => (
                  <tr key={m.model}>
                    <td>{m.model}</td>
                    <td data-label="Input">{count(m.input_tokens)}</td>
                    <td data-label="Output">{count(m.output_tokens)}</td>
                    <td data-label="Cost">{money(m.charge)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!data.models.length && <p>No recorded model usage yet.</p>}
          </div>
          {data.mode === "work" && (
            <section className="info-resources">
              <h3>Live workspaces</h3>
              {!data.runtime_available ? (
                <p role="status">{data.runtime_message}</p>
              ) : (
                data.runtimes?.map((r) => (
                  <div key={r.kind} className="info-resource">
                    <Icon name={r.kind === "code" ? "code" : "browser"} />
                    <span>
                      <strong>
                        {r.kind === "code"
                          ? "Coding sandbox"
                          : "Browser workspace"}
                      </strong>
                      <small>
                        {humanLabel(r.status)} ·{" "}
                        {r.billing_active
                          ? "Runtime active"
                          : "Runtime inactive"}
                      </small>
                    </span>
                    <button
                      className="button small"
                      disabled={
                        busy ||
                        r.status !== "running" ||
                        data.busy ||
                        ["queued", "running"].includes(data.status)
                      }
                      onClick={() => action(r.kind)}
                    >
                      Stop {r.kind === "code" ? "sandbox" : "browser"}
                    </button>
                  </div>
                ))
              )}
              {["queued", "running"].includes(data.status) && (
                <button
                  className="button"
                  disabled={busy}
                  onClick={() => action("pause")}
                >
                  Pause work to stop a workspace
                </button>
              )}
              {data.busy && (
                <p>
                  Waiting for the current action to finish. Stop controls become
                  available afterward.
                </p>
              )}
              <p className="muted">
                Stopping saves the workspace and ends its runtime metering.
                Opening this panel does not keep a workspace alive.
              </p>
            </section>
          )}
        </div>
      )}
    </Modal>
  );
}
export function ConversationInfo({ task, onChanged }) {
  const [open, setOpen] = useState(false);
  useEffect(() => setOpen(false), [task.id]);
  return (
    <>
      <button
        type="button"
        className="button small conversation-info-button"
        aria-label="Conversation information"
        title="Usage, models and costs"
        onClick={() => setOpen(true)}
      >
        <Icon name="info" size={16} />
        <span>Usage</span>
      </button>
      {open && (
        <UsageDialog
          task={task}
          onClose={() => setOpen(false)}
          onChanged={onChanged}
        />
      )}
    </>
  );
}
