"use client";
import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { mobileClient } from "../lib/browser-display.mjs";
import { Icon } from "./UI";

export function ModelPicker({ options, value = "auto", onChange }) {
  const [open, setOpen] = useState(false),
    [query, setQuery] = useState("");
  const root = useRef(null),
    trigger = useRef(null),
    search = useRef(null),
    popover = useRef(null),
    id = useId();
  const models = options?.models || [];
  const selected = models.find((m) => m.id === value),
    auto = models.find((m) => m.id === options?.auto);
  const choices = [
    {
      id: "auto",
      name: "Auto",
      description: auto
        ? `Default · ${auto.name}`
        : "Use your configured default",
    },
    ...models.map((m) => ({ ...m, description: m.id })),
  ];
  const visible = choices.filter((m) =>
    (m.name + " " + m.description).toLowerCase().includes(query.toLowerCase()),
  );
  function close() {
    setOpen(false);
    trigger.current?.focus({ preventScroll: true });
  }
  useEffect(() => {
    if (!open) return;
    // Opening the chooser should not summon a mobile keyboard.
    if (mobileClient()) popover.current?.focus({ preventScroll: true });
    else search.current?.focus({ preventScroll: true });
    function fit() {
      const p = popover.current,
        r = trigger.current?.getBoundingClientRect();
      if (!p || !r) return;
      const v = window.visualViewport,
        top = v?.offsetTop || 0,
        left = v?.offsetLeft || 0;
      const height = v?.height || window.innerHeight,
        width = v?.width || window.innerWidth;
      const small = mobileClient() || width < 700;
      const available = Math.max(100, height - 24),
        maxHeight = Math.min(480, available);
      p.style.width = `${Math.min(380, width - 24)}px`;
      p.style.maxHeight = `${maxHeight}px`;
      p.style.left = `${small ? left + 12 : Math.max(left + 12, Math.min(r.left, left + width - 392))}px`;
      const actualHeight = p.getBoundingClientRect().height;
      p.style.top = `${small ? top + 12 : Math.max(top + 12, Math.min(r.top - actualHeight - 12, top + height - actualHeight - 12))}px`;
    }
    fit();
    window.addEventListener("resize", fit);
    window.visualViewport?.addEventListener("resize", fit);
    window.visualViewport?.addEventListener("scroll", fit);
    function outside(e) {
      if (
        !root.current?.contains(e.target) &&
        !popover.current?.contains(e.target)
      )
        setOpen(false);
    }
    document.addEventListener("pointerdown", outside);
    document.addEventListener("focusin", outside);
    return () => {
      window.removeEventListener("resize", fit);
      window.visualViewport?.removeEventListener("resize", fit);
      window.visualViewport?.removeEventListener("scroll", fit);
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("focusin", outside);
    };
  }, [open]);
  const optionKey = JSON.stringify([
    options?.auto,
    models.map((m) => [m.id, m.name]),
  ]);
  useEffect(() => {
    setOpen(false);
    setQuery("");
  }, [optionKey]);
  function keys(e) {
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      close();
      return;
    }
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) return;
    const nodes = [...popover.current.querySelectorAll("[role=option]")];
    if (!nodes.length) return;
    if (e.target === search.current && ["Home", "End"].includes(e.key)) return;
    e.preventDefault();
    const at = nodes.indexOf(document.activeElement);
    const next =
      e.key === "Home"
        ? 0
        : e.key === "End"
          ? nodes.length - 1
          : e.key === "ArrowDown"
            ? (at + 1) % nodes.length
            : at <= 0
              ? nodes.length - 1
              : at - 1;
    nodes[next].focus();
  }
  return (
    <div className="model-picker" ref={root}>
      <button
        type="button"
        className="model-trigger"
        ref={trigger}
        aria-label="Model"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => {
          setQuery("");
          setOpen((v) => !v);
        }}
      >
        <Icon name={value === "auto" ? "spark" : "memory"} size={14} />
        <span>
          {value === "auto" ? "Auto" : selected?.name || "Choose a model"}
        </span>
        <Icon name="chevron" size={12} />
      </button>
      {open &&
        createPortal(
          <div
            ref={popover}
            tabIndex={-1}
            onKeyDown={keys}
            className="model-popover"
            role="dialog"
            aria-label="Choose model"
          >
            <div className="model-popover-heading">
              <button
                type="button"
                className="icon-button"
                aria-label="Close model chooser"
                onClick={close}
              >
                <Icon name="close" size={16} />
              </button>
              <strong>Choose a model</strong>
              <small>
                {options?.source === "account"
                  ? "Account model policy"
                  : "Global model policy"}
              </small>
            </div>
            <label className="model-search">
              <Icon name="search" size={16} />
              <input
                ref={search}
                aria-label="Search models"
                placeholder="Search models…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </label>
            <div
              role="listbox"
              aria-label="Model options"
              id={id}
              className="model-options"
            >
              {visible.map((m) => (
                <button
                  type="button"
                  role="option"
                  aria-selected={value === m.id}
                  key={m.id}
                  onClick={() => {
                    onChange(m.id);
                    close();
                  }}
                >
                  <span className="model-option-icon">
                    <Icon
                      name={m.id === "auto" ? "spark" : "memory"}
                      size={17}
                    />
                  </span>
                  <span>
                    <strong>{m.name}</strong>
                    <small>{m.description}</small>
                  </span>
                  {value === m.id && <Icon name="check" size={16} />}
                </button>
              ))}
            </div>
            {!visible.length && (
              <p className="model-empty">No matching models.</p>
            )}
          </div>,
          document.body,
        )}
    </div>
  );
}
