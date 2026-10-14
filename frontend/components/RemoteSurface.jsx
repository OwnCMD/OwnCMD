"use client";
import { useEffect, useImperativeHandle, useRef, useState } from "react";
import { Icon } from "./UI";
import { previewDisplay, framePoint } from "../lib/browser-display.mjs";
import { readFrameStream } from "../lib/preview-stream.mjs";
import "../app/preview-stream.css";
function surfaceViewport(element, mode) {
  const r = element?.getBoundingClientRect();
  if (!r || r.width < 1 || r.height < 1) return null;
  return previewDisplay(r.width, r.height, mode);
}
// One serial input stream. Failed or unacknowledged input is never replayed automatically.
export function RemoteSurface({
  ref,
  taskId,
  frameURL,
  streamURL,
  request,
  resizeRequest,
  enabled,
  drag = false,
  label,
  imageLabel,
  onURL,
  onApproval,
  onStatus,
  notify,
  active = true,
  starting = false,
}) {
  const host = useRef(),
    image = useRef(),
    keyboard = useRef(),
    callbacks = useRef(),
    queue = useRef([]),
    chain = useRef(Promise.resolve()),
    batch = useRef(null),
    timer = useRef(),
    mounted = useRef(false),
    kick = useRef(() => {}),
    gesture = useRef(),
    fitted = useRef(false),
    serverStopped = useRef(false),
    composing = useRef(false),
    [state, setState] = useState("Connecting…"),
    [loaded, setLoaded] = useState(false),
    [frameReady, setFrameReady] = useState(false),
    [displayMode, setDisplayMode] = useState("auto"),
    [inputError, setInputError] = useState("");
  callbacks.current = {
    request,
    resizeRequest,
    enabled,
    onURL,
    onApproval,
    onStatus,
    notify,
    active,
    starting,
  };
  function fitRenderedFrame() {
    const img = image.current,
      box = host.current?.getBoundingClientRect();
    if (!img?.naturalWidth || !img.naturalHeight || !box?.width || !box.height)
      return;
    const scale = Math.min(
      box.width / img.naturalWidth,
      box.height / img.naturalHeight,
    );
    // Size the image box itself, so input coordinates exclude any fit margins.
    // This also fills larger viewers when CDP sends a downscaled frame.
    img.style.width = `${img.naturalWidth * scale}px`;
    img.style.height = `${img.naturalHeight * scale}px`;
  }
  useEffect(() => {
    const observer = new ResizeObserver(fitRenderedFrame);
    if (host.current) observer.observe(host.current);
    return () => observer.disconnect();
  }, []);
  function enqueue(kind, args = {}) {
    if (!callbacks.current.enabled || !loaded) return;
    const last = queue.current.at(-1);
    if (
      kind === "text" &&
      last?.kind === "text" &&
      last.args.text.length + args.text.length <= 12000
    )
      last.args.text += args.text;
    else if (kind === "move" && last?.kind === "move") last.args = args;
    else if (kind === "scroll" && last?.kind === "scroll") {
      last.args.delta += args.delta;
      last.args.x += args.x || 0;
      last.args.atX = args.atX;
      last.args.atY = args.atY;
    } else queue.current.push({ kind, args });
    if (queue.current.length > 240) {
      queue.current = [];
      setInputError("Input queue is full. Wait for the browser to catch up.");
      return;
    }
    if (!timer.current) timer.current = setTimeout(flush, 14);
  }
  function dispatch(kind, args = {}, token) {
    chain.current = chain.current
      .catch(() => {})
      .then(async () => {
        if (!mounted.current || !callbacks.current.enabled) return;
        try {
          const r = await callbacks.current.request(kind, args, token);
          if (!mounted.current) return;
          if (r?.approval_required) {
            queue.current = [];
            callbacks.current.onApproval?.(r, kind, args);
            return r;
          }
          if (r?.url) callbacks.current.onURL?.(r.url);
          if (r?.session_warning) callbacks.current.notify?.(r.session_warning);
          setInputError("");
          kick.current();
          return r;
        } catch (e) {
          queue.current = [];
          if (mounted.current)
            setInputError(
              e.message + " Check the page before trying the action again.",
            );
          throw e;
        }
      });
    return chain.current;
  }
  function flush() {
    clearTimeout(timer.current);
    timer.current = null;
    if (batch.current) return batch.current;
    if (!queue.current.length) return chain.current;
    const events = queue.current.splice(0, 80);
    const result = dispatch("input", { events });
    batch.current = result;
    result
      .catch(() => {})
      .finally(() => {
        batch.current = null;
        if (mounted.current && queue.current.length)
          timer.current = setTimeout(flush, 0);
      });
    return result;
  }
  async function drain() {
    let result = await flush();
    while (queue.current.length && !result?.approval_required)
      result = await flush();
    return result;
  }
  useImperativeHandle(ref, () => ({
    async run(kind, args = {}, token) {
      const pending = await drain();
      if (pending?.approval_required) return pending;
      return dispatch(kind, args, token);
    },
    drain,
    display: () => surfaceViewport(host.current, displayMode),
    refresh: () => kick.current(),
    focusKeyboard: () => keyboard.current?.focus({ preventScroll: true }),
  }));
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      queue.current = [];
      clearTimeout(timer.current);
    };
  }, []);
  useEffect(() => {
    if (!enabled) {
      queue.current = [];
      gesture.current = null;
      keyboard.current?.blur();
    }
  }, [enabled]);
  useEffect(() => {
    const panel = host.current?.closest("aside");
    if (!panel) return;
    let frame;
    const fit = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        if (window.innerWidth > 1000) {
          panel.style.removeProperty("--remote-visible-height");
          panel.style.removeProperty("--remote-visible-top");
          return;
        }
        const viewport = window.visualViewport,
          top = viewport?.offsetTop || 0;
        const base = panel.classList.contains("fullscreen")
          ? 0
          : parseFloat(
              getComputedStyle(document.documentElement).getPropertyValue(
                "--app-topbar-height",
              ),
            ) || 62;
        const panelTop = Math.max(top, base);
        panel.style.setProperty("--remote-visible-top", `${panelTop}px`);
        panel.style.setProperty(
          "--remote-visible-height",
          `${Math.max(80, (viewport?.height || window.innerHeight) + top - panelTop)}px`,
        );
      });
    };
    fit();
    window.addEventListener("resize", fit);
    window.visualViewport?.addEventListener("resize", fit);
    window.visualViewport?.addEventListener("scroll", fit);
    const observer = new MutationObserver(fit);
    observer.observe(panel, { attributes: true, attributeFilter: ["class"] });
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      window.removeEventListener("resize", fit);
      window.visualViewport?.removeEventListener("resize", fit);
      window.visualViewport?.removeEventListener("scroll", fit);
      panel.style.removeProperty("--remote-visible-height");
      panel.style.removeProperty("--remote-visible-top");
    };
  }, [active]);
  useEffect(() => {
    if (!active) return;
    setLoaded(false);
    setFrameReady(false);
    setState(
      frameURL.includes("workspace-frame")
        ? "Preview is starting…"
        : "Browser is starting…",
    );
    fitted.current = false;
    serverStopped.current = false;
    image.current?.removeAttribute("src");
    const fittingStarted = performance.now();
    let alive = true,
      first = true,
      inflight = false,
      urgent = false,
      controller,
      tick,
      url = "",
      failures = 0,
      streaming = false,
      streamController,
      streamRetry,
      streamWatchdog,
      pendingFrame,
      painting = false,
      paintRetry;
    const streamAddress =
      streamURL ||
      (/-frame$/.test(frameURL)
        ? frameURL.replace(/-frame$/, "-stream")
        : null);
    async function paintLatest() {
      if (painting) return;
      painting = true;
      try {
        while (alive && pendingFrame) {
          const { metadata, bytes } = pendingFrame;
          pendingFrame = null;
          setFrameReady(true);
          if (
            first &&
            callbacks.current.resizeRequest &&
            !fitted.current &&
            performance.now() - fittingStarted < 2000
          ) {
            pendingFrame ||= { metadata, bytes };
            setState("Fitting browser…");
            clearTimeout(paintRetry);
            paintRetry = setTimeout(paintLatest, 50);
            return;
          }
          const next = URL.createObjectURL(
            new Blob([bytes], { type: "image/jpeg" }),
          );
          try {
            const decoded = new Image();
            decoded.src = next;
            await decoded.decode();
            if (!alive) {
              URL.revokeObjectURL(next);
              return;
            }
            const old = url;
            url = next;
            image.current.src = url;
            if (old) URL.revokeObjectURL(old);
            first = false;
            failures = 0;
            setFrameReady(true);
            setLoaded(true);
            setState("Live view");
            callbacks.current.onStatus?.("Live view");
            if (metadata.url) callbacks.current.onURL?.(metadata.url);
          } catch {
            URL.revokeObjectURL(next);
          }
        }
      } finally {
        painting = false;
      }
    }
    async function startStream() {
      if (
        !alive ||
        !streamAddress ||
        streaming ||
        document.hidden ||
        serverStopped.current
      )
        return;
      streaming = true;
      clearTimeout(tick);
      controller?.abort();
      streamController = new AbortController();
      let unsupported = false;
      const streamStarted = performance.now();
      const watch = () => {
        clearTimeout(streamWatchdog);
        streamWatchdog = setTimeout(() => streamController.abort(), 8000);
      };
      watch();
      try {
        await readFrameStream(
          streamAddress,
          streamController.signal,
          (metadata, bytes) => {
            if (!alive) return;
            watch();
            if (bytes) {
              pendingFrame = { metadata, bytes };
              void paintLatest();
            } else {
              if (first && performance.now() - streamStarted > 6000)
                streamController.abort();
              if (metadata.url) callbacks.current.onURL?.(metadata.url);
            }
          },
        );
      } catch (e) {
        unsupported = [400, 401, 403, 404, 405, 501].includes(e.status);
      } finally {
        clearTimeout(streamWatchdog);
        streaming = false;
        if (alive) {
          frame();
          if (!unsupported) streamRetry = setTimeout(startStream, 10000);
        }
      }
    }
    async function frame() {
      if (!alive || streaming) return;
      if (inflight) {
        urgent = true;
        return;
      }
      clearTimeout(tick);
      if (document.hidden) {
        tick = setTimeout(frame, 1000);
        return;
      }
      inflight = true;
      urgent = false;
      controller = new AbortController();
      const started = performance.now(),
        timeout = setTimeout(() => controller.abort(), 6000);
      let next = "";
      try {
        const r = await fetch(frameURL + "?ts=" + Date.now(), {
          cache: "no-store",
          credentials: "same-origin",
          signal: controller.signal,
        });
        if ([404, 410].includes(r.status)) {
          if (
            first &&
            (performance.now() - fittingStarted < 5000 ||
              (callbacks.current.starting &&
                performance.now() - fittingStarted < 120000))
          ) {
            failures++;
            const status = frameURL.includes("workspace-frame")
              ? "Preview is starting…"
              : "Browser is starting…";
            setState(status);
            callbacks.current.onStatus?.(status);
            return;
          }
          serverStopped.current = true;
          queue.current = [];
          setLoaded(false);
          setFrameReady(false);
          const status = frameURL.includes("workspace-frame")
            ? "Workspace stopped. Reopen it from Workspace."
            : "Browser stopped · runtime stopped";
          setState(status);
          callbacks.current.onStatus?.(status);
          return;
        }
        if (!r.ok)
          throw Error(
            [404, 410].includes(r.status)
              ? "Workspace stopped. Reopen it from Workspace."
              : "Live view unavailable",
          );
        next = URL.createObjectURL(await r.blob());
        const decoded = new Image();
        decoded.src = next;
        await decoded.decode();
        if (!alive) return;
        setFrameReady(true);
        if (first && callbacks.current.resizeRequest) {
          // A screenshot can differ on sites without a mobile viewport tag.
          // Wait briefly for the resize acknowledgement, never for pixel equality.
          if (!fitted.current && performance.now() - fittingStarted < 2000) {
            setState("Fitting browser…");
            return;
          }
        }
        first = false;
        const old = url;
        url = next;
        next = "";
        image.current.src = url;
        if (old) URL.revokeObjectURL(old);
        failures = 0;
        setLoaded(true);
        const status =
          Number(r.headers.get("X-Aster-Frame-Age") || 0) > 3000
            ? "Updating the browser view…"
            : "Live view";
        setState(status);
        callbacks.current.onStatus?.(status);
        const u = r.headers.get("X-Aster-Frame-URL");
        if (u) callbacks.current.onURL?.(decodeURIComponent(u));
      } catch (e) {
        if (alive) {
          failures++;
          const status = e.message.includes("stopped")
            ? e.message
            : first
              ? frameURL.includes("workspace-frame")
                ? "Preview is starting…"
                : "Browser is starting…"
              : "Reconnecting…";
          setState(status);
          callbacks.current.onStatus?.(status);
        }
      } finally {
        clearTimeout(timeout);
        if (next) URL.revokeObjectURL(next);
        inflight = false;
        if (alive && !serverStopped.current)
          tick = setTimeout(
            frame,
            urgent
              ? 0
              : failures
                ? Math.min(2500, failures * 350)
                : Math.max(40, 100 - (performance.now() - started)),
          );
      }
    }
    kick.current = () => {
      serverStopped.current = false;
      if (streaming) return;
      urgent = true;
      clearTimeout(tick);
      frame();
    };
    const visible = () => {
      if (document.hidden) {
        streamController?.abort();
        clearTimeout(streamRetry);
      } else if (streamAddress) {
        clearTimeout(streamRetry);
        startStream();
      } else kick.current();
    };
    document.addEventListener("visibilitychange", visible);
    if (streamAddress) startStream();
    else frame();
    return () => {
      alive = false;
      clearTimeout(tick);
      controller?.abort();
      streamController?.abort();
      clearTimeout(streamRetry);
      clearTimeout(streamWatchdog);
      clearTimeout(paintRetry);
      pendingFrame = null;
      if (url) URL.revokeObjectURL(url);
      kick.current = () => {};
      document.removeEventListener("visibilitychange", visible);
    };
  }, [taskId, frameURL, streamURL, active]);
  useEffect(() => {
    if (!active || (!resizeRequest && (!enabled || !frameReady))) return;
    let alive = true,
      inflight = false,
      desired;
    let resizeTimer,
      last = "";
    const send = async () => {
      if (!alive || inflight || !desired || serverStopped.current) return;
      const v = desired,
        key = JSON.stringify(v);
      if (key === last) return;
      if (!callbacks.current.resizeRequest) {
        enqueue("resize", v);
        last = key;
        return;
      }
      inflight = true;
      try {
        await callbacks.current.resizeRequest(v);
        if (!alive) return;
        last = key;
        fitted.current = true;
        kick.current();
      } catch {
        // A display resize is idempotent; retry after startup/transient failures.
        // Never retry pointer, typing or other user actions here.
      } finally {
        inflight = false;
        if (alive && JSON.stringify(desired) !== last) {
          clearTimeout(resizeTimer);
          resizeTimer = setTimeout(send, 700);
        }
      }
    };
    const resize = () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => {
        desired = surfaceViewport(host.current, displayMode);
        if (!desired) return;
        send();
      }, 100);
    };
    const observer = new ResizeObserver(resize);
    observer.observe(host.current);
    window.addEventListener("resize", resize);
    window.visualViewport?.addEventListener("resize", resize);
    resize();
    return () => {
      alive = false;
      clearTimeout(resizeTimer);
      observer.disconnect();
      window.removeEventListener("resize", resize);
      window.visualViewport?.removeEventListener("resize", resize);
    };
  }, [enabled, frameReady, active, taskId, !!resizeRequest, displayMode]);
  useEffect(() => {
    const el = host.current;
    if (!el) return;
    const wheel = (e) => {
      if (!callbacks.current.enabled) return;
      e.preventDefault();
      enqueue("scroll", {
        x:
          e.deltaX *
          (e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? el.clientWidth : 1),
        delta:
          e.deltaY *
          (e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? el.clientHeight : 1),
        atX: coords(e).x,
        atY: coords(e).y,
      });
    };
    el.addEventListener("wheel", wheel, { passive: false });
    return () => el.removeEventListener("wheel", wheel);
  }, [loaded]);
  useEffect(() => {
    const el = keyboard.current;
    const beforeInput = (e) => {
      if (e.isComposing || composing.current) return;
      const keys = {
        deleteContentBackward: "Backspace",
        deleteContentForward: "Delete",
        insertLineBreak: "Enter",
        insertParagraph: "Enter",
      };
      if (keys[e.inputType]) {
        e.preventDefault();
        enqueue("key", { key: keys[e.inputType] });
      }
    };
    el?.addEventListener("beforeinput", beforeInput);
    return () => el?.removeEventListener("beforeinput", beforeInput);
  }, [loaded]);
  function coords(e) {
    const img = image.current,
      r = img.getBoundingClientRect();
    return framePoint(
      r,
      img.naturalWidth,
      img.naturalHeight,
      e.clientX,
      e.clientY,
    );
  }

  function key(e) {
    if (!enabled || composing.current || e.isComposing) return;
    if (e.altKey && e.key === "Escape") {
      e.currentTarget.blur();
      return;
    }
    if (
      [
        "Shift",
        "Control",
        "Alt",
        "Meta",
        "CapsLock",
        "Dead",
        "Process",
      ].includes(e.key)
    )
      return;
    if (
      (e.ctrlKey || e.metaKey) &&
      ["c", "v", "x"].includes(e.key.toLowerCase())
    )
      return;
    e.preventDefault();
    if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey)
      enqueue("text", { text: e.key });
    else
      enqueue("key", {
        key: [
          e.ctrlKey || e.metaKey ? "Control" : null,
          e.altKey ? "Alt" : null,
          e.shiftKey ? "Shift" : null,
          e.key === " " ? "Space" : e.key,
        ]
          .filter(Boolean)
          .join("+"),
      });
  }
  const paste = (e) => {
    e.preventDefault();
    enqueue("text", {
      text: e.clipboardData.getData("text/plain").slice(0, 12000),
    });
  };
  async function copy(e, cut = false) {
    e.preventDefault();
    if (!enabled) return;
    try {
      await drain();
      const r = await dispatch("selection");
      await navigator.clipboard.writeText(r?.text || "");
      if (cut && r?.text) enqueue("key", { key: "Backspace" });
    } catch {
      callbacks.current.notify?.("Clipboard access is unavailable.");
    }
  }
  return (
    <>
      <div
        className="preview-display-bar"
        role="group"
        aria-label="Preview display mode"
      >
        <span>Display</span>
        {["auto", "desktop", "mobile"].map((mode) => (
          <button
            key={mode}
            type="button"
            aria-pressed={displayMode === mode}
            title="Changes the display without reloading. Reload if the site serves a separate mobile version."
            onClick={() => setDisplayMode(mode)}
          >
            {mode[0].toUpperCase() + mode.slice(1)}
          </button>
        ))}
        <small>
          {displayMode === "auto"
            ? "Fits your device"
            : displayMode === "desktop"
              ? "Desktop layout"
              : "Mobile layout"}
        </small>
      </div>
      <div
        className="remote-surface preview-surface"
        ref={host}
        tabIndex={enabled ? 0 : -1}
        role="application"
        aria-label={label}
        onKeyDown={key}
        onCompositionStart={() => {
          composing.current = true;
        }}
        onCompositionEnd={(e) => {
          composing.current = false;
          enqueue("text", { text: e.data });
        }}
        onPaste={paste}
        onCopy={copy}
        onCut={(e) => copy(e, true)}
        onContextMenu={(e) => e.preventDefault()}
        onPointerDown={(e) => {
          if (!enabled || e.button !== 0 || !loaded || gesture.current) return;
          e.preventDefault();
          if (document.activeElement !== keyboard.current)
            host.current.focus({ preventScroll: true });
          e.currentTarget.setPointerCapture(e.pointerId);
          gesture.current = {
            id: e.pointerId,
            x: e.clientX,
            y: e.clientY,
            lastX: e.clientX,
            lastY: e.clientY,
            touch: e.pointerType === "touch",
            moved: false,
          };
          if (drag && e.pointerType !== "touch")
            enqueue("down", {
              ...coords(e),
              count: Math.min(2, e.detail || 1),
            });
        }}
        onPointerMove={(e) => {
          const g = gesture.current;
          if (g && g.id !== e.pointerId) return;
          if (g?.touch) {
            const distance = Math.hypot(e.clientX - g.x, e.clientY - g.y);
            if (distance > 8) g.moved = true;
            if (g.moved) {
              enqueue("scroll", {
                x:
                  ((g.lastX - e.clientX) * image.current.naturalWidth) /
                  image.current.getBoundingClientRect().width,
                delta:
                  ((g.lastY - e.clientY) * image.current.naturalHeight) /
                  image.current.getBoundingClientRect().height,
                atX: coords(e).x,
                atY: coords(e).y,
              });
              g.lastX = e.clientX;
              g.lastY = e.clientY;
            }
          } else if (loaded && e.pointerType !== "touch")
            enqueue("move", coords(e));
        }}
        onPointerUp={(e) => {
          const g = gesture.current;
          if (!g || g.id !== e.pointerId) return;
          gesture.current = null;
          if (g.touch) {
            if (!g.moved) enqueue("pointer", { ...coords(e), touch: true });
          } else
            enqueue(drag ? "up" : "pointer", {
              ...coords(e),
              count: Math.min(2, e.detail || 1),
            });
        }}
        onPointerCancel={(e) => {
          if (gesture.current?.id !== e.pointerId) return;
          if (gesture.current && !gesture.current.touch && drag)
            enqueue("up", coords(e));
          gesture.current = null;
        }}
      >
        <img
          ref={image}
          alt={imageLabel}
          draggable={false}
          onLoad={fitRenderedFrame}
          style={{ visibility: loaded ? "visible" : "hidden" }}
        />
        {!loaded && (
          <div className="preview-connecting">
            <Icon name="browser" size={30} />
            <span>{state}</span>
          </div>
        )}
      </div>
      <textarea
        className="remote-keyboard"
        ref={keyboard}
        aria-label="Remote keyboard"
        autoCapitalize="none"
        autoComplete="off"
        autoCorrect="off"
        spellCheck={false}
        disabled={!enabled}
        onPaste={paste}
        onCompositionStart={() => {
          composing.current = true;
        }}
        onCompositionEnd={(e) => {
          composing.current = false;
          enqueue("text", { text: e.data });
          e.currentTarget.value = "";
        }}
        onInput={(e) => {
          if (!composing.current && !e.nativeEvent.isComposing) {
            const text = e.currentTarget.value;
            if (text) enqueue("text", { text });
            e.currentTarget.value = "";
          }
        }}
      />
      {inputError && (
        <div className="preview-error" role="alert">
          {inputError}
          <button
            className="button small"
            onClick={() => {
              setInputError("");
              kick.current();
            }}
          >
            Refresh view
          </button>
        </div>
      )}
    </>
  );
}
