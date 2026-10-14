"use client";
import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
export function WorkspaceTerminal({ task, locked, onRefresh, notify }) {
  const host = useRef(),
    term = useRef(),
    lock = useRef(locked),
    callbacks = useRef({ onRefresh, notify }),
    [status, setStatus] = useState("Not connected"),
    [session, setSession] = useState(0),
    [connecting, setConnecting] = useState(false);
  lock.current = locked;
  callbacks.current = { onRefresh, notify };
  useEffect(() => {
    if (!session) return;
    let active = true,
      timer,
      observer,
      disposable,
      fit,
      cursor = 0,
      chain = Promise.resolve(),
      connected = false;
    const request = (action, args = {}) =>
      api(`tasks/${task.id}/workspace`, { op: "terminal", action, ...args });
    const send = (action, args) => {
      chain = chain
        .then(async () => {
          if (!active || lock.current) return;
          await request(action, args);
        })
        .catch((e) => {
          if (active) {
            setStatus(e.message);
            callbacks.current.notify(e.message);
          }
        });
    };
    const poll = async () => {
      if (!active) return;
      try {
        const r = await request("read", { cursor });
        if (!active) return;
        if (r.truncated)
          term.current.writeln("\r\n[Earlier output trimmed]\r\n");
        if (r.output) term.current.write(r.output);
        cursor = r.cursor;
        setStatus(r.running ? "Connected" : "Shell exited");
        if (!r.running) {
          connected = false;
          return;
        }
      } catch (e) {
        if (active) {
          setStatus(e.message);
          connected = false;
          return;
        }
      }
      if (active) timer = setTimeout(poll, document.hidden ? 2000 : 220);
    };
    (async () => {
      try {
        setConnecting(true);
        setStatus("Opening terminal…");
        const [{ Terminal }, { FitAddon }] = await Promise.all([
          import("@xterm/xterm"),
          import("@xterm/addon-fit"),
        ]);
        if (!active) return;
        const terminal = new Terminal({
          fontFamily: "ui-monospace, SFMono-Regular, Consolas, monospace",
          fontSize: 13,
          scrollback: 5000,
          cursorBlink: true,
          screenReaderMode: true,
          theme: {
            background: "#111820",
            foreground: "#e0e7ed",
            cursor: "#67d6c6",
          },
          allowProposedApi: false,
        });
        term.current = terminal;
        fit = new FitAddon();
        terminal.loadAddon(fit);
        terminal.open(host.current);
        fit.fit();
        await request("open", { cols: terminal.cols, rows: terminal.rows });
        if (!active) return;
        connected = true;
        setConnecting(false);
        callbacks.current.onRefresh();
        disposable = terminal.onData((data) => {
          if (!lock.current && connected) send("input", { data });
        });
        observer = new ResizeObserver(() => {
          fit.fit();
          if (connected && !lock.current)
            send("resize", { cols: terminal.cols, rows: terminal.rows });
        });
        observer.observe(host.current);
        terminal.focus();
        poll();
      } catch (e) {
        if (active) {
          setStatus(e.message);
          setConnecting(false);
        }
      }
    })();
    return () => {
      active = false;
      clearTimeout(timer);
      observer?.disconnect();
      disposable?.dispose();
      term.current?.dispose();
      term.current = null;
    };
  }, [session, task.id]);
  useEffect(() => {
    if (term.current) term.current.options.disableStdin = locked;
  }, [locked]);
  return (
    <div className="workspace-terminal">
      <div className="terminal-toolbar">
        <span>
          <i className={status === "Connected" ? "live-dot" : "offline-dot"} />
          {locked ? "Input paused while OwnCMD works" : status}
        </span>
        <div>
          <button
            className="button small"
            onClick={() => term.current?.clear()}
          >
            Clear display
          </button>
          <button
            className="button small"
            disabled={locked || connecting}
            onClick={() => setSession((s) => s + 1)}
          >
            {session ? "Reconnect" : "Open terminal"}
          </button>
          <button
            className="button small"
            disabled={locked || !session || connecting}
            onClick={async () => {
              try {
                await api(`tasks/${task.id}/workspace`, {
                  op: "terminal",
                  action: "close",
                });
                setSession(0);
                setStatus("Terminal closed");
                callbacks.current.onRefresh();
              } catch (e) {
                notify(e.message);
              }
            }}
          >
            End session
          </button>
        </div>
      </div>
      <div className="terminal-host" ref={host} />
      {!session && (
        <div className="terminal-welcome">
          <strong>Your Linux workspace</strong>
          <p>
            Run commands, install packages, use interactive programs and inspect
            your app.
          </p>
          <button
            className="button primary"
            disabled={locked}
            onClick={() => setSession(1)}
          >
            Open terminal
          </button>
        </div>
      )}
      <p className="terminal-help">
        Bash · Tab completion · ↑ command history · Ctrl+C interrupt · Ctrl+D
        exit. Opening a terminal starts workspace billing. The session stays
        alive when you switch tabs.
      </p>
    </div>
  );
}
