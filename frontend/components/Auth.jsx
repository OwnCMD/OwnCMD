"use client";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { Logo } from "./UI";

// Bootstrap and invitations never depend on SMTP. Tokens remain in memory.
export function Auth({ onSuccess }) {
  const [setup, setSetup] = useState(null),
    [invite, setInvite] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  useEffect(() => {
    api("setup")
      .then((d) => setSetup(d.required))
      .catch((e) => setError(e.message));
    if (location.hash.startsWith("#invite=")) setInvite(location.hash.slice(8));
  }, []);
  const creating = setup || !!invite;
  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const data = Object.fromEntries(new FormData(e.currentTarget));
    try {
      if (creating) {
        await api(setup ? "setup" : "invite/accept", {
          ...data,
          token: setup ? data.token : invite,
        });
        history.replaceState(null, "", location.pathname);
        setInvite("");
        setSetup(false);
      }
      await api("login", { email: data.email, password: data.password });
      await onSuccess();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="auth-shell">
      <div className="auth-brand">
        <Logo />
        <span>OwnCMD Community</span>
      </div>
      <div className="auth-card signup-card">
        <span className="eyebrow">YOUR SERVER. YOUR WORKSPACE.</span>
        <h1>
          {setup
            ? "Set up your instance"
            : invite
              ? "Join your workspace"
              : "Welcome back"}
        </h1>
        <p>
          {setup
            ? "Create the owner account. API keys are optional and can be added later in Instance settings."
            : invite
              ? "Create your member account using the email address your invitation was issued for."
              : "Sign in to your self-hosted workspace."}
        </p>
        <form onSubmit={submit}>
          {setup && (
            <label>
              Setup token
              <input
                name="token"
                type="password"
                required
                autoComplete="off"
                placeholder="Printed by your installer"
              />
            </label>
          )}
          {creating && (
            <label>
              Display name
              <input name="name" maxLength={100} required autoComplete="name" />
            </label>
          )}
          <label>
            Email (login identifier)
            <input name="email" type="email" required autoComplete="username" />
          </label>
          <label>
            Password
            <input
              name="password"
              type="password"
              required
              minLength={creating ? 12 : 1}
              maxLength={128}
              autoComplete={creating ? "new-password" : "current-password"}
            />
          </label>
          {creating && (
            <label>
              Confirm password
              <input
                name="confirm_password"
                type="password"
                required
                minLength={12}
                maxLength={128}
                autoComplete="new-password"
              />
            </label>
          )}
          <p className="form-error" role="alert">
            {error}
          </p>
          <button
            className="button primary auth-submit"
            disabled={busy || setup === null}
          >
            {busy ? "Please wait…" : creating ? "Create account" : "Sign in"}
          </button>
        </form>
        <p className="muted">
          {creating
            ? "No email verification or mail service is required."
            : "Need access? Ask an instance owner for an invitation. For password recovery, ask your server operator to run owncmdctl reset-password."}
        </p>
      </div>
    </main>
  );
}
