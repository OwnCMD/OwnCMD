"use client";
import { useState } from "react";
const labels = {
  file_mb: "Maximum file size (MB)",
  storage_mb: "Upload storage per account (MB)",
  active_work: "Concurrent Work tasks",
  tasks_hour: "New conversations per hour",
  workspace_mb: "Live workspace size (MiB)",
  workspace_files: "Live workspace files & directories",
  daily_spend_usd: "Daily spend limit (USD; 0 = unlimited)",
};
export function ModelPolicy({ mode, value, onChange, models, inherit }) {
  const [query, setQuery] = useState("");
  return (
    <section className="admin-card">
      <h3>{mode === "chat" ? "Chat" : "Work"} models</h3>
      {inherit}
      <p>
        Select the models people can use. Auto always uses the default chosen
        below.
      </p>
      <label>
        Auto default
        <select
          aria-label={`${mode} Auto default`}
          value={value.auto}
          onChange={(e) => onChange({ ...value, auto: e.target.value })}
        >
          {value.allowed.map((id) => (
            <option key={id} value={id}>
              {models.find((m) => m.id === id)?.name || id}
            </option>
          ))}
        </select>
      </label>
      <input
        aria-label={`Find ${mode} models`}
        placeholder="Search model catalog…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      <p className="model-count">
        {value.allowed.length} of 50 selected · Provider rates, no markup
      </p>
      <div className="admin-models">
        {[
          ...new Set([
            ...value.allowed,
            ...models
              .filter((m) =>
                (m.name + " " + m.id)
                  .toLowerCase()
                  .includes(query.toLowerCase()),
              )
              .map((m) => m.id),
          ]),
        ]
          .slice(0, 100)
          .map((id) => {
            const m = models.find((m) => m.id === id);
            return (
              <label className="admin-check" key={id}>
                <input
                  type="checkbox"
                  checked={value.allowed.includes(id)}
                  disabled={
                    (value.allowed.length === 1 &&
                      value.allowed.includes(id)) ||
                    (value.allowed.length >= 50 && !value.allowed.includes(id))
                  }
                  onChange={(e) => {
                    const allowed = e.target.checked
                      ? [...value.allowed, id]
                      : value.allowed.filter((x) => x !== id);
                    onChange({
                      allowed,
                      auto: allowed.includes(value.auto)
                        ? value.auto
                        : allowed[0] || "",
                    });
                  }}
                />
                <span>
                  {m?.name || id}
                  <small>
                    {id}
                    {m?.vision ? " · Vision" : ""}
                    {m?.pricing?.prompt != null
                      ? ` · $${(Number(m.pricing.prompt) * 1e6).toFixed(2)} / $${(Number(m.pricing.completion) * 1e6).toFixed(2)} per 1M input/output tokens`
                      : ""}
                  </small>
                </span>
              </label>
            );
          })}
      </div>
    </section>
  );
}
export function Policy({
  value,
  onChange,
  models,
  ranges,
  reset,
  overrides,
  section = "all",
}) {
  const inherited = (section, key) =>
    reset && (
      <button
        type="button"
        className="text-action inherit-control"
        disabled={!Object.hasOwn(overrides?.[section] || {}, key)}
        onClick={() => reset(section, key)}
      >
        {Object.hasOwn(overrides?.[section] || {}, key)
          ? "Use global default"
          : "Inherits global default"}
      </button>
    );
  return (
    <>
      {(section === "all" || section === "models") && (
        <div className="admin-grid">
          {["chat", "work"].map((mode) => (
            <ModelPolicy
              key={mode}
              mode={mode}
              value={value.models[mode]}
              inherit={inherited("models", mode)}
              models={models}
              onChange={(v) =>
                onChange({ ...value, models: { ...value.models, [mode]: v } })
              }
            />
          ))}
        </div>
      )}
      {(section === "all" || section === "limits") && (
        <div className="admin-grid">
          <section className="admin-card">
            <h3>Feature access</h3>
            <div className="admin-feature-grid">
              {Object.entries(value.features).map(([k, v]) => (
                <label className="admin-check" key={k}>
                  <input
                    type="checkbox"
                    checked={v}
                    onChange={(e) =>
                      onChange({
                        ...value,
                        features: { ...value.features, [k]: e.target.checked },
                      })
                    }
                  />
                  <span>{k[0].toUpperCase() + k.slice(1)}</span>
                  {inherited("features", k)}
                </label>
              ))}
            </div>
          </section>
          <section className="admin-card">
            <h3>Usage limits</h3>
            {Object.entries(value.limits).map(([k, v]) => (
              <label key={k}>
                {labels[k]}
                <input
                  type="number"
                  min={ranges?.[k]?.[0]}
                  max={ranges?.[k]?.[1]}
                  value={v}
                  onChange={(e) =>
                    onChange({
                      ...value,
                      limits: { ...value.limits, [k]: Number(e.target.value) },
                    })
                  }
                />
                {inherited("limits", k)}
              </label>
            ))}
          </section>
        </div>
      )}
    </>
  );
}
