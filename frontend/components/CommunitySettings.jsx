"use client";
import { useEffect, useState } from "react";
import { api, copyText } from "../lib/api";
import { CodeNetworkPolicy } from "./CodeNetworkPolicy";

export function CommunitySettings() {
  const [tab, setTab] = useState("providers"),
    [providers, setProviders] = useState(null),
    [policy, setPolicy] = useState(null),
    [users, setUsers] = useState([]),
    [error, setError] = useState(""),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false),
    [invite, setInvite] = useState("");
  async function load() {
    const [p, s, u] = await Promise.all([
      api("instance/providers"),
      api("admin/settings"),
      api("admin/users"),
    ]);
    setProviders(p);
    setPolicy(s);
    setUsers(u.users);
  }
  useEffect(() => {
    load().catch((e) => setError(e.message));
  }, []);
  async function action(fn) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await fn();
      setMessage("Saved successfully.");
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  async function updateUser(user, changes) {
    const current = await api("admin/users/" + user.id);
    await api(
      "admin/users/" + user.id,
      {
        role: current.role,
        disabled: current.disabled,
        overrides: current.overrides,
        version: current.version,
        ...changes,
      },
      "PUT",
    );
    await load();
  }
  return (
    <section className="community-page">
      <span className="eyebrow">OWNCMD COMMUNITY</span>
      <h1>Instance settings</h1>
      <p>
        Manage your self-hosted workspace. Owners administer the instance;
        members use their own private conversations and files.
      </p>
      <nav className="community-tabs">
        {["providers", "members", "models", "network"].map((t) => (
          <button
            className={"button " + (tab === t ? "primary" : "")}
            key={t}
            onClick={() => setTab(t)}
          >
            {t[0].toUpperCase() + t.slice(1)}
          </button>
        ))}
      </nav>
      {error && (
        <p role="alert" className="form-error">
          {error}
        </p>
      )}
      {message && <p role="status">{message}</p>}
      {tab === "providers" && providers && (
        <form
          className="community-card"
          onSubmit={(e) => {
            e.preventDefault();
            const form = e.currentTarget;
            const settings = Object.fromEntries(new FormData(form));
            action(async () => {
              setProviders(
                await api(
                  "instance/providers",
                  { settings, version: providers.version },
                  "PUT",
                ),
              );
              form.reset();
            });
          }}
        >
          <h2>Provider keys</h2>
          <p>
            Optional during installation. Add or replace keys whenever you need
            them. Blank fields keep existing keys. Provider charges go directly
            to your provider account.
          </p>
          {[
            [
              "openrouter_key",
              "OpenRouter",
              "Chat, Work and model-powered features",
            ],
            ["exa_key", "Exa", "Web search and page retrieval"],
          ].map(([key, label, help]) => (
            <div key={key}>
              <label>
                {label} ·{" "}
                {providers.credentials[key].configured
                  ? "Configured"
                  : "Not configured"}
                <input
                  name={key}
                  type="password"
                  autoComplete="new-password"
                  placeholder="Paste a new key to replace"
                  maxLength={4096}
                />
              </label>
              <small>{help}</small>
              {providers.credentials[key].configured && (
                <button
                  type="button"
                  className="text-action"
                  disabled={busy}
                  onClick={() =>
                    action(async () =>
                      setProviders(
                        await api(
                          "instance/providers",
                          {
                            settings: {},
                            remove: [key],
                            version: providers.version,
                          },
                          "PUT",
                        ),
                      ),
                    )
                  }
                >
                  Remove key
                </button>
              )}
            </div>
          ))}
          <button className="button primary" disabled={busy}>
            Save provider keys
          </button>
        </form>
      )}
      {tab === "members" && (
        <div className="community-card">
          <h2>Members and owners</h2>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const email = new FormData(e.currentTarget).get("email");
              action(async () =>
                setInvite((await api("instance/invites", { email })).url),
              );
            }}
          >
            <label>
              Invite a member
              <input
                name="email"
                type="email"
                required
                placeholder="member@example.com"
              />
            </label>
            <button className="button" disabled={busy}>
              Create invitation link
            </button>
          </form>
          {invite && (
            <div>
              <p>
                Share privately. This link expires in 24 hours and can be used
                once.
              </p>
              <input readOnly value={invite} aria-label="Invitation link" />
              <button
                className="button"
                onClick={() => action(() => copyText(invite))}
              >
                Copy link
              </button>
            </div>
          )}
          <button
            className="text-action"
            disabled={busy}
            onClick={() =>
              action(async () => {
                await api("instance/invites", {}, "DELETE");
                setInvite("");
              })
            }
          >
            Revoke all outstanding invitations
          </button>
          <div className="community-table">
            <table>
              <thead>
                <tr>
                  <th>Account</th>
                  <th>Role</th>
                  <th>Status</th>
                  <th>Access</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id}>
                    <td>{u.email}</td>
                    <td>
                      <select
                        aria-label={"Role for " + u.email}
                        value={u.role}
                        disabled={busy}
                        onChange={(e) =>
                          action(() => updateUser(u, { role: e.target.value }))
                        }
                      >
                        <option value="user">Member</option>
                        <option value="admin">Owner</option>
                      </select>
                    </td>
                    <td>{u.disabled ? "Suspended" : "Active"}</td>
                    <td>
                      <button
                        className="text-action"
                        disabled={busy}
                        onClick={() =>
                          action(() => updateUser(u, { disabled: !u.disabled }))
                        }
                      >
                        {u.disabled ? "Reactivate" : "Suspend"}
                      </button>
                      <button
                        className="text-action"
                        disabled={busy}
                        onClick={() =>
                          action(() =>
                            api("admin/users/" + u.id + "/revoke-sessions", {}),
                          )
                        }
                      >
                        Sign out sessions
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      {tab === "models" && policy && (
        <form
          className="community-card"
          onSubmit={(e) => {
            e.preventDefault();
            action(async () => {
              const d = await api(
                "admin/settings",
                { policy: policy.policy, version: policy.version },
                "PUT",
              );
              setPolicy((old) => ({ ...old, ...d }));
            });
          }}
        >
          <h2>Models and resource limits</h2>
          <p>
            Use provider model IDs. The first model in each list is Auto. Saving
            validates the models with OpenRouter.
          </p>
          {["chat", "work"].map((mode) => (
            <label key={mode}>
              {mode === "chat" ? "Chat" : "Work"} models (one per line)
              <textarea
                value={policy.policy.models[mode].allowed.join("\n")}
                onChange={(e) => {
                  const allowed = e.target.value.split("\n");
                  setPolicy((old) => ({
                    ...old,
                    policy: {
                      ...old.policy,
                      models: {
                        ...old.policy.models,
                        [mode]: { allowed, auto: allowed[0] },
                      },
                    },
                  }));
                }}
              />
            </label>
          ))}
          {Object.entries(policy.policy.limits).map(([key, value]) => (
            <label key={key}>
              {key.replaceAll("_", " ")}
              <input
                type="number"
                min={policy.limit_ranges[key][0]}
                max={policy.limit_ranges[key][1]}
                value={value}
                onChange={(e) =>
                  setPolicy((old) => ({
                    ...old,
                    policy: {
                      ...old.policy,
                      limits: {
                        ...old.policy.limits,
                        [key]: Number(e.target.value),
                      },
                    },
                  }))
                }
              />
            </label>
          ))}
          <button className="button primary" disabled={busy}>
            Save models and limits
          </button>
        </form>
      )}
      {tab === "network" && <CodeNetworkPolicy />}
    </section>
  );
}
