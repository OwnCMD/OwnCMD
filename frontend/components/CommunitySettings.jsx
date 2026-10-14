"use client";
import { useEffect, useRef, useState } from "react";
import { api, copyText } from "../lib/api";
import { CodeNetworkPolicy } from "./CodeNetworkPolicy";
import { Icon, Modal } from "./UI";
import { Policy } from "./CommunityPolicy";

const tabs = [
  ["providers", "Providers", "globe"],
  ["members", "Members", "user"],
  ["models", "Models", "spark"],
  ["limits", "Access & limits", "settings"],
  ["network", "Network", "shield"],
];
const clone = (v) => structuredClone(v);
const roleName = (v) => (v === "admin" ? "Owner" : "Member");

// Settings writes carry the version the operator reviewed. A conflict must be
// reloaded rather than silently replacing another owner's changes.
export function CommunitySettings() {
  const [tab, setTab] = useState("providers");
  const [providers, setProviders] = useState(null),
    [settings, setSettings] = useState(null);
  const [savedPolicy, setSavedPolicy] = useState(null);
  const [savedMember, setSavedMember] = useState(null);
  const [models, setModels] = useState([]),
    [catalogError, setCatalogError] = useState("");
  const [users, setUsers] = useState([]),
    [next, setNext] = useState(null),
    [offset, setOffset] = useState(0);
  const [query, setQuery] = useState(""),
    [role, setRole] = useState("all"),
    [status, setStatus] = useState("all");
  const [loading, setLoading] = useState(true),
    [membersLoading, setMembersLoading] = useState(false);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [message, setMessage] = useState("");
  const [invite, setInvite] = useState(null),
    [inviteOpen, setInviteOpen] = useState(false);
  const [confirm, setConfirm] = useState(null),
    [member, setMember] = useState(null);
  const [memberTab, setMemberTab] = useState("account"),
    [memberError, setMemberError] = useState("");
  const [dirty, setDirty] = useState(false),
    [userRefresh, setUserRefresh] = useState(0);
  const opening = useRef(0),
    mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  async function loadSettings() {
    setLoading(true);
    setError("");
    try {
      const [p, s] = await Promise.all([
        api("instance/providers"),
        api("admin/settings"),
      ]);
      if (mounted.current) {
        setProviders(p);
        setSettings(s);
        setSavedPolicy(clone(s.policy));
        setDirty(false);
      }
    } catch (e) {
      if (mounted.current) setError(e.message);
    } finally {
      if (mounted.current) setLoading(false);
    }
  }
  async function loadCatalog() {
    setCatalogError("");
    try {
      const result = await api("admin/models");
      if (mounted.current) setModels(result);
    } catch (e) {
      if (mounted.current)
        setCatalogError(
          "Model catalog unavailable. Check your OpenRouter key, then retry. " +
            e.message,
        );
    }
  }
  useEffect(() => {
    loadSettings();
  }, []);
  useEffect(() => {
    if (tab === "models" || (memberTab === "models" && member)) loadCatalog();
  }, [tab, memberTab, !!member]);
  useEffect(() => {
    if (tab !== "members") return;
    const controller = new AbortController();
    setMembersLoading(true);
    const timer = setTimeout(async () => {
      try {
        const result = await api(
          "admin/users?" +
            new URLSearchParams({
              q: query,
              role,
              status,
              offset: String(offset),
            }),
          undefined,
          "GET",
          controller.signal,
        );
        if (!controller.signal.aborted) {
          setUsers(result.users);
          setNext(result.next_offset);
        }
      } catch (e) {
        if (!controller.signal.aborted) setError(e.message);
      } finally {
        if (!controller.signal.aborted) setMembersLoading(false);
      }
    }, 200);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [tab, query, role, status, offset, userRefresh]);
  useEffect(() => {
    if (!dirty) return;
    const warn = (e) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  async function action(fn, success = "Changes saved.") {
    if (busy) return;
    setBusy(true);
    setError("");
    setMemberError("");
    setMessage("");
    try {
      await fn();
      setMessage(success);
      return true;
    } catch (e) {
      setError(e.message);
      setMemberError(e.message);
      return false;
    } finally {
      setBusy(false);
    }
  }
  function chooseTab(value) {
    setTab(value);
    setError("");
    setMessage("");
  }
  function editPolicy(value) {
    setSettings((s) => ({ ...s, policy: value }));
    setDirty(true);
  }
  async function savePolicy() {
    const result = await api(
      "admin/settings",
      { policy: settings.policy, version: settings.version },
      "PUT",
    );
    setSettings((s) => ({ ...s, ...result }));
    setSavedPolicy(clone(result.policy || settings.policy));
    setDirty(false);
    window.dispatchEvent(new Event("aster:policy-changed"));
  }
  async function openMember(id) {
    const request = ++opening.current;
    setBusy(true);
    setError("");
    setMemberError("");
    try {
      const value = await api("admin/users/" + id);
      if (request === opening.current && mounted.current) {
        setMember(value);
        setSavedMember(clone(value));
        setMemberTab("account");
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  function editMemberPolicy(value) {
    setMember((old) => {
      const overrides = clone(old.overrides);
      for (const section of ["models", "features", "limits"]) {
        for (const [key, v] of Object.entries(value[section])) {
          if (
            JSON.stringify(v) !== JSON.stringify(old.effective[section][key])
          ) {
            overrides[section] ??= {};
            overrides[section][key] = v;
          }
        }
      }
      return { ...old, overrides, effective: value };
    });
  }
  function inherit(section, key) {
    setMember((old) => {
      const overrides = clone(old.overrides);
      delete overrides[section]?.[key];
      if (overrides[section] && !Object.keys(overrides[section]).length)
        delete overrides[section];
      return {
        ...old,
        overrides,
        effective: {
          ...old.effective,
          [section]: {
            ...old.effective[section],
            [key]: savedPolicy[section][key],
          },
        },
      };
    });
  }
  async function saveMember(value) {
    await api(
      "admin/users/" + value.id,
      {
        role: value.role,
        disabled: value.disabled,
        overrides: value.overrides,
        version: value.version,
      },
      "PUT",
    );
    const fresh = await api("admin/users/" + value.id);
    setSavedMember(clone(fresh));
    setMember(fresh);
    setUserRefresh((v) => v + 1);
    window.dispatchEvent(new Event("aster:policy-changed"));
  }
  function ask(title, description, run, label = "Confirm") {
    setConfirm({ title, description, run, label });
  }
  const providerRows = [
    [
      "openrouter_key",
      "OpenRouter",
      "Models for Chat, Work and reusable skills",
      "spark",
    ],
    ["exa_key", "Exa", "Web search and page retrieval", "globe"],
  ];
  return (
    <section className="instance-page">
      <header className="instance-heading">
        <div>
          <span className="eyebrow">OWNCMD COMMUNITY</span>
          <h1>Instance settings</h1>
          <p>Your workspace, configured your way.</p>
        </div>
        <span className="instance-edition">
          <Icon name="shield" size={14} /> Owner controls
        </span>
      </header>
      <nav className="instance-tabs" aria-label="Instance settings sections">
        {tabs.map(([id, label, icon]) => (
          <button
            key={id}
            type="button"
            aria-current={tab === id ? "page" : undefined}
            onClick={() => chooseTab(id)}
          >
            <Icon name={icon} size={16} />
            {label}
          </button>
        ))}
      </nav>
      {error && (
        <div className="instance-alert error" role="alert">
          <Icon name="info" />
          <span>{error}</span>
          <button
            className="button small"
            disabled={busy}
            onClick={loadSettings}
          >
            Reload settings
          </button>
        </div>
      )}
      {message && (
        <div className="instance-alert" role="status">
          <Icon name="check" />
          <span>{message}</span>
        </div>
      )}
      {loading && (
        <div className="instance-empty" role="status">
          Loading instance settings…
        </div>
      )}
      {!loading && tab === "providers" && providers && (
        <>
          <div className="instance-section-head">
            <div>
              <h2>Provider connections</h2>
              <p>
                Add keys when you need them. They can be changed at any time.
              </p>
            </div>
          </div>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const form = e.currentTarget;
              const values = Object.fromEntries(new FormData(form));
              action(async () => {
                const p = await api(
                  "instance/providers",
                  { settings: values, version: providers.version },
                  "PUT",
                );
                setProviders(p);
                form.reset();
              }, "Provider keys saved.");
            }}
          >
            <fieldset disabled={busy} className="instance-fieldset">
              <div className="provider-grid">
                {providerRows.map(([key, name, help, icon]) => (
                  <section className="provider-card" key={key}>
                    <div className="provider-card-head">
                      <span className="provider-icon">
                        <Icon name={icon} size={23} />
                      </span>
                      <span
                        className={
                          "instance-status " +
                          (providers.credentials[key].configured
                            ? "enabled"
                            : "")
                        }
                      >
                        {providers.credentials[key].configured
                          ? "Configured"
                          : "Not configured"}
                      </span>
                    </div>
                    <h3>{name}</h3>
                    <p>{help}</p>
                    <label className="instance-field">
                      {name} API key
                      <input
                        name={key}
                        type="password"
                        autoComplete="new-password"
                        maxLength={4096}
                        placeholder={
                          providers.credentials[key].configured
                            ? "Enter a replacement key"
                            : "Paste your API key"
                        }
                      />
                    </label>
                    <div className="provider-card-foot">
                      <small>
                        {providers.credentials[key].configured
                          ? "Leave blank to keep your current key."
                          : "Optional until you use this provider."}
                      </small>
                      {providers.credentials[key].configured && (
                        <button
                          type="button"
                          className="button small danger-outline"
                          onClick={() =>
                            ask(
                              "Remove " + name + " key?",
                              "New requests using this provider will stop working until you add another key. The key will also stop falling back to its installation value.",
                              () =>
                                action(
                                  async () =>
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
                                  name + " key removed.",
                                ),
                              "Remove key",
                            )
                          }
                        >
                          Remove key
                        </button>
                      )}
                    </div>
                  </section>
                ))}
              </div>
              <div className="instance-save">
                <p>
                  <Icon name="shield" size={15} /> Keys are encrypted and never
                  displayed after saving.
                </p>
                <button className="button primary" type="submit">
                  {busy ? "Saving…" : "Save provider keys"}
                </button>
              </div>
            </fieldset>
          </form>
          <aside className="instance-note">
            <Icon name="info" />
            <p>
              Provider charges go directly to your provider account. OwnCMD
              Community adds no markup and has no credit wallet.
            </p>
          </aside>
        </>
      )}
      {!loading && tab === "members" && (
        <>
          <div className="instance-section-head">
            <div>
              <h2>Members & owners</h2>
              <p>
                Manage access without mixing account actions into your member
                list.
              </p>
            </div>
            <button
              className="button primary"
              disabled={busy}
              onClick={() => {
                setInviteOpen(true);
                setMemberError("");
              }}
            >
              <Icon name="plus" size={16} />
              Invite member
            </button>
          </div>
          <div className="members-toolbar">
            <label className="member-search">
              <Icon name="search" size={16} />
              <input
                type="search"
                aria-label="Search members"
                placeholder="Search by email…"
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value);
                  setOffset(0);
                }}
              />
            </label>
            <label>
              Role
              <select
                value={role}
                onChange={(e) => {
                  setRole(e.target.value);
                  setOffset(0);
                }}
              >
                <option value="all">All roles</option>
                <option value="admin">Owners</option>
                <option value="user">Members</option>
              </select>
            </label>
            <label>
              Status
              <select
                value={status}
                onChange={(e) => {
                  setStatus(e.target.value);
                  setOffset(0);
                }}
              >
                <option value="all">All statuses</option>
                <option value="active">Active</option>
                <option value="suspended">Suspended</option>
              </select>
            </label>
          </div>
          <div className="member-list" aria-busy={membersLoading}>
            <div className="member-list-head">
              <span>Account</span>
              <span>Role</span>
              <span>Status</span>
              <span>Actions</span>
            </div>
            {membersLoading ? (
              <div className="instance-empty" role="status">
                Loading members…
              </div>
            ) : users.length ? (
              users.map((u) => (
                <article className="member-row" key={u.id}>
                  <div className="member-identity">
                    <span className="member-avatar">
                      {u.email[0].toUpperCase()}
                    </span>
                    <span>
                      <strong>{u.email}</strong>
                      <small>
                        Joined {new Date(u.created * 1000).toLocaleDateString()}
                      </small>
                    </span>
                  </div>
                  <span className="member-role">{roleName(u.role)}</span>
                  <span
                    className={
                      "instance-status " + (!u.disabled ? "enabled" : "")
                    }
                  >
                    {u.disabled ? "Suspended" : "Active"}
                  </span>
                  <button
                    className="button small"
                    disabled={busy}
                    aria-label={"Manage " + u.email}
                    onClick={() => openMember(u.id)}
                  >
                    Manage
                    <Icon name="chevron" size={14} />
                  </button>
                </article>
              ))
            ) : (
              <div className="instance-empty">
                <Icon name="user" size={28} />
                <h3>No matching members</h3>
                <p>Try a different email, role or status.</p>
              </div>
            )}
          </div>
          <div className="members-pagination">
            <span>
              Page {Math.floor(offset / 50) + 1} · {users.length} accounts shown
            </span>
            <div>
              <button
                className="button small"
                disabled={!offset || membersLoading}
                onClick={() => setOffset(Math.max(0, offset - 50))}
              >
                Previous
              </button>
              <button
                className="button small"
                disabled={next == null || membersLoading}
                onClick={() => setOffset(next)}
              >
                Next
              </button>
            </div>
          </div>
          <div className="instance-note">
            <Icon name="shield" />
            <div>
              <strong>Invitation access</strong>
              <p>
                Links expire after 24 hours and work once. Share them privately;
                Community does not send email.
              </p>
            </div>
            <button
              className="button small"
              disabled={busy}
              onClick={() =>
                ask(
                  "Revoke outstanding invitations?",
                  "All unused invitation links will stop working. Existing members keep their access.",
                  () =>
                    action(async () => {
                      await api("instance/invites", {}, "DELETE");
                      setInvite(null);
                    }, "Outstanding invitations revoked."),
                  "Revoke invitations",
                )
              }
            >
              Revoke invitations
            </button>
          </div>
        </>
      )}
      {!loading && (tab === "models" || tab === "limits") && settings && (
        <>
          <div className="instance-section-head">
            <div>
              <h2>
                {tab === "models"
                  ? "Model preferences"
                  : "Feature access & limits"}
              </h2>
              <p>
                {tab === "models"
                  ? "Choose available models and an Auto default for each mode."
                  : "Set the defaults members inherit. Individual accounts can have their own policy."}
              </p>
            </div>
          </div>
          {tab === "models" && catalogError && (
            <div className="instance-alert error" role="alert">
              <span>{catalogError}</span>
              <button className="button small" onClick={loadCatalog}>
                Retry catalog
              </button>
            </div>
          )}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              action(savePolicy, "Instance policy saved.");
            }}
          >
            <fieldset className="instance-fieldset" disabled={busy}>
              <Policy
                value={settings.policy}
                onChange={editPolicy}
                models={models}
                ranges={settings.limit_ranges}
                section={tab}
              />
              <div className="instance-save">
                <p>
                  {dirty
                    ? "You have unsaved changes."
                    : "Changes apply to members using instance defaults."}
                </p>
                <button
                  className="button primary"
                  disabled={!dirty}
                  type="submit"
                >
                  {busy ? "Saving…" : "Save changes"}
                </button>
              </div>
            </fieldset>
          </form>
        </>
      )}
      {!loading && tab === "network" && <CodeNetworkPolicy />}
      {inviteOpen && (
        <Modal
          title="Invite a member"
          onClose={() => {
            if (!busy) setInviteOpen(false);
          }}
        >
          <form
            className="instance-dialog-form"
            onSubmit={(e) => {
              e.preventDefault();
              const email = new FormData(e.currentTarget).get("email");
              action(
                async () =>
                  setInvite({
                    ...(await api("instance/invites", { email })),
                    email,
                  }),
                "Invitation created. Share the link privately.",
              );
            }}
          >
            <p>Create a private invitation for one person. No email is sent.</p>
            <label className="instance-field">
              Email address
              <input
                name="email"
                type="email"
                required
                placeholder="member@example.com"
                disabled={busy}
              />
            </label>
            {memberError && (
              <p role="alert" className="form-error">
                {memberError}
              </p>
            )}
            <button className="button primary" disabled={busy}>
              Create invitation link
            </button>
            {invite && (
              <div className="invite-result">
                <strong>Invitation for {invite.email}</strong>
                <p>Expires in 24 hours · Single use</p>
                <label className="instance-field">
                  Invitation link
                  <input readOnly value={invite.url} />
                </label>
                <button
                  type="button"
                  className="button"
                  onClick={() =>
                    action(
                      () => copyText(invite.url),
                      "Invitation link copied.",
                    )
                  }
                  disabled={busy}
                >
                  <Icon name="copy" size={15} />
                  Copy link
                </button>
              </div>
            )}
          </form>
        </Modal>
      )}
      {member && (
        <Modal
          title="Manage member"
          wide
          onClose={() => {
            if (!busy) {
              setMember(null);
              setMemberError("");
            }
          }}
        >
          <div className="member-detail">
            <div className="member-detail-heading">
              <span className="member-avatar">
                {member.email[0].toUpperCase()}
              </span>
              <div>
                <h3>{member.profile?.name || member.email}</h3>
                <p>{member.email}</p>
              </div>
              <span
                className={
                  "instance-status " + (!member.disabled ? "enabled" : "")
                }
              >
                {member.disabled ? "Suspended" : "Active"}
              </span>
            </div>
            <nav className="instance-tabs" aria-label="Member settings">
              {[
                ["account", "Account"],
                ["models", "Models"],
                ["limits", "Access & limits"],
                ["network", "Network"],
              ].map(([id, name]) => (
                <button
                  key={id}
                  aria-current={memberTab === id ? "page" : undefined}
                  onClick={() => setMemberTab(id)}
                >
                  {name}
                </button>
              ))}
            </nav>
            {memberError && (
              <div className="instance-alert error" role="alert">
                <span>{memberError}</span>
                <button
                  className="button small"
                  disabled={busy}
                  onClick={() => openMember(member.id)}
                >
                  Reload member
                </button>
              </div>
            )}
            {message && !memberError && (
              <p role="status" className="member-message">
                {message}
              </p>
            )}
            {memberTab === "account" ? (
              <>
                <div className="member-facts">
                  <span>
                    Role<strong>{roleName(member.role)}</strong>
                  </span>
                  <span>
                    Active sessions<strong>{member.sessions}</strong>
                  </span>
                  <span>
                    Conversations<strong>{member.conversations}</strong>
                  </span>
                </div>
                <section className="member-action">
                  <div>
                    <h3>Account role</h3>
                    <p>
                      Owners can manage providers, members and instance policy.
                    </p>
                  </div>
                  <button
                    className="button"
                    disabled={busy}
                    onClick={() =>
                      ask(
                        "Change account role?",
                        member.email +
                          " will become an " +
                          (member.role === "admin" ? "Member" : "Owner") +
                          ". At least one active Owner must remain.",
                        () =>
                          action(
                            () =>
                              saveMember({
                                ...savedMember,
                                role:
                                  member.role === "admin" ? "user" : "admin",
                              }),
                            "Account role updated.",
                          ),
                        "Change role",
                      )
                    }
                  >
                    {member.role === "admin" ? "Make Member" : "Make Owner"}
                  </button>
                </section>
                <section className="member-action">
                  <div>
                    <h3>Signed-in sessions</h3>
                    <p>Require this account to sign in again on all devices.</p>
                  </div>
                  <button
                    className="button"
                    disabled={busy}
                    onClick={() =>
                      ask(
                        "Sign out all sessions?",
                        member.email +
                          " will need to sign in again. If this is your account, your current session will end too.",
                        () =>
                          action(async () => {
                            await api(
                              "admin/users/" + member.id + "/revoke-sessions",
                              {},
                            );
                            setMember((m) => ({ ...m, sessions: 0 }));
                          }, "Sessions signed out."),
                        "Sign out sessions",
                      )
                    }
                  >
                    Sign out sessions
                  </button>
                </section>
                <section className="member-action danger-zone">
                  <div>
                    <h3>
                      {member.disabled ? "Restore access" : "Suspend account"}
                    </h3>
                    <p>
                      {member.disabled
                        ? "Allow this member to sign in and use their workspace again."
                        : "Block access and stop active work. Existing account data is retained."}
                    </p>
                  </div>
                  <button
                    className="button danger-outline"
                    disabled={busy}
                    onClick={() =>
                      ask(
                        member.disabled
                          ? "Restore this account?"
                          : "Suspend this account?",
                        member.email +
                          (member.disabled
                            ? " will be allowed to sign in again."
                            : " will lose access. Active work will be stopped; data is retained."),
                        () =>
                          action(
                            () =>
                              saveMember({
                                ...savedMember,
                                disabled: !member.disabled,
                              }),
                            "Account access updated.",
                          ),
                        member.disabled ? "Restore access" : "Suspend account",
                      )
                    }
                  >
                    {member.disabled ? "Restore access" : "Suspend account"}
                  </button>
                </section>
              </>
            ) : memberTab === "network" ? (
              <CodeNetworkPolicy owner={member.id} />
            ) : (
              <>
                <p className="member-policy-note">
                  Changes here apply only to this account. Use the default
                  controls to remove individual overrides.
                </p>
                {memberTab === "models" && catalogError && (
                  <div className="instance-alert error" role="alert">
                    <span>{catalogError}</span>
                    <button className="button small" onClick={loadCatalog}>
                      Retry catalog
                    </button>
                  </div>
                )}
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    action(() => saveMember(member), "Member policy saved.");
                  }}
                >
                  <fieldset className="instance-fieldset" disabled={busy}>
                    <Policy
                      value={member.effective}
                      onChange={editMemberPolicy}
                      models={models}
                      ranges={settings?.limit_ranges}
                      section={memberTab}
                      overrides={member.overrides}
                      reset={inherit}
                    />
                    <div className="instance-save">
                      <span>
                        Model and resource changes affect this account only.
                      </span>
                      <button className="button primary" type="submit">
                        Save member policy
                      </button>
                    </div>
                  </fieldset>
                </form>
              </>
            )}
          </div>
        </Modal>
      )}
      {confirm && (
        <Modal
          title={confirm.title}
          onClose={() => {
            if (!busy) setConfirm(null);
          }}
        >
          <div className="instance-dialog-form">
            <p>{confirm.description}</p>
            {memberError && (
              <p className="form-error" role="alert">
                {memberError}
              </p>
            )}
            <div className="instance-dialog-actions">
              <button
                className="button"
                disabled={busy}
                onClick={() => setConfirm(null)}
              >
                Cancel
              </button>
              <button
                className="button primary"
                disabled={busy}
                onClick={async () => {
                  if (await confirm.run()) setConfirm(null);
                }}
              >
                {busy ? "Working…" : confirm.label}
              </button>
            </div>
          </div>
        </Modal>
      )}
    </section>
  );
}
