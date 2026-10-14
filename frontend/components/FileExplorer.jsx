"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { Icon } from "./UI";
import { ancestorPaths, fileTree } from "../lib/file-tree.mjs";
export function FileExplorer({
  files,
  path,
  filter,
  onFilter,
  onOpen,
  loading,
  error,
  onNew,
  newDisabled,
}) {
  const tree = useMemo(() => fileTree(files), [files]),
    [collapsed, setCollapsed] = useState(new Set()),
    [focus, setFocus] = useState(""),
    host = useRef();
  useEffect(() => {
    setCollapsed((old) => {
      const next = new Set(old);
      ancestorPaths(path).forEach((p) => next.delete(p));
      return next;
    });
    setFocus(path);
  }, [path]);
  const query = filter.trim().toLowerCase();
  const matching = (node) =>
    node.path.toLowerCase().includes(query) ||
    (node.folder && node.children.some(matching));
  const rows = [];
  function visit(nodes, depth = 1, parent = null) {
    for (const n of nodes) {
      if (query && !matching(n)) continue;
      const open = n.folder && (query || !collapsed.has(n.path));
      rows.push({ ...n, depth, parent, open: !!open });
      if (open) visit(n.children, depth + 1, n.path);
    }
  }
  visit(tree);
  const focused = rows.some((r) => r.path === focus) ? focus : rows[0]?.path;
  function toggle(node) {
    setCollapsed((old) => {
      const next = new Set(old);
      next.has(node.path) ? next.delete(node.path) : next.add(node.path);
      return next;
    });
  }
  function move(target) {
    if (!target) return;
    setFocus(target);
    requestAnimationFrame(() =>
      [...(host.current?.querySelectorAll("[role=treeitem]") || [])]
        .find((n) => n.dataset.path === target)
        ?.focus(),
    );
  }
  function keys(e, node, index) {
    let target;
    if (e.key === "ArrowDown")
      target = rows[Math.min(rows.length - 1, index + 1)]?.path;
    else if (e.key === "ArrowUp") target = rows[Math.max(0, index - 1)]?.path;
    else if (e.key === "Home") target = rows[0]?.path;
    else if (e.key === "End") target = rows.at(-1)?.path;
    else if (e.key === "ArrowRight" && node.folder) {
      if (!node.open) toggle(node);
      else target = rows[index + 1]?.path;
    } else if (e.key === "ArrowLeft") {
      if (node.folder && node.open && !query) toggle(node);
      else target = node.parent;
    } else if (e.key === "Enter" || e.key === " ") {
      node.folder ? toggle(node) : onOpen(node.path);
    } else return;
    e.preventDefault();
    move(target);
  }
  return (
    <nav className="workspace-explorer" aria-label="Project files">
      <div className="explorer-heading">
        <strong>Explorer</strong>
        <div>
          <button
            title="Expand all folders"
            aria-label="Expand all folders"
            onClick={() => setCollapsed(new Set())}
          >
            <Icon name="expand" size={14} />
          </button>
          <button
            title="Collapse all folders"
            aria-label="Collapse all folders"
            onClick={() => {
              const all = [];
              function walk(ns) {
                ns.forEach((n) => {
                  if (n.folder) {
                    all.push(n.path);
                    walk(n.children);
                  }
                });
              }
              walk(tree);
              setCollapsed(new Set(all));
            }}
          >
            <Icon name="collapse" size={14} />
          </button>
        </div>
      </div>
      <label className="file-search">
        <Icon name="search" size={14} />
        <input
          aria-label="Filter files"
          placeholder="Find a file…"
          value={filter}
          onChange={(e) => onFilter(e.target.value)}
        />
      </label>
      <div className="explorer-root">
        <Icon name="chevron" size={12} />
        <span>WORKSPACE</span>
        <small>{files.length}</small>
      </div>
      <div
        className="file-tree"
        role="tree"
        aria-label="Workspace files"
        ref={host}
      >
        {loading && !files.length ? (
          <p role="status">Loading workspace files…</p>
        ) : rows.length ? (
          rows.map((n, i) => (
            <div
              key={n.path}
              role="treeitem"
              aria-label={n.name}
              aria-level={n.depth}
              aria-expanded={n.folder ? n.open : undefined}
              aria-selected={!n.folder && path === n.path}
              tabIndex={focused === n.path ? 0 : -1}
              data-path={n.path}
              className={`tree-row ${n.folder ? "folder-row" : "file-row"} ${path === n.path ? "selected" : ""}`}
              style={{ paddingLeft: 8 + (n.depth - 1) * 16 }}
              title={n.path}
              onFocus={() => setFocus(n.path)}
              onClick={() => {
                setFocus(n.path);
                n.folder ? toggle(n) : onOpen(n.path);
              }}
              onKeyDown={(e) => keys(e, n, i)}
            >
              <span className={"tree-chevron " + (n.open ? "open" : "")}>
                {n.folder && <Icon name="chevron" size={12} />}
              </span>
              <Icon
                name={n.folder ? (n.open ? "folderOpen" : "folder") : "file"}
                size={15}
              />
              <span className="tree-name">{n.name}</span>
            </div>
          ))
        ) : (
          <p>
            {filter
              ? "No files match your search."
              : error
                ? "Files could not be loaded."
                : "This project has no saved files yet."}
          </p>
        )}
      </div>
      <button
        className="button small explorer-new"
        disabled={newDisabled}
        onClick={onNew}
      >
        <Icon name="plus" size={14} />
        New file
      </button>
    </nav>
  );
}
