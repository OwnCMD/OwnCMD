"use client";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { Icon, Modal } from "./UI";
import { Pagination } from "./Pagination";
const typeOf = (r) =>
  r.destination.includes("/")
    ? "Subnet"
    : r.destination.startsWith("*.")
      ? "Wildcard"
      : r.destination.includes(":") || /^[\d.]+$/.test(r.destination)
        ? "IP address"
        : "Domain";
const portLabel = (r) =>
  Array.isArray(r.ports) ? r.ports.join(", ") : "All TCP ports";
function RuleEditor({ rule, onClose, onSave }) {
  const [destination, setDestination] = useState(rule?.destination || ""),
    [ports, setPorts] = useState(
      rule
        ? Array.isArray(rule.ports)
          ? rule.ports.join(", ")
          : rule.ports
        : "443",
    ),
    [error, setError] = useState("");
  return (
    <Modal
      title={rule ? "Edit network rule" : "Add network rule"}
      onClose={onClose}
    >
      <form
        className="network-editor"
        onSubmit={(e) => {
          e.preventDefault();
          const values =
            ports.trim() === "*"
              ? "*"
              : ports.split(",").map((v) => Number(v.trim()));
          if (
            !destination.trim() ||
            destination.includes("://") ||
            destination.includes(" ")
          ) {
            setError(
              "Enter a domain, public IP or subnet without a URL scheme.",
            );
            return;
          }
          if (
            values !== "*" &&
            (!values.length ||
              values.length > 50 ||
              values.some((v) => !Number.isInteger(v) || v < 1 || v > 65535))
          ) {
            setError(
              "Use 1–50 comma-separated TCP ports from 1 to 65535, or *.",
            );
            return;
          }
          onSave({ destination: destination.trim(), ports: values });
        }}
      >
        <label>
          Destination
          <input
            autoFocus
            aria-label="Network destination"
            value={destination}
            onChange={(e) => setDestination(e.target.value)}
            placeholder="api.example.com"
            required
            maxLength={253}
          />
          <small>
            Domain, *.example.com, public IP, or CIDR subnet. A wildcard
            excludes the root domain.
          </small>
        </label>
        <label>
          TCP ports
          <input
            aria-label="Network ports"
            value={ports}
            onChange={(e) => setPorts(e.target.value)}
            placeholder="443, 80 or *"
            required
          />
          <small>Use * for all TCP ports. HTTPS commonly uses 443.</small>
        </label>
        {error && (
          <p role="alert" className="form-error">
            {error}
          </p>
        )}
        <div className="modal-actions">
          <button type="button" className="button" onClick={onClose}>
            Cancel
          </button>
          <button className="button primary">
            {rule ? "Update rule" : "Add rule"}
          </button>
        </div>
        <p className="muted">
          Rules remain a draft until you save the network policy. Public-address
          validation also runs when saving.
        </p>
      </form>
    </Modal>
  );
}
export function CodeNetworkPolicy({ owner = "global" }) {
  const [data, setData] = useState(null),
    [policy, setPolicy] = useState(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [saved, setSaved] = useState(""),
    [query, setQuery] = useState(""),
    [type, setType] = useState("all"),
    [offset, setOffset] = useState(0),
    [editing, setEditing] = useState(null),
    [view, setView] = useState("draft");
  const account = owner !== "global",
    dirty = policy && JSON.stringify(policy) !== JSON.stringify(data?.policy);
  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    setPolicy(null);
    setError("");
    setSaved("");
    setEditing(null);
    setOffset(0);
    api("admin/code-network/" + owner, undefined, undefined, controller.signal)
      .then((d) => {
        setData(d);
        setPolicy(d.policy);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      });
    return () => controller.abort();
  }, [owner]);
  async function save() {
    setBusy(true);
    setError("");
    setSaved("");
    try {
      const d = await api(
        "admin/code-network/" + owner,
        { policy, version: data.version },
        "PUT",
      );
      setData((old) => ({ ...old, ...d }));
      setPolicy(d.policy);
      setSaved(
        "Policy saved. New connections use it immediately; revoked connections close within about one second.",
      );
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  function change(p) {
    setSaved("");
    setPolicy(p);
  }
  const rows =
      (view === "effective" ? data?.effective?.rules : policy?.rules) || [],
    filtered = rows
      .map((r, i) => ({ ...r, index: i }))
      .filter(
        (r) =>
          (type === "all" || typeOf(r) === type) &&
          (r.destination + " " + portLabel(r))
            .toLowerCase()
            .includes(query.toLowerCase()),
      ),
    shown = filtered.slice(offset, offset + 10);
  return (
    <section className="admin-card network-policy">
      <div className="network-heading">
        <div className="network-heading-icon">
          <Icon name="globe" />
        </div>
        <div>
          <span className="eyebrow">
            {account ? "ACCOUNT POLICY" : "GLOBAL DEFAULTS"}
          </span>
          <h3>Coding sandbox internet</h3>
          <p>Control public destinations without restarting workspaces.</p>
        </div>
        <span className={"network-state " + (dirty ? "is-draft" : "")}>
          {dirty ? "Unsaved changes" : "Saved policy"}
        </span>
      </div>
      {error && (
        <p role="alert" className="form-error">
          {error}
        </p>
      )}
      {!policy && !error && <p>Loading network policy…</p>}
      {policy && (
        <>
          <fieldset disabled={busy} className="network-fieldset">
            {account && (
              <div className="network-access-options">
                <label>
                  <input
                    type="checkbox"
                    checked={policy.unrestricted}
                    onChange={(e) =>
                      change({ ...policy, unrestricted: e.target.checked })
                    }
                  />
                  <span>
                    <strong>Unrestricted public internet</strong>
                    <small>
                      Allow all public destinations through the coding proxy for
                      this account only.
                    </small>
                  </span>
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={policy.inherit}
                    onChange={(e) =>
                      change({ ...policy, inherit: e.target.checked })
                    }
                  />
                  <span>
                    <strong>Include global allowlist</strong>
                    <small>
                      Add account rules to the global list. Turn off to use only
                      account rules.
                    </small>
                  </span>
                </label>
              </div>
            )}
            {policy.unrestricted && (
              <p className="network-notice">
                All public destinations are allowed after saving. Your rules are
                retained for when unrestricted access is turned off.
              </p>
            )}
            <div className="network-toolbar">
              <div className="network-view" aria-label="Network rule view">
                <button
                  type="button"
                  aria-pressed={view === "draft"}
                  onClick={() => {
                    setView("draft");
                    setOffset(0);
                  }}
                >
                  Editable rules <b>{policy.rules.length}</b>
                </button>
                <button
                  type="button"
                  aria-pressed={view === "effective"}
                  onClick={() => {
                    setView("effective");
                    setOffset(0);
                  }}
                >
                  Currently effective{" "}
                  <b>
                    {data.effective?.unrestricted
                      ? "All"
                      : data.effective?.rules.length || 0}
                  </b>
                </button>
              </div>
              <button
                type="button"
                className="button primary"
                disabled={policy.rules.length >= 200}
                onClick={() => setEditing({ index: -1 })}
              >
                <Icon name="plus" size={16} />
                Add network rule
              </button>
            </div>
            <div className="network-filters">
              <label>
                Find a destination
                <input
                  type="search"
                  placeholder="Search domains, IPs or ports…"
                  value={query}
                  onChange={(e) => {
                    setQuery(e.target.value);
                    setOffset(0);
                  }}
                />
              </label>
              <label>
                Rule type
                <select
                  value={type}
                  onChange={(e) => {
                    setType(e.target.value);
                    setOffset(0);
                  }}
                >
                  {["all", "Domain", "Wildcard", "IP address", "Subnet"].map(
                    (t) => (
                      <option key={t} value={t}>
                        {t === "all" ? "All types" : t}
                      </option>
                    ),
                  )}
                </select>
              </label>
            </div>
            {view === "effective" && data.effective?.unrestricted ? (
              <p className="network-notice">
                The saved policy allows all public destinations and TCP ports.
              </p>
            ) : (
              <>
                <div className="network-table-wrap">
                  <table className="network-table">
                    <thead>
                      <tr>
                        <th>Destination</th>
                        <th>Type</th>
                        <th>TCP ports</th>
                        <th>
                          <span className="sr-only">Actions</span>
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {shown.map((rule) => (
                        <tr key={rule.index}>
                          <td>
                            <code>{rule.destination}</code>
                          </td>
                          <td>
                            <span className="network-type">{typeOf(rule)}</span>
                          </td>
                          <td>{portLabel(rule)}</td>
                          <td>
                            {view === "draft" && (
                              <div className="network-row-actions">
                                <button
                                  type="button"
                                  className="button small"
                                  aria-label={"Edit " + rule.destination}
                                  onClick={() =>
                                    setEditing({ index: rule.index, rule })
                                  }
                                >
                                  Edit
                                </button>
                                <button
                                  type="button"
                                  className="text-action"
                                  aria-label={"Remove " + rule.destination}
                                  onClick={() => {
                                    change({
                                      ...policy,
                                      rules: policy.rules.filter(
                                        (_, i) => i !== rule.index,
                                      ),
                                    });
                                    setOffset(0);
                                  }}
                                >
                                  Remove
                                </button>
                              </div>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {!filtered.length && (
                    <div className="network-empty">
                      <Icon name="globe" />
                      <strong>
                        {query || type !== "all"
                          ? "No matching rules"
                          : "No rules added"}
                      </strong>
                      <p>
                        {account && policy.inherit
                          ? "Global rules still apply. View the effective list to see them."
                          : "Add a destination to allow it through the coding proxy."}
                      </p>
                    </div>
                  )}
                </div>
                <Pagination
                  total={filtered.length}
                  offset={offset}
                  limit={10}
                  onPage={setOffset}
                  busy={busy}
                  label="network rules"
                />
              </>
            )}
            <details className="network-guidance">
              <summary>Policy behavior & defaults</summary>
              <p>
                Rules support domains, wildcard subdomains, public IPs and
                subnets. Only accounts can receive unrestricted access. HTTP,
                HTTPS and TCP tunnels use the authenticated proxy; applications
                must support it. Direct sockets, UDP, private networks, host
                services and metadata remain blocked. Browser sessions are
                separate.
              </p>
              {!account && (
                <button
                  type="button"
                  className="button"
                  onClick={() => {
                    change(structuredClone(data.defaults));
                    setView("draft");
                    setOffset(0);
                    setQuery("");
                  }}
                >
                  Load shipped package defaults
                </button>
              )}
            </details>
          </fieldset>
          <div className="network-savebar">
            <span>
              {dirty
                ? "Review and save your changes to apply them."
                : "Changes apply to existing and new coding workspaces."}
            </span>
            <div className="inline-actions">
              <button
                type="button"
                className="button"
                disabled={busy || !dirty}
                onClick={() => {
                  change(structuredClone(data.policy));
                  setOffset(0);
                  setError("");
                }}
              >
                Discard changes
              </button>
              <button
                type="button"
                className="button primary"
                disabled={busy || !dirty}
                onClick={save}
              >
                {busy ? "Saving…" : "Save network policy"}
              </button>
            </div>
          </div>
          {saved && (
            <p role="status" className="network-success">
              {saved}
            </p>
          )}
          {editing && (
            <RuleEditor
              rule={editing.rule}
              onClose={() => setEditing(null)}
              onSave={(rule) => {
                const duplicate = policy.rules.some(
                  (r, i) =>
                    i !== editing.index &&
                    r.destination.toLowerCase() ===
                      rule.destination.toLowerCase() &&
                    JSON.stringify(r.ports) === JSON.stringify(rule.ports),
                );
                if (duplicate) {
                  setError("That destination and ports already have a rule.");
                  setEditing(null);
                  return;
                }
                change({
                  ...policy,
                  rules:
                    editing.index < 0
                      ? [...policy.rules, rule]
                      : policy.rules.map((r, i) =>
                          i === editing.index ? rule : r,
                        ),
                });
                setEditing(null);
                setView("draft");
                setQuery(rule.destination);
                setType("all");
                setOffset(0);
              }}
            />
          )}
        </>
      )}
    </section>
  );
}
