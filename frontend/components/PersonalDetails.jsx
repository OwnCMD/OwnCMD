"use client";
import { randomId } from "../lib/id.mjs";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { Icon, Modal } from "./UI";
export function PersonalDetails({ notify }) {
  const [data, setData] = useState(null),
    [saved, setSaved] = useState(""),
    [loading, setLoading] = useState(true),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [tab, setTab] = useState("contact"),
    [clear, setClear] = useState(false);
  const dirty = data && JSON.stringify(data) !== saved;
  async function load() {
    try {
      const r = await api("personal-details");
      setData(r);
      setSaved(JSON.stringify(r));
      setError("");
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    load();
  }, []);
  useEffect(() => {
    const warn = (e) => {
      if (dirty) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  function field(key, value) {
    setData((d) => ({ ...d, fields: { ...d.fields, [key]: value } }));
  }
  async function save() {
    setBusy(true);
    try {
      const r = await api("personal-details", data, "PUT");
      setData(r);
      setSaved(JSON.stringify(r));
      notify("Personal details saved");
      setError("");
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  const input = (key, type = "text") => (
    <label key={key}>
      {data.labels[key]}
      <input
        type={type}
        maxLength={1000}
        value={data.fields[key] || ""}
        autoComplete="off"
        onChange={(e) => field(key, e.target.value)}
      />
    </label>
  );
  const filled = data
    ? Object.values(data.fields).filter(Boolean).length +
      data.custom.filter((x) => x.value).length
    : 0;
  return (
    <div className="page personal-page">
      <div className="page-heading">
        <span className="eyebrow">YOUR PERSONAL WORKSPACE</span>
        <h1>Personal details</h1>
        <p>A little context. A lot less repetition.</p>
      </div>
      <section className="details-hero">
        <div className="details-hero-icon">
          <Icon name="user" size={30} />
        </div>
        <div>
          <h2>Ready when you need them</h2>
          <p>
            Keep your contact information, addresses and preferences in one
            place. Review prefilled answers before OwnCMD uses them in Work.
          </p>
          <div className="details-trust">
            <span>
              <Icon name="shield" size={14} />
              Encrypted at rest
            </span>
            <span>
              <Icon name="check" size={14} />
              You stay in control
            </span>
          </div>
        </div>
        <div className="details-count">
          <strong>{filled}</strong>
          <span>saved details</span>
        </div>
      </section>
      {error && (
        <div className="error-card" role="alert">
          {error}
          <button className="button small" onClick={load}>
            Reload
          </button>
        </div>
      )}
      {loading ? (
        <p role="status">Loading personal details…</p>
      ) : (
        data && (
          <>
            <div className="detail-prefill-toggle">
              <div>
                <strong>Prefill my Work answers</strong>
                <p>
                  Suggestions stay editable. Turning this off does not change
                  inputs you already approved for a schedule.
                </p>
              </div>
              <input
                aria-label="Prefill my Work answers"
                type="checkbox"
                role="switch"
                className="switch"
                checked={data.enabled}
                onChange={(e) =>
                  setData((d) => ({ ...d, enabled: e.target.checked }))
                }
              />
            </div>
            <div
              className="tabs"
              role="tablist"
              aria-label="Personal detail sections"
            >
              {[
                ["contact", "Contact"],
                ["addresses", "Addresses"],
                ["preferences", "Preferences"],
                ["custom", "Additional details"],
              ].map(([id, name]) => (
                <button
                  key={id}
                  role="tab"
                  aria-selected={tab === id}
                  onClick={() => setTab(id)}
                >
                  {name}
                </button>
              ))}
            </div>
            <fieldset className="details-body" disabled={busy}>
              {tab === "contact" && (
                <section className="details-card">
                  <h2>The essentials</h2>
                  <p>
                    Use the name and contact details you normally provide on
                    websites.
                  </p>
                  <div className="details-grid">
                    {[
                      "full_name",
                      "preferred_name",
                      "email",
                      "phone",
                      "company",
                      "job_title",
                    ].map((k) =>
                      input(
                        k,
                        k === "email"
                          ? "email"
                          : k === "phone"
                            ? "tel"
                            : "text",
                      ),
                    )}
                  </div>
                </section>
              )}
              {tab === "addresses" && (
                <div className="address-cards">
                  {["shipping", "billing"].map((prefix) => (
                    <section className="details-card" key={prefix}>
                      <div className="schedule-card-heading">
                        <h2>
                          {prefix === "shipping"
                            ? "Shipping address"
                            : "Billing address"}
                        </h2>
                        {prefix === "billing" && (
                          <button
                            className="button small"
                            onClick={() => {
                              setData((d) => {
                                const fields = { ...d.fields };
                                for (const suffix of [
                                  "name",
                                  "line1",
                                  "line2",
                                  "city",
                                  "region",
                                  "postal",
                                  "country",
                                ])
                                  fields["billing_" + suffix] =
                                    fields["shipping_" + suffix] || "";
                                return { ...d, fields };
                              });
                            }}
                          >
                            Copy shipping address
                          </button>
                        )}
                      </div>
                      <div className="details-grid">
                        {[
                          "name",
                          "line1",
                          "line2",
                          "city",
                          "region",
                          "postal",
                          "country",
                        ].map((s) => input(prefix + "_" + s))}
                      </div>
                    </section>
                  ))}
                </div>
              )}
              {tab === "preferences" && (
                <section className="details-card">
                  <h2>The details that make a difference</h2>
                  <div className="details-grid">
                    {["language", "timezone", "delivery_notes"].map((k) =>
                      input(k),
                    )}
                  </div>
                </section>
              )}
              {tab === "custom" && (
                <section className="details-card">
                  <h2>Useful to you, remembered by OwnCMD</h2>
                  <p>
                    Add clothing sizes, dietary preferences, loyalty program
                    names or other everyday details.
                  </p>
                  {data.custom.map((x, i) => (
                    <div className="custom-detail" key={x.id}>
                      <label>
                        Label
                        <input
                          aria-label={`Detail ${i + 1} label`}
                          value={x.label}
                          maxLength={80}
                          onChange={(e) =>
                            setData((d) => ({
                              ...d,
                              custom: d.custom.map((v) =>
                                v.id === x.id
                                  ? { ...v, label: e.target.value }
                                  : v,
                              ),
                            }))
                          }
                        />
                      </label>
                      <label>
                        Value
                        <input
                          aria-label={`Detail ${i + 1} value`}
                          value={x.value}
                          maxLength={1000}
                          onChange={(e) =>
                            setData((d) => ({
                              ...d,
                              custom: d.custom.map((v) =>
                                v.id === x.id
                                  ? { ...v, value: e.target.value }
                                  : v,
                              ),
                            }))
                          }
                        />
                      </label>
                      <button
                        className="button small"
                        aria-label={`Remove detail ${i + 1}`}
                        onClick={() =>
                          setData((d) => ({
                            ...d,
                            custom: d.custom.filter((v) => v.id !== x.id),
                          }))
                        }
                      >
                        <Icon name="trash" size={16} />
                      </button>
                    </div>
                  ))}
                  <button
                    className="button"
                    disabled={data.custom.length >= 20}
                    onClick={() =>
                      setData((d) => ({
                        ...d,
                        custom: [
                          ...d.custom,
                          { id: randomId(), label: "", value: "" },
                        ],
                      }))
                    }
                  >
                    <Icon name="plus" size={16} />
                    Add a detail
                  </button>
                </section>
              )}
            </fieldset>
            <p className="details-security">
              <Icon name="shield" size={15} />
              Do not store card numbers, security codes, passwords, verification
              codes or government ID numbers.
            </p>
            <div className="details-savebar">
              <span>
                {dirty
                  ? "Unsaved changes"
                  : data.updated
                    ? `Saved ${new Date(data.updated * 1000).toLocaleString()}`
                    : "Your details are private to your account."}
              </span>
              <div>
                <button
                  className="button subtle"
                  disabled={busy}
                  onClick={() => setClear(true)}
                >
                  Clear all
                </button>
                <button
                  className="button"
                  disabled={!dirty || busy}
                  onClick={() => setData(JSON.parse(saved))}
                >
                  Discard changes
                </button>
                <button
                  className="button primary"
                  disabled={!dirty || busy}
                  onClick={save}
                >
                  {busy ? "Saving…" : "Save details"}
                </button>
              </div>
            </div>
          </>
        )
      )}
      {clear && (
        <Modal title="Clear personal details?" onClose={() => setClear(false)}>
          <p className="modal-copy">
            This removes your saved profile. Previously approved schedule inputs
            and conversation history are separate; edit those to remove their
            copies.
          </p>
          <div className="modal-actions">
            <button className="button" onClick={() => setClear(false)}>
              Keep details
            </button>
            <button
              className="button danger"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                try {
                  await api("personal-details", {}, "DELETE");
                  await load();
                  setClear(false);
                  notify("Personal details cleared");
                } catch (e) {
                  setError(e.message);
                } finally {
                  setBusy(false);
                }
              }}
            >
              Clear personal details
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}
