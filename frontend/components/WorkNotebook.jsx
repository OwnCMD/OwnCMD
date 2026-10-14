"use client";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { Icon, Modal } from "./UI";
export function WorkNotebook({ task }) {
  const [open, setOpen] = useState(false),
    [query, setQuery] = useState(""),
    [offset, setOffset] = useState(0),
    [data, setData] = useState(null),
    [entry, setEntry] = useState(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  useEffect(() => {
    setOpen(false);
    setEntry(null);
    setData(null);
    setQuery("");
    setOffset(0);
  }, [task?.id]);
  useEffect(() => {
    if (!open || !task?.id) return;
    let active = true;
    const load = () =>
      api(
        `tasks/${task.id}/notebook?query=${encodeURIComponent(query)}&offset=${offset}`,
      )
        .then((r) => {
          if (active) {
            setData(r);
            setError("");
          }
        })
        .catch((e) => {
          if (active) setError(e.message);
        });
    const timer = setTimeout(load, query ? 250 : 0),
      poll = setInterval(load, 5000);
    return () => {
      active = false;
      clearTimeout(timer);
      clearInterval(poll);
    };
  }, [open, task?.id, query, offset]);
  async function read(key, offset = 0) {
    setBusy(true);
    setError("");
    try {
      setEntry(
        await api(
          `tasks/${task.id}/notebook?key=${encodeURIComponent(key)}&offset=${offset}`,
        ),
      );
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <button
        className="button small"
        disabled={!task}
        onClick={() => setOpen(true)}
      >
        <Icon name="file" size={15} />
        Notebook
      </button>
      {open && (
        <Modal title="Work notebook" wide onClose={() => setOpen(false)}>
          <p className="muted">
            OwnCMD’s saved plan, findings and decisions for this conversation.
            Kept with this Work chat, including while its workspace is stopped.
          </p>
          <input
            className="notebook-search"
            aria-label="Search Work notebook"
            placeholder="Find a fact, decision or completed step…"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setOffset(0);
              setData(null);
              setEntry(null);
            }}
          />
          {error && (
            <p role="alert" className="form-error">
              {error}
            </p>
          )}
          <div className="notebook-layout">
            <div className="notebook-entries">
              {(data?.entries || data?.matches || []).map((x, i) => (
                <button
                  key={x.key + ":" + i}
                  className={
                    "notebook-entry " + (entry?.key === x.key ? "selected" : "")
                  }
                  disabled={busy}
                  onClick={() => read(x.key, x.offset || 0)}
                >
                  <strong>{x.title}</strong>
                  <small>
                    {x.kind === "checklist"
                      ? x.status.replace("_", " ")
                      : x.kind}{" "}
                    · {Math.max(1, Math.ceil(x.size / 1024))} KB
                  </small>
                  {x.text && <span>{x.text.slice(0, 180)}</span>}
                </button>
              ))}
              {data && !(data.entries || data.matches || []).length && (
                <p className="muted">No matching notes.</p>
              )}
              {offset > 0 && (
                <button
                  className="button small"
                  disabled={busy}
                  onClick={() =>
                    setOffset(Math.max(0, offset - (query ? 6 : 50)))
                  }
                >
                  Previous notes
                </button>
              )}
              {data?.next_offset != null && (
                <button
                  className="button small"
                  disabled={busy}
                  onClick={() => setOffset(data.next_offset)}
                >
                  More notes
                </button>
              )}
            </div>
            <div className="notebook-content">
              {entry ? (
                <>
                  <h3>{entry.title}</h3>
                  <small>
                    {entry.status.replace("_", " ")} · revision {entry.revision}
                  </small>
                  <pre>{entry.text}</pre>
                  <div className="inline-actions">
                    {entry.offset > 0 && (
                      <button
                        className="button small"
                        disabled={busy}
                        onClick={() =>
                          read(entry.key, Math.max(0, entry.offset - 12000))
                        }
                      >
                        Previous section
                      </button>
                    )}
                    {entry.next_offset != null && (
                      <button
                        className="button small"
                        disabled={busy}
                        onClick={() => read(entry.key, entry.next_offset)}
                      >
                        Next section
                      </button>
                    )}
                    <button
                      className="button small"
                      disabled={busy}
                      onClick={() => read(entry.key, entry.offset)}
                    >
                      Refresh note
                    </button>
                  </div>
                </>
              ) : (
                <p className="muted">
                  Choose a note to read it. OwnCMD updates the notebook as work
                  progresses.
                </p>
              )}
            </div>
          </div>
        </Modal>
      )}
    </>
  );
}
