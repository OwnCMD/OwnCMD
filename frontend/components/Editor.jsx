"use client";
import { useEffect, useImperativeHandle, useRef, useState } from "react";
import { copyText } from "../lib/api";
let loading;
function loadEditor() {
  if (!loading) {
    globalThis.MonacoEnvironment = {
      getWorker: (_, label) =>
        new Worker(
          `/static/editor/${{ json: "json", css: "css", scss: "css", less: "css", html: "html", handlebars: "html", razor: "html", javascript: "ts", typescript: "ts" }[label] || "editor"}.worker.js`,
        ),
    };
    if (!document.querySelector("link[data-editor-css]")) {
      const css = document.createElement("link");
      css.rel = "stylesheet";
      css.href = "/static/editor/monaco.css";
      css.dataset.editorCss = "true";
      document.head.append(css);
    }
    loading = import(
      /* webpackIgnore: true */ "/static/editor/monaco.js"
    ).catch((e) => {
      loading = null;
      throw e;
    });
  }
  return loading;
}
const language = (path) =>
  ({
    js: "javascript",
    jsx: "javascript",
    mjs: "javascript",
    cjs: "javascript",
    ts: "typescript",
    tsx: "typescript",
    json: "json",
    html: "html",
    htm: "html",
    vue: "html",
    css: "css",
    scss: "scss",
    less: "less",
    py: "python",
    sh: "shell",
    bash: "shell",
    md: "markdown",
    yml: "yaml",
    yaml: "yaml",
    sql: "sql",
    php: "php",
    go: "go",
    rs: "rust",
    java: "java",
    c: "c",
    cpp: "cpp",
    xml: "xml",
    toml: "ini",
    txt: "plaintext",
  })[path.split(".").at(-1).toLowerCase()] ||
  (path.endsWith("Dockerfile") ? "dockerfile" : "plaintext");
const supportsFormat = (path) =>
  /\.(?:[cm]?js|jsx|tsx?|json|html?|vue|css|scss|less|md|markdown|ya?ml)$/i.test(
    path,
  );
const compressed = (source) => {
  const lines = source.split(/\r?\n/).filter((l) => l.trim());
  return (
    lines.some((l) => l.length > 1000) ||
    (lines.length <= 3 && lines.some((l) => l.length > 120))
  );
};
export function Editor({
  ref,
  path,
  value,
  readOnly,
  onChange,
  onSave,
  onEdit,
  truncated = false,
}) {
  const host = useRef(),
    instance = useRef(),
    model = useRef(),
    callbacks = useRef(),
    latest = useRef(),
    silent = useRef(false),
    formatWorker = useRef(),
    formatTimer = useRef(),
    formatSeq = useRef(0);
  const [copied, setCopied] = useState(false),
    [wrap, setWrap] = useState(true),
    [error, setError] = useState(""),
    [ready, setReady] = useState(false),
    [position, setPosition] = useState("Ln 1, Col 1"),
    [formatted, setFormatted] = useState(null),
    [sourceView, setSourceView] = useState(false),
    [formatting, setFormatting] = useState(false),
    [notice, setNotice] = useState("");
  callbacks.current = { onChange, onSave, onEdit };
  latest.current = { path, value, readOnly, truncated };
  const previewing =
    readOnly && !sourceView && formatted != null && formatted !== value;
  const display = previewing ? formatted : value;
  function cancelFormat() {
    formatSeq.current++;
    clearTimeout(formatTimer.current);
    formatWorker.current?.terminate();
    formatWorker.current = null;
  }
  function formatDocument(auto = false) {
    const current = latest.current;
    if (!supportsFormat(current.path) || current.truncated) return;
    cancelFormat();
    const seq = formatSeq.current,
      source = instance.current?.getValue() ?? current.value;
    setFormatting(true);
    setNotice("");
    const fail = (message) => {
      if (formatSeq.current !== seq) return;
      cancelFormat();
      setFormatting(false);
      setNotice(
        auto
          ? "Showing original source. Use Format document to check its syntax."
          : `Could not format: ${message} Your code is unchanged.`,
      );
    };
    try {
      const worker = new Worker("/static/editor/format.worker.js");
      formatWorker.current = worker;
      formatTimer.current = setTimeout(
        () => fail("formatting took too long."),
        8000,
      );
      worker.onerror = () => fail("formatter unavailable.");
      worker.onmessage = ({ data }) => {
        if (formatSeq.current !== seq) return;
        if (data.error) {
          fail(data.error);
          return;
        }
        cancelFormat();
        setFormatting(false);
        // Never apply an asynchronous result over newer edits, a changed path or lock state.
        if (
          latest.current.path !== current.path ||
          latest.current.value !== current.value ||
          latest.current.readOnly !== current.readOnly
        )
          return;
        if (current.readOnly) {
          setFormatted(data.value);
          setSourceView(false);
          if (data.value === current.value)
            setNotice("This file is already formatted.");
        } else if (instance.current) {
          const editor = instance.current;
          editor.pushUndoStop();
          editor.executeEdits("format-document", [
            { range: model.current.getFullModelRange(), text: data.value },
          ]);
          editor.pushUndoStop();
          editor.focus();
        }
      };
      worker.postMessage({ path: current.path, source });
    } catch {
      fail("formatter unavailable.");
    }
  }
  useImperativeHandle(
    ref,
    () => ({
      beginEdit() {
        cancelFormat();
        setFormatting(false);
        callbacks.current.onEdit?.(display);
      },
    }),
    [display],
  );
  useEffect(() => {
    let active = true,
      observer,
      disposeChange,
      disposeCursor,
      disposeAction;
    loadEditor()
      .then((monaco) => {
        if (!active) return;
        const dark = () =>
          document.documentElement.dataset.theme === "dark" ||
          document.documentElement.classList.contains("dark");
        model.current = monaco.editor.createModel(
          latest.current.value,
          language(path),
          monaco.Uri.parse(
            "inmemory://workspace/" + encodeURIComponent(path || "untitled"),
          ),
        );
        const editor = monaco.editor.create(host.current, {
          model: model.current,
          theme: dark() ? "vs-dark" : "vs",
          readOnly,
          automaticLayout: true,
          fontSize: 13,
          lineHeight: 21,
          fontFamily: "ui-monospace, SFMono-Regular, Consolas, monospace",
          wordWrap: wrap ? "on" : "off",
          wrappingIndent: "indent",
          minimap: { enabled: false },
          scrollBeyondLastLine: false,
          padding: { top: 14, bottom: 14 },
          tabSize: 2,
          insertSpaces: true,
          renderWhitespace: "selection",
          guides: { indentation: true, bracketPairs: true },
          bracketPairColorization: { enabled: true },
          ariaLabel: "File content",
          fixedOverflowWidgets: false,
        });
        instance.current = editor;
        disposeChange = editor.onDidChangeModelContent(() => {
          if (!silent.current && !latest.current.readOnly)
            callbacks.current.onChange?.(editor.getValue());
        });
        disposeCursor = editor.onDidChangeCursorPosition((e) =>
          setPosition(`Ln ${e.position.lineNumber}, Col ${e.position.column}`),
        );
        editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () =>
          callbacks.current.onSave?.(),
        );
        disposeAction = editor.addAction({
          id: "aster.formatDocument",
          label: "Format document",
          keybindings: [
            monaco.KeyMod.Shift | monaco.KeyMod.Alt | monaco.KeyCode.KeyF,
          ],
          contextMenuGroupId: "1_modification",
          run: () => formatDocument(),
        });
        observer = new MutationObserver(() =>
          monaco.editor.setTheme(dark() ? "vs-dark" : "vs"),
        );
        observer.observe(document.documentElement, {
          attributes: true,
          attributeFilter: ["data-theme", "class"],
        });
        setReady(true);
      })
      .catch(() => {
        if (active)
          setError("The editor could not load. Reopen the workspace to retry.");
      });
    return () => {
      active = false;
      cancelFormat();
      observer?.disconnect();
      disposeChange?.dispose();
      disposeCursor?.dispose();
      disposeAction?.dispose();
      instance.current?.dispose();
      model.current?.dispose();
      instance.current = null;
      model.current = null;
    };
  }, []);
  useEffect(() => {
    if (ready && model.current)
      loadEditor().then((monaco) => {
        if (model.current)
          monaco.editor.setModelLanguage(model.current, language(path));
      });
  }, [path, ready]);
  useEffect(() => {
    instance.current?.updateOptions({
      readOnly,
      wordWrap: wrap ? "on" : "off",
    });
  }, [readOnly, wrap, ready]);
  useEffect(() => {
    if (model.current && model.current.getValue() !== display) {
      silent.current = true;
      model.current.setValue(display);
      silent.current = false;
    }
  }, [display, ready]);
  useEffect(() => {
    setFormatted(null);
    setSourceView(false);
    setNotice("");
    if (
      ready &&
      readOnly &&
      !truncated &&
      supportsFormat(path) &&
      compressed(value)
    )
      formatDocument(true);
    else {
      cancelFormat();
      setFormatting(false);
    }
    return cancelFormat;
  }, [path, value, readOnly, ready, truncated]);
  return (
    <div className="editor-shell">
      <div className="editor-tools">
        <span>
          {language(path)} · {readOnly ? "Read only" : "Editing"}
        </span>
        <div>
          <button
            className="button small"
            onClick={async () => {
              try {
                await copyText(display);
                setCopied(true);
                setTimeout(() => setCopied(false), 1600);
              } catch {
                setError(
                  "Copy failed. Select the code and copy with your keyboard.",
                );
              }
            }}
          >
            {copied ? "Copied" : "Copy"}
          </button>
          <button
            className="button small"
            disabled={!ready}
            onClick={() => instance.current?.getAction("actions.find").run()}
          >
            Find
          </button>
          {supportsFormat(path) && !truncated && (
            <button
              className="button small"
              disabled={!ready || formatting}
              title="Format document (Shift+Alt+F)"
              onClick={() => formatDocument()}
            >
              {formatting ? "Formatting…" : "Format document"}
            </button>
          )}
          <button
            className="button small"
            aria-pressed={wrap}
            title="Wrap long lines to the editor width"
            onClick={() => setWrap(!wrap)}
          >
            Wrap {wrap ? "on" : "off"}
          </button>
        </div>
      </div>
      {previewing ? (
        <div className="editor-format-note" role="status">
          <span>Formatted preview · saved file unchanged</span>
          <button onClick={() => setSourceView(true)}>Show original</button>
        </div>
      ) : readOnly && formatted != null && formatted !== value ? (
        <div className="editor-format-note">
          <span>Original source</span>
          <button onClick={() => setSourceView(false)}>Show formatted</button>
        </div>
      ) : null}
      {notice && (
        <p className="editor-notice" role="status">
          {notice}
        </p>
      )}
      {error && <p role="alert">{error}</p>}
      {!ready && !error && <p role="status">Loading code editor…</p>}
      <div className="monaco-host" ref={host} />
      <div className="editor-status">
        <span>{position}</span>
        <span>Spaces: 2 · UTF-8 · Ctrl / ⌘ S to save</span>
      </div>
    </div>
  );
}
