"use client";
import { randomId } from "../lib/id.mjs";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  uploadPart,
  defaults,
  setCSRF,
  discardTemporary,
} from "../lib/api";
import {
  Logo,
  Icon,
  IconButton,
  Modal,
  Markdown,
  Sources,
  CopyButton,
  ImageStrip,
} from "./UI";
import {
  uploadDocument,
  ARCHIVE_EXTENSIONS,
  isArchive,
} from "../lib/document-upload.mjs";
import { DocumentAttachments } from "./DocumentAttachments";
import { ConversationInfo } from "./ConversationInfo";
import { ModelPicker } from "./ModelPicker";
import { remainingSources } from "../lib/sources.mjs";
import { CommunitySettings } from "./CommunitySettings";
import { Auth } from "./Auth";

import { Usage } from "./Usage";
import { AppPreview } from "./AppPreview";
import { Development } from "./Development";
import { Settings, Collection } from "./Settings";
import { PersonalDetails } from "./PersonalDetails";
import { Skills } from "./Skills";
import { Schedules } from "./Schedules";
import { Activity, Approval, BrowserPanel } from "./Workspace";
function routeNow() {
  const h = decodeURIComponent(location.hash.slice(1));
  if (
    [
      "settings",
      "memory",
      "schedules",
      "usage",
      "details",
      "skills",
      "admin",
      "help",
    ].includes(h)
  )
    return { view: h, id: null };
  const match = h.match(
    /^chat\/([a-zA-Z0-9_-]+)(?:\?preview=(\d+)(?:&path=([^#]*))?)?$/,
  );
  if (match)
    return {
      view: "chat",
      id: match[1],
      preview: Number(match[2]) || null,
      path: match[3] ? decodeURIComponent(match[3]) : "/",
    };
  return { view: "chat", id: null };
}
async function imageAttachment(file) {
  if (
    !["image/png", "image/jpeg", "image/webp", "image/gif"].includes(file?.type)
  )
    throw new Error("Choose a PNG, JPEG, WebP or GIF image.");
  if (file.size > 20 * 1024 * 1024)
    throw new Error("Images must be smaller than 20 MB.");
  if (file.size > 6 * 1024 * 1024) {
    if (file.type === "image/gif")
      throw new Error(
        "Animated GIFs must be smaller than 6 MB. Upload a still image instead.",
      );
    const bitmap = await createImageBitmap(file),
      canvas = document.createElement("canvas");
    const scale = Math.min(1, 2560 / Math.max(bitmap.width, bitmap.height));
    canvas.width = Math.max(1, Math.round(bitmap.width * scale));
    canvas.height = Math.max(1, Math.round(bitmap.height * scale));
    const context = canvas.getContext("2d");
    context.fillStyle = "#fff";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close();
    const resized = await new Promise((resolve) =>
      canvas.toBlob(resolve, "image/jpeg", 0.9),
    );
    if (!resized || resized.size > 6 * 1024 * 1024)
      throw new Error(
        "This image could not be resized for upload. Try a smaller image.",
      );
    file = new File([resized], file.name, { type: "image/jpeg" });
  }
  const dataUrl = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error("This image could not be read."));
    reader.readAsDataURL(file);
  });
  return {
    id: `${file.name}-${file.lastModified}-${file.size}-${randomId()}`,
    name: file.name,
    type: file.type,
    dataUrl,
  };
}
function Composer({
  mode,
  setMode,
  locked,
  value,
  setValue,
  onSubmit,
  busy,
  blocked,
  prefs,
  notify,
  images = [],
  setImages,
  modelOptions,
  modelChoice,
  setModelChoice,
  documents = [],
  setDocuments,
  temporary = false,
  fileLimit = 100,
}) {
  const uploads = useRef(new Map());
  useEffect(
    () => () => {
      const ids = new Set(uploads.current.keys());
      for (const controller of uploads.current.values()) controller.abort();
      if (ids.size)
        setDocuments((old) =>
          old.map((d) =>
            ids.has(d.id)
              ? {
                  ...d,
                  status: "failed",
                  error: "Upload paused. Retry to resume.",
                }
              : d,
          ),
        );
    },
    [],
  );
  const uploadPending = documents.some((d) => d.status !== "ready");
  const ref = useRef(),
    file = useRef();
  useEffect(() => {
    const e = ref.current;
    e.style.height = "auto";
    e.style.height = Math.min(200, e.scrollHeight) + "px";
  }, [value]);
  async function attachment(e) {
    const selected = [...(e.target.files || [])];
    e.target.value = "";
    await addAttachments(selected);
  }
  async function addAttachments(selected) {
    const imageFiles = selected.filter((f) => f.type?.startsWith("image/"));
    const textFiles = selected.filter((f) => !f.type?.startsWith("image/"));
    if (imageFiles.length) {
      try {
        const next = await Promise.all(imageFiles.map(imageAttachment));
        setImages((old) => [...old, ...next].slice(0, 8));
        if (next.length + images.length > 8)
          notify("You can attach up to 8 images per message.");
      } catch (e) {
        notify(e.message);
      }
    }
    if (temporary && textFiles.length) {
      notify(
        "Turn off temporary Chat to attach documents. Images are still supported.",
      );
      return;
    }
    if (documents.length + textFiles.length > 12) {
      notify("Attach up to 12 documents per message.");
      return;
    }
    for (const f of textFiles) {
      if (isArchive(f.name) && mode !== "work") {
        notify("Switch to Work mode to upload archives.");
        continue;
      }
      if (f.size > fileLimit * 1048576) {
        notify(`Files must be smaller than ${fileLimit} MB.`);
        continue;
      }
      const item = {
        id: randomId(),
        name: f.name,
        size: f.size,
        status: "uploading",
        received: 0,
        file: f,
      };
      setDocuments((old) => [...old, item]);
      startUpload(item);
    }
  }
  async function startUpload(item) {
    const controller = new AbortController();
    uploads.current.set(item.id, controller);
    const update = (data) =>
      setDocuments((old) =>
        old.map((d) => (d.id === item.id ? { ...d, ...data } : d)),
      );
    update({ status: "uploading", error: "" });
    try {
      await uploadDocument(item.file, item.id, {
        request: api,
        put: uploadPart,
        onUpdate: update,
        signal: controller.signal,
        mode,
      });
    } catch (e) {
      if (!controller.signal.aborted)
        update({ status: "failed", error: e.message });
    } finally {
      uploads.current.delete(item.id);
    }
  }
  function removeDocument(item) {
    uploads.current.get(item.id)?.abort();
    setDocuments((old) => old.filter((d) => d.id !== item.id));
    api("attachments/" + item.id, {}, "DELETE").catch(() => {});
  }

  function paste(e) {
    const files = [...(e.clipboardData?.items || [])]
      .map((item) => (item.kind === "file" ? item.getAsFile() : null))
      .filter(Boolean);
    if (files.length) {
      e.preventDefault();
      addAttachments(files);
    }
  }
  return (
    <form
      className={"composer " + (busy ? "is-busy" : "")}
      onSubmit={(e) => {
        e.preventDefault();
        if (!busy && !blocked && !uploadPending) onSubmit();
      }}
    >
      <label htmlFor="prompt" className="sr-only">
        Message OwnCMD
      </label>
      <textarea
        id="prompt"
        ref={ref}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder={
          blocked
            ? "Respond to the request above to continue…"
            : locked
              ? "Continue the conversation…"
              : mode === "work"
                ? "Describe what you’d like to get done…"
                : "Ask anything, or explore an idea…"
        }
        rows={2}
        onPaste={paste}
        onKeyDown={(e) => {
          if (e.nativeEvent.isComposing) return;
          if (
            e.key === "Enter" &&
            !e.shiftKey &&
            (prefs.send_enter || e.ctrlKey || e.metaKey)
          ) {
            e.preventDefault();
            if (!busy && !blocked && !uploadPending) onSubmit();
          }
        }}
      />
      <DocumentAttachments
        items={documents}
        onRetry={startUpload}
        onRemove={removeDocument}
      />
      <div className="composer-toolbar">
        <div className="composer-left">
          <input
            ref={file}
            type="file"
            hidden
            tabIndex={-1}
            multiple
            accept={
              "image/*,text/*,.pdf,.docx,.xlsx,.pptx,.md,.csv,.tsv,.json,.xml,.log,.py,.js,.ts,.yaml,.yml,.html,.css,.ipynb,.toml,.go,.rs,.java,.cpp,.h,.sh,.php,.rb,.swift,.kt,.vue,.svelte" +
              (mode === "work" ? "," + ARCHIVE_EXTENSIONS.join(",") : "")
            }
            onChange={attachment}
          />
          <IconButton
            name="attach"
            label={
              mode === "work"
                ? "Attach images, documents or archives"
                : "Attach images or documents"
            }
            onClick={() => file.current.click()}
          />
          {images.length > 0 && (
            <span className="attachment-count">
              {images.length} image{images.length === 1 ? "" : "s"}
            </span>
          )}
          {locked ? (
            <span className="mode-label">
              <Icon name={mode === "work" ? "work" : "chat"} size={15} />
              {mode === "work" ? "Work" : "Chat"}
            </span>
          ) : (
            <div className="mode-switch" aria-label="Conversation mode">
              {["chat", "work"].map((m) => (
                <button
                  key={m}
                  type="button"
                  aria-pressed={mode === m}
                  onClick={() => setMode(m)}
                >
                  <Icon name={m} size={15} />
                  {m === "chat" ? "Chat" : "Work"}
                </button>
              ))}
            </div>
          )}
          {modelOptions && (
            <ModelPicker
              options={modelOptions}
              value={modelChoice || "auto"}
              onChange={setModelChoice}
            />
          )}
        </div>
        <button
          type="submit"
          className="send"
          aria-label="Send message"
          disabled={
            busy ||
            blocked ||
            uploadPending ||
            (!value.trim() && !images.length && !documents.length)
          }
        >
          {busy ? (
            <span className="spinner" />
          ) : (
            <Icon name="arrow" size={20} />
          )}
        </button>
      </div>
      {images.length > 0 && (
        <div className="composer-attachments">
          {images.map((image, index) => (
            <div className="attachment-card" key={image.id}>
              <img src={image.dataUrl} alt={image.name} />
              <span title={image.name}>{image.name}</span>
              <button
                type="button"
                aria-label={`Remove ${image.name}`}
                onClick={() =>
                  setImages((old) => old.filter((_, i) => i !== index))
                }
              >
                <Icon name="close" size={13} />
              </button>
            </div>
          ))}
        </div>
      )}
    </form>
  );
}
export default function App() {
  const [mobile, setMobile] = useState(false),
    [workspaceOpen, setWorkspaceOpen] = useState(false),
    [previewPort, setPreviewPort] = useState(null),
    [previewPath, setPreviewPath] = useState("/"),
    [workspaceState, setWorkspaceState] = useState(null);
  const drawer = useRef();
  const [draftDocuments, setDraftDocuments] = useState({}),
    [savedDocuments, setSavedDocuments] = useState([]);
  const [modelOptions, setModelOptions] = useState(null),
    [modelChoice, setModelChoice] = useState("auto");
  const [me, setMe] = useState(null),
    [booting, setBooting] = useState(true),
    [bootError, setBootError] = useState(""),
    [prefs, setPrefs] = useState(defaults),
    [route, setRoute] = useState({ view: "chat", id: null }),
    [history, setHistory] = useState([]),
    [historyError, setHistoryError] = useState(""),
    [search, setSearch] = useState(""),
    [menu, setMenu] = useState(false),
    [mode, setMode] = useState("chat"),
    [task, setTask] = useState(null),
    [taskError, setTaskError] = useState(""),
    [drafts, setDrafts] = useState({}),
    [draftImages, setDraftImages] = useState({}),
    [pending, setPending] = useState({}),
    [optimistic, setOptimistic] = useState(null),
    [delta, setDelta] = useState(""),
    [streamRender, setStreamRender] = useState({}),
    [temporaryChat, setTemporaryChat] = useState(false),
    [dismissedWork, setDismissedWork] = useState(new Set()),
    [handoffBusy, setHandoffBusy] = useState(false),
    [activity, setActivity] = useState(""),
    [connection, setConnection] = useState("Connecting"),
    [toast, setToast] = useState(""),
    [deleting, setDeleting] = useState(null),
    [actionBusy, setActionBusy] = useState(false),
    [browserClosed, setBrowserClosed] = useState(false),
    [jump, setJump] = useState(false);
  const creationRef = useRef(null);
  const streamRef = useRef({}),
    temporaryIds = useRef(new Set());
  const routeRef = useRef(route),
    taskRef = useRef(task),
    session = useRef(0),
    submitLocks = useRef(new Set()),
    request = useRef(0),
    scroll = useRef(),
    stick = useRef(true),
    timer = useRef(),
    mounted = useRef(true),
    lastRefresh = useRef(0);
  routeRef.current = route;
  taskRef.current = task;
  const notify = useCallback((message) => {
    setToast(message);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setToast(""), 6500);
  }, []);
  const signout = useCallback((preserveInvite = false) => {
    session.current++;
    temporaryIds.current.forEach(discardTemporary);
    temporaryIds.current.clear();
    setTemporaryChat(false);
    setDismissedWork(new Set());
    if (!preserveInvite || !location.hash.startsWith("#invite="))
      window.history.replaceState(null, "", location.pathname);
    setRoute({ view: "chat", id: null });
    setCSRF("");
    setMe(null);
    setHistory([]);
    setTask(null);
    setDrafts({});
    setDraftImages({});
    setDraftDocuments({});
    setSavedDocuments([]);
    setModelOptions(null);
    setModelChoice("auto");
    setPending({});
    setOptimistic(null);
    setDelta("");
    submitLocks.current.clear();
    setBooting(false);
  }, []);
  const refreshHistory = useCallback(async () => {
    const s = session.current;
    try {
      const rows = await api("tasks");
      if (s === session.current) {
        setHistory(rows);
        setHistoryError("");
      }
    } catch (e) {
      if (s === session.current) setHistoryError(e.message);
    }
  }, []);
  const boot = useCallback(async () => {
    setBootError("");
    try {
      const user = await api("me");
      setCSRF(user.csrf);
      setMe(user);
      const settings = await api("settings");
      setPrefs({ ...defaults, ...settings });
      await refreshHistory();
    } catch (e) {
      if (e.message === "Please sign in") signout(true);
      else {
        setBootError(e.message);
      }
    } finally {
      setBooting(false);
    }
  }, [refreshHistory, signout]);
  useEffect(() => {
    mounted.current = true;
    setRoute(routeNow());
    boot();
    const hash = () => {
        setRoute(routeNow());
        setMenu(false);
      },
      out = () => signout();
    window.addEventListener("hashchange", hash);
    window.addEventListener("aster:signout", out);
    return () => {
      mounted.current = false;
      clearTimeout(timer.current);
      window.removeEventListener("hashchange", hash);
      window.removeEventListener("aster:signout", out);
    };
  }, [boot, signout]);
  useEffect(() => {
    if (me && route.view === "admin" && me.account?.role !== "admin") {
      window.history.replaceState(
        null,
        "",
        location.pathname + location.search,
      );
      setRoute({ view: "chat", id: null });
    }
  }, [me?.account?.role, route.view, me?.email]);
  useEffect(() => {
    const media = matchMedia("(max-width: 720px)");
    const change = () => setMobile(media.matches);
    change();
    media.addEventListener("change", change);
    return () => media.removeEventListener("change", change);
  }, []);
  useEffect(() => {
    if (!menu || !mobile) return;
    const previous = document.activeElement;
    drawer.current?.querySelector("button")?.focus();
    const trap = (e) => {
      if (e.key !== "Tab") return;
      const items = [
        ...drawer.current.querySelectorAll("a,button,input"),
      ].filter(
        (el) =>
          !el.disabled &&
          el.getClientRects().length &&
          getComputedStyle(el).visibility !== "hidden",
      );
      if (!items.length) return;
      const first = items[0],
        last = items.at(-1);
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", trap);
    return () => {
      document.removeEventListener("keydown", trap);
      if (previous?.isConnected) previous.focus();
    };
  }, [menu, mobile]);
  useEffect(() => {
    const media = matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      document.documentElement.dataset.theme =
        prefs.theme === "system"
          ? media.matches
            ? "dark"
            : "light"
          : prefs.theme;
      document.documentElement.dataset.font = prefs.font;
      document.documentElement.dataset.fontSize = prefs.font_size;
      document.documentElement.dataset.density = prefs.density;
      document.documentElement.dataset.reduceMotion = String(
        prefs.reduce_motion,
      );
    };
    apply();
    media.addEventListener("change", apply);
    return () => media.removeEventListener("change", apply);
  }, [prefs]);
  useEffect(() => {
    const bar = document.querySelector(".topbar");
    if (!bar) return;
    const measure = () =>
      document.documentElement.style.setProperty(
        "--app-topbar-height",
        Math.ceil(bar.getBoundingClientRect().height) + "px",
      );
    const observer = new ResizeObserver(measure);
    observer.observe(bar);
    measure();
    return () => observer.disconnect();
  }, [booting, me?.email]);
  useEffect(() => {
    const id = route.id;
    if (!id?.startsWith("tmp-")) return;
    temporaryIds.current.add(id);
    return () => {
      discardTemporary(id);
      temporaryIds.current.delete(id);
      setDrafts((old) => {
        const next = { ...old };
        delete next[id];
        return next;
      });
      setDraftImages((old) => {
        const next = { ...old };
        delete next[id];
        return next;
      });
    };
  }, [route.id]);
  useEffect(() => {
    const close = () => temporaryIds.current.forEach(discardTemporary);
    window.addEventListener("pagehide", close);
    return () => window.removeEventListener("pagehide", close);
  }, []);
  function changeMode(next) {
    setMode(next);
    if (next === "work") setTemporaryChat(false);
    creationRef.current = null;
  }
  function toggleTemporary() {
    setTemporaryChat(!(activeTask?.temporary || temporaryChat));
    setDrafts((old) => ({ ...old, new: "" }));
    setDraftImages((old) => ({ ...old, new: [] }));
    setDraftDocuments((old) => ({ ...old, new: [] }));
    creationRef.current = null;
    setMode("chat");
    newConversation();
  }
  async function handoff(action) {
    const proposal = activeTask?.work_suggestion;
    if (!proposal || handoffBusy) return;
    setHandoffBusy(true);
    try {
      const result = await api(`tasks/${activeTask.id}/work-handoff`, {
        proposal_id: proposal.id,
        action,
      });
      setDismissedWork((old) => new Set([...old, proposal.id]));
      if (action === "accept") {
        setTemporaryChat(false);
        setMode("work");
        go("chat", result.id);
        refreshHistory();
      }
    } catch (e) {
      notify(e.message);
    } finally {
      setHandoffBusy(false);
    }
  }
  function go(view = "chat", id = null) {
    const hash = view === "chat" ? (id ? "chat/" + id : "") : view;
    if (id?.startsWith("tmp-") || routeRef.current.id?.startsWith("tmp-"))
      window.history.replaceState(
        null,
        "",
        location.pathname + location.search + (hash ? "#" + hash : ""),
      );
    else historyPush(hash);
    setRoute({ view, id });
    setMenu(false);
  }
  function historyPush(hash) {
    if (location.hash.slice(1) !== hash) location.hash = hash;
  }
  function newConversation() {
    setTask(null);
    setOptimistic(null);
    creationRef.current = null;
    go();
    requestAnimationFrame(() => document.getElementById("prompt")?.focus());
  }
  useEffect(() => {
    const key = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setMenu(true);
        requestAnimationFrame(() =>
          document.getElementById("history-search")?.focus(),
        );
      }
      if (
        (e.metaKey || e.ctrlKey) &&
        e.shiftKey &&
        e.key.toLowerCase() === "o"
      ) {
        e.preventDefault();
        newConversation();
      }
      if (e.key === "Escape") setMenu(false);
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  });
  useEffect(() => {
    if (!me) return;
    document.title =
      (route.view === "chat"
        ? route.id
          ? task?.title || "Conversation"
          : "New conversation"
        : route.view === "schedules"
          ? "Scheduled work"
          : route.view === "details"
            ? "Personal details"
            : route.view[0].toUpperCase() + route.view.slice(1)) + " — OwnCMD";
  }, [route, task?.title, me]);
  useEffect(() => {
    setTask(null);
    setTaskError("");
    setDelta("");
    streamRef.current = {};
    setStreamRender({});
    setActivity("");
    setBrowserClosed(false);
    setWorkspaceOpen(false);
    setPreviewPort(route.preview || null);
    setPreviewPath(route.path || "/");
    setJump(false);
    stick.current = true;
    const id = route.id;
    if (!me || route.view !== "chat" || !id) return;
    let alive = true,
      stream,
      poll,
      scheduled,
      busy = false,
      lastEvent = 0;
    const generation = ++request.current;
    async function update() {
      if (!alive || busy) return;
      busy = true;
      try {
        const data = await api("tasks/" + id);
        if (!alive || generation !== request.current) return;
        setTask(data);
        setMode(data.mode);
        setTemporaryChat(!!data.temporary);
        setTaskError("");
        if (
          ["completed", "failed", "cancelled", "paused"].includes(
            data.status,
          ) &&
          !data.busy
        ) {
          if (
            !streamRef.current.id ||
            data.messages?.some((m) => m.id === streamRef.current.id) ||
            data.status === "failed"
          ) {
            setDelta("");
            setActivity("");
          }
        }
        if (Date.now() - lastRefresh.current > 5000) {
          lastRefresh.current = Date.now();
          refreshHistory();
        }
        return data;
      } catch (e) {
        if (alive) setTaskError(e.message);
      } finally {
        busy = false;
      }
    }
    function connect() {
      if (!alive) return;
      stream = new EventSource(
        "/api/tasks/" + encodeURIComponent(id) + "/stream?after=" + lastEvent,
      );
      stream.onopen = () => alive && setConnection("Live");
      stream.onerror = () => alive && setConnection("Reconnecting");
      stream.addEventListener("activity", (e) => {
        if (!alive) return;
        let event;
        try {
          event = JSON.parse(e.data);
        } catch {
          return;
        }
        if (event.id <= lastEvent) return;
        lastEvent = Math.max(lastEvent, event.id || 0);
        if (
          event.body?.turn_id &&
          taskRef.current?.messages?.some((m) => m.id === event.body.turn_id)
        )
          return;
        if (event.kind === "chat_delta") {
          streamRef.current = {
            id: event.body?.turn_id,
            html: event.body?.html,
          };
          setStreamRender(streamRef.current);
          setDelta((v) => v + (event.body?.delta || ""));
          setActivity("");
          return;
        }
        if (event.kind === "chat_search") {
          setDelta("");
          setActivity("Searching the web");
        }
        if (event.kind === "chat_thinking") {
          if (event.body?.reset) setDelta("");
          streamRef.current = { id: event.body?.turn_id };
          setStreamRender(streamRef.current);
          setActivity(event.body?.text || "Thinking");
        }
        if (["chat_completed", "chat_failed"].includes(event.kind)) {
          // Keep the streamed reply mounted until the saved message arrives.
          setActivity("");
        }
        if (event.kind === "title_updated") refreshHistory();
        clearTimeout(scheduled);
        scheduled = setTimeout(update, 100);
      });
      stream.addEventListener("state", () => {
        clearTimeout(scheduled);
        scheduled = setTimeout(update, 100);
      });
      stream.addEventListener("reconnect", () => {
        stream.close();
        connect();
      });
    }
    setConnection("Connecting");
    update().then((data) => {
      if (!alive) return;
      lastEvent = Math.max(0, ...(data?.events || []).map((e) => e.id));
      if (data?.mode === "chat" && (data.busy || data.status === "running")) {
        const events = data.events || [];
        let boundary = -1;
        for (let i = events.length - 1; i >= 0; i--)
          if (
            [
              "chat_completed",
              "chat_failed",
              "chat_search",
              "chat_thinking",
            ].includes(events[i].kind)
          ) {
            boundary = i;
            break;
          }
        const latestDelta = events
          .slice(boundary + 1)
          .filter((e) => e.kind === "chat_delta")
          .at(-1);
        streamRef.current = {
          id: latestDelta?.body?.turn_id,
          html: latestDelta?.body?.html,
        };
        setStreamRender(streamRef.current);
        setDelta(
          events
            .slice(boundary + 1)
            .filter((e) => e.kind === "chat_delta")
            .map((e) => e.body?.delta || "")
            .join(""),
        );
      }
      connect();
    });
    poll = setInterval(update, 5000);
    return () => {
      alive = false;
      stream?.close();
      clearInterval(poll);
      clearTimeout(scheduled);
    };
  }, [route.view, route.id, me?.email, refreshHistory]);
  useEffect(() => {
    if (!me?.email) return;
    let alive = true;
    const timer = setInterval(() => {
      if (document.hidden) return;
      api("me")
        .then((user) => {
          if (alive) setMe(user);
        })
        .catch(() => {});
    }, 15000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [me?.email]);
  const activeTask = task?.id === route.id ? task : null;
  useEffect(() => {
    if (stick.current && scroll.current)
      scroll.current.scrollTop = scroll.current.scrollHeight;
  }, [JSON.stringify(activeTask?.messages), delta, optimistic, activity]);
  useEffect(() => {
    if (!me?.email) return;
    let alive = true,
      inflight = false;
    async function refreshModels() {
      if (inflight || document.hidden) return;
      inflight = true;
      try {
        const r = await api("models");
        if (alive)
          setModelOptions((old) =>
            JSON.stringify(old) === JSON.stringify(r) ? old : r,
          );
      } catch {
      } finally {
        inflight = false;
      }
    }
    refreshModels();
    const timer = setInterval(refreshModels, 15000);
    window.addEventListener("focus", refreshModels);
    window.addEventListener("aster:policy-changed", refreshModels);
    document.addEventListener("visibilitychange", refreshModels);
    return () => {
      alive = false;
      clearInterval(timer);
      window.removeEventListener("focus", refreshModels);
      window.removeEventListener("aster:policy-changed", refreshModels);
      document.removeEventListener("visibilitychange", refreshModels);
    };
  }, [me?.email, JSON.stringify(me?.account?.models)]);
  useEffect(() => {
    setModelChoice(activeTask?.model_choice || "auto");
  }, [route.id, activeTask?.model_choice, mode]);
  const draftKey = route.id || "new";
  const draft = drafts[draftKey] || "";
  function setDraft(value) {
    setDrafts((old) => ({
      ...old,
      [draftKey]:
        typeof value === "function" ? value(old[draftKey] || "") : value,
    }));
  }
  const images = draftImages[draftKey] || [];
  const documents = draftDocuments[draftKey] || [];
  function setDocuments(value) {
    setDraftDocuments((old) => ({
      ...old,
      [draftKey]:
        typeof value === "function" ? value(old[draftKey] || []) : value,
    }));
  }
  useEffect(() => {
    let alive = true;
    setSavedDocuments([]);
    if (route.id && !route.id.startsWith("tmp-"))
      api("tasks/" + route.id + "/attachments")
        .then((r) => {
          if (alive) setSavedDocuments(r.attachments);
        })
        .catch(() => {});
    return () => {
      alive = false;
    };
  }, [route.id, activeTask?.messages?.length]);
  function setImages(value) {
    setDraftImages((old) => ({
      ...old,
      [draftKey]:
        typeof value === "function" ? value(old[draftKey] || []) : value,
    }));
  }
  function showInputRequest() {
    setBrowserClosed(true);
    requestAnimationFrame(() => {
      const request = document.getElementById("task-input-request");
      request?.scrollIntoView({ block: "center", behavior: "instant" });
      request?.focus({ preventScroll: true });
    });
  }
  async function refreshTask(id) {
    const d = await api("tasks/" + id);
    if (routeRef.current.id === id && routeRef.current.view === "chat") {
      setTask(d);
      if (!d.busy && ["completed", "failed"].includes(d.status)) {
        setDelta("");
        setActivity("");
      }
    }
    return d;
  }
  async function send() {
    const prompt = draft.trim(),
      requestPrompt = prompt || "Please review the attached files.",
      attachedDocuments = documents,
      attachmentPayload = documents.map((d) => d.id),
      attachedImages = images,
      imagePayload = attachedImages.map((image) => ({
        data_url: image.dataUrl,
        name: image.name,
        mime_type: image.type,
      })),
      startKey = draftKey,
      current = activeTask,
      chosenMode = current?.mode || mode,
      s = session.current;
    if (
      chosenMode !== "work" &&
      attachedDocuments.some((d) => isArchive(d.name))
    ) {
      notify("Switch to Work mode to send archive attachments.");
      return;
    }
    if (
      (!prompt && !attachedImages.length && !attachedDocuments.length) ||
      documents.some((d) => d.status !== "ready") ||
      submitLocks.current.has(startKey) ||
      current?.status === "approval" ||
      (current?.mode === "chat" &&
        (current.busy || current.status === "running"))
    )
      return;
    if (prompt.length > 24000) {
      notify(
        "Messages can contain up to 24,000 characters. Shorten the text or attachment.",
      );
      return;
    }
    submitLocks.current.add(startKey);
    setPending((p) => ({ ...p, [startKey]: true }));
    setDraft("");
    setImages([]);
    setDocuments([]);
    let id = route.id,
      created = Boolean(route.id);
    try {
      if (!id) {
        const previous = creationRef.current;
        id =
          previous?.prompt === requestPrompt &&
          previous?.mode === chosenMode &&
          previous?.temporary === temporaryChat
            ? previous.id
            : randomId();
        creationRef.current = {
          id,
          prompt: requestPrompt,
          mode: chosenMode,
          temporary: temporaryChat,
        };
        const createdTask = await api("tasks", {
          id,
          prompt: requestPrompt,
          mode: chosenMode,
          model: modelChoice,
          attachments: attachmentPayload,
          images: imagePayload,
          temporary: chosenMode === "chat" && temporaryChat,
        });
        id = createdTask.id;
        if (id.startsWith("tmp-")) temporaryIds.current.add(id);
        created = true;
        creationRef.current = null;
        if (
          s !== session.current ||
          (id.startsWith("tmp-") &&
            (routeRef.current.view !== "chat" || routeRef.current.id))
        ) {
          discardTemporary(id);
          return;
        }
        submitLocks.current.add(id);
        setPending((p) => ({ ...p, [id]: true }));
        if (routeRef.current.view === "chat" && !routeRef.current.id)
          go("chat", id);
      } else {
        setOptimistic({
          id,
          text: prompt,
          images: attachedImages,
          count: (current?.messages || []).filter((m) => m.role === "user")
            .length,
        });
      }
      if (chosenMode === "chat")
        await api(
          "tasks/" + id + "/chat",
          current
            ? {
                text: requestPrompt,
                model: modelChoice,
                attachments: attachmentPayload,
                images: imagePayload,
              }
            : { initial: true },
        );
      else if (current)
        await api("tasks/" + id + "/command", {
          action: "followup",
          model: modelChoice,
          text: requestPrompt,
          images: imagePayload,
          attachments: attachmentPayload,
        });
      if (s === session.current) {
        await refreshTask(id);
        await refreshHistory();
        api("me")
          .then((user) => {
            if (s === session.current) setMe(user);
          })
          .catch(() => {});
      }
    } catch (e) {
      if (
        s === session.current &&
        (!id?.startsWith("tmp-") || routeRef.current.id === id)
      ) {
        notify(e.message);
        setDrafts((old) => ({
          ...old,
          [created ? id : startKey]: old[created ? id : startKey] || prompt,
        }));
        setDraftDocuments((old) => ({
          ...old,
          [created ? id : startKey]: attachedDocuments,
        }));
        setDraftImages((old) => ({
          ...old,
          [created ? id : startKey]: old[created ? id : startKey]?.length
            ? old[created ? id : startKey]
            : attachedImages,
        }));
        if (created && id) await refreshTask(id).catch(() => {});
      }
    } finally {
      submitLocks.current.delete(startKey);
      if (id) submitLocks.current.delete(id);
      if (mounted.current && s === session.current) {
        setPending((p) => ({
          ...p,
          [startKey]: false,
          ...(id ? { [id]: false } : {}),
        }));
        setOptimistic((o) => (o?.id === id ? null : o));
      }
    }
  }
  async function command(action, text) {
    const id = route.id;
    if (!id || actionBusy) return;
    setActionBusy(true);
    try {
      await api("tasks/" + id + "/command", {
        action,
        ...(text && typeof text === "object" ? text : { text }),
      });
      await refreshTask(id);
      await refreshHistory();
    } catch (e) {
      notify(e.message);
    } finally {
      setActionBusy(false);
    }
  }
  async function control(owner) {
    if (actionBusy) return;
    const id = route.id;
    setActionBusy(true);
    try {
      await api("tasks/" + id + "/control", { owner });
      await refreshTask(id);
    } catch (e) {
      notify(e.message);
    } finally {
      setActionBusy(false);
    }
  }
  const openPreview = useCallback(
    (port, path = "/") => {
      if (
        workspaceState?.id === routeRef.current.id &&
        workspaceState.status === "stopped"
      ) {
        notify(
          "Workspace stopped. Start your app from Services to open a preview.",
        );
        setWorkspaceOpen(true);
        return;
      }
      setPreviewPort(port);
      setPreviewPath(path);
      setWorkspaceOpen(false);
    },
    [workspaceState, notify],
  );
  async function deleteTask() {
    if (actionBusy) return;
    const target = deleting;
    setActionBusy(true);
    try {
      await api("tasks/" + target.id, {}, "DELETE");
      setDeleting(null);
      setDrafts((p) => {
        const n = { ...p };
        delete n[target.id];
        return n;
      });
      setDraftImages((p) => {
        const n = { ...p };
        delete n[target.id];
        return n;
      });
      setDraftDocuments((p) => {
        const n = { ...p };
        delete n[target.id];
        return n;
      });
      if (routeRef.current.id === target.id) go();
      await refreshHistory();
      notify("Conversation deleted");
    } catch (e) {
      notify(e.message);
    } finally {
      setActionBusy(false);
    }
  }
  useEffect(() => {
    if (!task?.id || task.mode !== "work") return;
    let alive = true,
      inflight = false;
    async function check() {
      if (inflight) return;
      inflight = true;
      try {
        const state = await api(`tasks/${task.id}/workspace-status`);
        if (alive) {
          setWorkspaceState({ ...state, id: task.id });
          if (state.status === "stopped") setPreviewPort(null);
        }
      } catch {
      } finally {
        inflight = false;
      }
    }
    check();
    const timer = setInterval(check, 5000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [task?.id, task?.mode]);
  function workspaceStopped(stopped = true) {
    if (stopped) {
      setPreviewPort(null);
      setWorkspaceState({ id: task.id, status: "stopped" });
      setTask((old) => ({ ...old, app_preview: null }));
    }
    refreshTask(task.id).catch((e) => notify(e.message));
  }
  if (booting)
    return (
      <div className="boot">
        <Logo />
        <span>Opening your workspace…</span>
      </div>
    );
  if (!me)
    return (
      <>
        <Auth
          onSuccess={async () => {
            window.history.replaceState(null, "", location.pathname);
            setRoute({ view: "chat", id: null });
            await boot();
          }}
        />
        {bootError && (
          <div className="toast" role="alert">
            {bootError}
            <button onClick={boot}>Retry</button>
          </div>
        )}
      </>
    );
  const modeNow = activeTask?.mode || mode,
    hasConversation = !!route.id,
    work = modeNow === "work",
    showComputer =
      route.view === "chat" && activeTask?.browser_used && !browserClosed;
  const busy =
    !!pending[draftKey] ||
    !!activeTask?.busy ||
    (activeTask?.mode === "chat" && activeTask?.status === "running");
  const messages = activeTask?.messages || [];
  const threadRows = [...messages];
  if (activeTask && work) {
    const lastUser = messages.findLastIndex((m) => m.role === "user");
    let insertion = messages.findIndex(
      (m, i) => i > lastUser && m.role === "assistant",
    );
    if (insertion < 0) insertion = messages.length;
    threadRows.splice(insertion, 0, { role: "activity" });
  }
  const workspaceRunning =
    workspaceState?.id === activeTask?.id &&
    workspaceState?.status === "running";
  const showOptimistic =
    optimistic?.id === route.id &&
    messages.filter((m) => m.role === "user").length <= optimistic.count;
  if (showOptimistic)
    threadRows.push({
      role: "user",
      text: optimistic.text,
      images: optimistic.images,
      optimistic: true,
    });
  const liveDelta =
    delta && !messages.some((m) => streamRender.id && m.id === streamRender.id);
  if (liveDelta)
    threadRows.push({
      role: "assistant",
      id: streamRender.id || "streaming",
      text: delta,
      html: streamRender.html,
      streaming: true,
    });
  const isTemporary = !work && (activeTask?.temporary || temporaryChat);
  const proposal = activeTask?.work_suggestion;
  const showWorkOffer =
    route.view === "chat" &&
    !work &&
    !busy &&
    proposal &&
    !proposal.dismissed &&
    !dismissedWork.has(proposal.id);
  const rows = history.filter((t) =>
    t.title.toLowerCase().includes(search.toLowerCase()),
  );
  return (
    <div className="app-shell">
      <a
        href="#main"
        className="skip-link"
        onClick={(e) => {
          e.preventDefault();
          document.getElementById("main")?.focus();
        }}
      >
        Skip to content
      </a>
      {menu && (
        <button
          className="sidebar-backdrop"
          aria-label="Close navigation"
          onClick={() => setMenu(false)}
        />
      )}
      <aside
        ref={drawer}
        inert={mobile && !menu}
        className={"sidebar " + (menu ? "open" : "")}
        aria-label="Workspace navigation"
        onClick={(e) => {
          if (e.target.closest("a")) setMenu(false);
        }}
      >
        <div className="sidebar-brand">
          <a href="#" aria-label="OwnCMD home" onClick={() => setTask(null)}>
            <Logo />
            <span>OwnCMD</span>
          </a>
          <span className="workspace-badge">WORKSPACE</span>
          <IconButton
            name="close"
            label="Close navigation"
            onClick={() => setMenu(false)}
          />
        </div>
        <button className="new-chat" onClick={newConversation}>
          <Icon name="plus" />
          <span>New conversation</span>
          <kbd>⌘ ⇧ O</kbd>
        </button>
        <label className="history-search">
          <Icon name="search" size={17} />
          <input
            id="history-search"
            type="search"
            autoComplete="off"
            placeholder="Search conversations"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            aria-label="Search conversations"
          />
          <kbd>⌘ K</kbd>
        </label>
        <nav className="workspace-nav">
          {[
            ["memory", "memory", "Memory"],
            ["schedules", "clock", "Scheduled work"],
            ["skills", "work", "Skills"],
            ["details", "user", "Personal details"],
          ].map(([v, icon, label]) => (
            <a
              key={v}
              href={"#" + v}
              className={route.view === v ? "selected" : ""}
              aria-current={route.view === v ? "page" : undefined}
            >
              <Icon name={icon} />
              {label}
            </a>
          ))}
        </nav>
        <div className="history-heading">Recent conversations</div>
        <nav className="history-list" aria-label="Conversations">
          {historyError ? (
            <button className="history-empty" onClick={refreshHistory}>
              Couldn’t load history. Retry
            </button>
          ) : !rows.length ? (
            <p className="history-empty">
              {search
                ? "No matching conversations."
                : "Your conversations will appear here."}
            </p>
          ) : (
            rows.map((t) => (
              <div
                key={t.id}
                className={
                  "history-row " +
                  (route.view === "chat" && route.id === t.id ? "selected" : "")
                }
              >
                <a
                  href={"#chat/" + t.id}
                  title={t.title}
                  aria-current={
                    route.view === "chat" && route.id === t.id
                      ? "page"
                      : undefined
                  }
                >
                  {t.title}
                </a>
                {["queued", "running", "approval"].includes(t.status) && (
                  <span className="task-status-dot" title={t.status} />
                )}
                <IconButton
                  name="trash"
                  label={"Delete " + t.title}
                  onClick={() => setDeleting(t)}
                />
              </div>
            ))
          )}
        </nav>
        <div className="sidebar-bottom">
          {me?.account?.role === "admin" && (
            <a href="#admin" className="settings-link">
              <Icon name="settings" />
              Instance settings
            </a>
          )}
          <a
            href="#usage"
            className={
              "settings-link " + (route.view === "usage" ? "selected" : "")
            }
            aria-current={route.view === "usage" ? "page" : undefined}
          >
            <Icon name="activity" />
            Usage
          </a>
          <a
            href="#help"
            className={
              "settings-link " + (route.view === "help" ? "selected" : "")
            }
            aria-current={route.view === "help" ? "page" : undefined}
          >
            <Icon name="help" />
            Help & support
          </a>
          <a
            href="#settings"
            className={
              "settings-link " + (route.view === "settings" ? "selected" : "")
            }
            aria-current={route.view === "settings" ? "page" : undefined}
          >
            <Icon name="settings" />
            Settings
          </a>
          <div className="account">
            <span className="avatar">{me.email[0].toUpperCase()}</span>
            <a href="#settings">
              <strong>{me.email.split("@")[0]}</strong>
              <small>
                {me.account?.role === "admin" ? "Instance owner" : "Member"}
              </small>
            </a>
            <IconButton
              name="logout"
              label="Sign out"
              onClick={async () => {
                try {
                  await api("logout", {});
                  signout();
                } catch (e) {
                  notify(e.message);
                }
              }}
            />
          </div>
        </div>
      </aside>
      <main
        id="main"
        inert={mobile && menu}
        tabIndex={-1}
        className={"main " + (showComputer ? "with-computer" : "")}
      >
        <header
          className={
            "topbar " +
            (!hasConversation || route.view !== "chat" ? "quiet" : "")
          }
        >
          <div className="topbar-left">
            <IconButton
              name="menu"
              label="Open navigation"
              onClick={() => setMenu(true)}
            />
            {route.view === "chat" && hasConversation ? (
              <div className="conversation-title">
                <strong>{activeTask?.title || "Opening conversation…"}</strong>
                <span>
                  <i
                    className={
                      connection === "Live" ? "live-dot" : "offline-dot"
                    }
                  />
                  {modeNow === "chat" ? "Chat" : "Work"}
                  <b>·</b>
                  {activeTask?.status === "completed"
                    ? "Ready"
                    : activeTask?.status || "Loading"}
                </span>
              </div>
            ) : (
              <span className="topbar-context">
                {route.view === "chat"
                  ? isTemporary
                    ? "Temporary chat"
                    : "Personal workspace"
                  : route.view === "schedules"
                    ? "Scheduled work"
                    : route.view === "details"
                      ? "Personal details"
                      : route.view[0].toUpperCase() + route.view.slice(1)}
              </span>
            )}
          </div>
          {route.view === "chat" && (
            <div className="topbar-actions">
              {!work && (
                <button
                  type="button"
                  className={
                    "temporary-toggle " + (isTemporary ? "selected" : "")
                  }
                  aria-label={
                    isTemporary
                      ? "Turn off temporary chat"
                      : "Turn on temporary chat"
                  }
                  aria-pressed={!!isTemporary}
                  title="Temporary chat · not saved to history"
                  disabled={busy}
                  onClick={toggleTemporary}
                >
                  <Icon name="temporary" />
                  <span>Temporary</span>
                </button>
              )}
              {activeTask && (
                <>
                  <ConversationInfo
                    task={activeTask}
                    onChanged={(kind) => {
                      if (kind === "code") workspaceStopped();
                      else {
                        if (kind === "browser") setBrowserClosed(true);
                        refreshTask(activeTask.id).catch((e) =>
                          notify(e.message),
                        );
                      }
                    }}
                  />
                  {work && (
                    <button
                      className="button small"
                      onClick={() => {
                        setPreviewPort(null);
                        setWorkspaceOpen(true);
                      }}
                    >
                      <Icon name="code" size={15} />
                      Workspace
                    </button>
                  )}
                  {work && (
                    <>
                      <button
                        className="button small"
                        disabled={
                          actionBusy ||
                          !["queued", "running"].includes(activeTask.status)
                        }
                        onClick={() => command("pause")}
                      >
                        <Icon name="pause" size={14} />
                        <span>Pause</span>
                      </button>
                      <button
                        className="button small"
                        disabled={
                          actionBusy ||
                          !["paused", "failed"].includes(activeTask.status)
                        }
                        onClick={() => command("resume")}
                      >
                        <Icon name="play" size={14} />
                        <span>Resume</span>
                      </button>
                      <button
                        className="button small"
                        disabled={
                          actionBusy ||
                          ["completed", "cancelled"].includes(activeTask.status)
                        }
                        onClick={() => command("cancel")}
                      >
                        <Icon name="stop" size={14} />
                        <span>Stop</span>
                      </button>
                    </>
                  )}
                  {activeTask.browser_used && browserClosed && (
                    <IconButton
                      name="browser"
                      label="Open computer"
                      onClick={() => setBrowserClosed(false)}
                    />
                  )}
                  <IconButton
                    name="trash"
                    label="Delete conversation"
                    onClick={() => setDeleting(activeTask)}
                  />
                </>
              )}
            </div>
          )}
        </header>
        {route.view === "help" ? (
          <div className="page-scroll">
            <section className="community-page">
              <h1>OwnCMD Community</h1>
              <p>
                See the README, CONTRIBUTING.md and SECURITY.md included with
                your source. Contact your instance owner for access or
                configuration help.
              </p>
            </section>
          </div>
        ) : route.view === "admin" ? (
          <div className="page-scroll">
            {me?.account?.role === "admin" ? (
              <CommunitySettings />
            ) : (
              <p>Administrator access required.</p>
            )}
          </div>
        ) : route.view === "usage" ? (
          <div className="page-scroll">
            <Usage />
          </div>
        ) : route.view === "settings" ? (
          <div className="page-scroll">
            <Settings
              prefs={prefs}
              me={me}
              notify={notify}
              onSave={async (patch) => {
                const next = await api("settings", patch, "PUT");
                setPrefs({ ...defaults, ...next });
              }}
            />
          </div>
        ) : route.view === "skills" ? (
          <div className="page-scroll">
            <Skills notify={notify} />
          </div>
        ) : route.view === "details" ? (
          <div className="page-scroll">
            <PersonalDetails notify={notify} />
          </div>
        ) : route.view === "schedules" ? (
          <div className="page-scroll">
            <Schedules notify={notify} />
          </div>
        ) : route.view === "memory" ? (
          <div className="page-scroll">
            <Collection key={route.view} kind={route.view} notify={notify} />
          </div>
        ) : (
          <div className="conversation-layout">
            <section
              className={"conversation " + (!hasConversation ? "home" : "")}
              aria-label="Conversation"
            >
              <div
                className="conversation-scroll"
                ref={scroll}
                onScroll={() => {
                  const e = scroll.current;
                  stick.current =
                    e.scrollHeight - e.scrollTop - e.clientHeight < 120;
                  setJump(!stick.current);
                }}
              >
                {!hasConversation ? (
                  <div className="home-content">
                    <div className="home-emblem">
                      <Logo />
                    </div>
                    <span className="eyebrow">YOUR SPACE TO THINK AND DO</span>
                    <h1>
                      {work
                        ? "Big ideas. Real progress."
                        : isTemporary
                          ? "A little space, just for now."
                          : "What’s on your mind?"}
                    </h1>
                    <p className="home-description">
                      {work
                        ? "Give OwnCMD an outcome. Make room for what matters."
                        : isTemporary
                          ? "This conversation won’t appear in your history or use your saved memories."
                          : "A question, a fresh perspective, or your next great idea."}
                    </p>
                    <Composer
                      key={draftKey}
                      mode={mode}
                      setMode={changeMode}
                      value={draft}
                      setValue={setDraft}
                      onSubmit={send}
                      busy={busy}
                      prefs={prefs}
                      notify={notify}
                      images={images}
                      setImages={setImages}
                      documents={documents}
                      setDocuments={setDocuments}
                      temporary={isTemporary}
                      fileLimit={me?.account?.limits?.file_mb || 100}
                      modelOptions={modelOptions?.[activeTask?.mode || mode]}
                      modelChoice={modelChoice}
                      setModelChoice={setModelChoice}
                    />
                    <div className="home-capability">
                      <Icon name={work ? "work" : "globe"} size={14} />
                      {work
                        ? "Browse the web, run code, and create files"
                        : "Current sources, whenever you need them"}
                    </div>
                    <div className="starters">
                      {(work
                        ? [
                            [
                              "globe",
                              "Research a topic",
                              "Research the latest developments in ",
                            ],
                            [
                              "code",
                              "Build something",
                              "Build a working prototype for ",
                            ],
                            [
                              "file",
                              "Create a document",
                              "Create a detailed report about ",
                            ],
                          ]
                        : [
                            ["globe", "Explore a topic", "Help me understand "],
                            [
                              "spark",
                              "Think it through",
                              "Help me think through this idea: ",
                            ],
                            [
                              "file",
                              "Refine my writing",
                              "Help me improve this draft: ",
                            ],
                          ]
                      ).map(([icon, title, prompt]) => (
                        <button
                          key={title}
                          onClick={() => {
                            setDraft(prompt);
                            document.getElementById("prompt")?.focus();
                          }}
                        >
                          <Icon name={icon} />
                          <span>{title}</span>
                          <Icon name="chevron" size={14} />
                        </button>
                      ))}
                    </div>
                    <p className="home-footnote">
                      {isTemporary
                        ? "Cleared when you leave. AI providers still process your messages."
                        : "A little clarity. A new possibility."}
                    </p>
                  </div>
                ) : (
                  <div className="thread">
                    {taskError && (
                      <div className="error-card" role="alert">
                        {taskError}
                        <button
                          className="button"
                          onClick={() =>
                            refreshTask(route.id).catch((e) =>
                              notify(e.message),
                            )
                          }
                        >
                          Retry
                        </button>
                      </div>
                    )}
                    {!activeTask && !taskError && (
                      <div className="thread-loading" role="status">
                        <span className="skeleton" />
                        <span className="skeleton" />
                        <span className="skeleton" />
                      </div>
                    )}
                    {isTemporary && (
                      <p className="temporary-notice">
                        <Icon name="temporary" size={16} />
                        Temporary chat · not saved to history
                      </p>
                    )}
                    {threadRows.map((m, i) =>
                      m.role === "activity" ? (
                        <Activity
                          key={"activity-" + activeTask.id}
                          task={activeTask}
                          expanded={prefs.activity_expanded}
                        />
                      ) : (
                        <article
                          className={"message " + m.role}
                          aria-busy={m.streaming || undefined}
                          key={m.id || `${m.role}-${i}`}
                        >
                          {m.role === "assistant" && (
                            <div className="message-author">
                              <Logo small />
                              <strong>OwnCMD</strong>
                            </div>
                          )}
                          <div className="message-body">
                            <ImageStrip images={m.images} />
                            <Markdown
                              html={m.html}
                              text={m.text}
                              onPreview={work ? openPreview : undefined}
                            />
                            {m.role === "assistant" &&
                              m.artifacts?.length > 0 && (
                                <div className="message-downloads">
                                  {m.artifacts.map((file) => (
                                    <a
                                      key={file.path}
                                      href={file.url}
                                      download={file.name}
                                    >
                                      <Icon name="file" />
                                      <span>
                                        {file.name}
                                        <small>
                                          {Math.max(
                                            1,
                                            Math.ceil(file.size / 1024),
                                          )}{" "}
                                          KB
                                        </small>
                                      </span>
                                      <Icon name="down" />
                                    </a>
                                  ))}
                                </div>
                              )}
                            {m.role === "assistant" && !m.streaming && (
                              <>
                                <Sources
                                  rows={m.sources}
                                  expanded={prefs.sources_expanded}
                                />
                                <div className="message-actions">
                                  <CopyButton text={m.text} notify={notify} />
                                </div>
                              </>
                            )}
                          </div>
                        </article>
                      ),
                    )}
                    {(activity ||
                      (busy &&
                        (showOptimistic ||
                          !messages.some((m) => m.role === "assistant") ||
                          activeTask?.status === "running"))) &&
                      !liveDelta &&
                      !work && (
                        <div className="thinking" role="status">
                          <span className="pulse" />
                          {activity || "Thinking…"}
                        </div>
                      )}
                    {activeTask?.error &&
                      ["failed", "paused"].includes(activeTask.status) && (
                        <div className="error-card" role="alert">
                          {activeTask.error}
                        </div>
                      )}
                    {activeTask && work && (
                      <>
                        {activeTask.app_preview && workspaceRunning && (
                          <button
                            className="app-preview-card"
                            onClick={() =>
                              openPreview(
                                activeTask.app_preview.port,
                                activeTask.app_preview.path || "/",
                              )
                            }
                          >
                            <Icon name="browser" size={24} />
                            <span>
                              <strong>Open app preview</strong>
                              <small>
                                Try your app in your private workspace
                              </small>
                            </span>
                            <Icon name="chevron" />
                          </button>
                        )}
                        <Sources
                          rows={remainingSources(activeTask.sources, messages)}
                          expanded={prefs.sources_expanded}
                        />
                      </>
                    )}
                    {activeTask?.status === "approval" &&
                      activeTask?.approval && (
                        <Approval
                          id="task-input-request"
                          key={
                            route.id +
                            ":" +
                            (activeTask.approval.id ||
                              JSON.stringify(activeTask.approval.arguments))
                          }
                          approval={activeTask.approval}
                          onCommand={command}
                          onControl={control}
                          busy={actionBusy}
                        />
                      )}
                  </div>
                )}
              </div>
              {hasConversation && (
                <div className="composer-dock">
                  {jump && (
                    <button
                      className="jump-latest"
                      onClick={() => {
                        stick.current = true;
                        scroll.current.scrollTo({
                          top: scroll.current.scrollHeight,
                          behavior: prefs.reduce_motion ? "instant" : "smooth",
                        });
                        setJump(false);
                      }}
                    >
                      <Icon name="down" size={15} />
                      Latest messages
                    </button>
                  )}
                  {savedDocuments.length > 0 && (
                    <div
                      className="saved-attachments"
                      aria-label="Conversation attachments"
                    >
                      {savedDocuments.map((d) => (
                        <span key={d.id}>
                          <Icon name="file" size={16} />
                          <a
                            href={"/api/attachments/" + d.id + "/download"}
                            download
                            title={d.name}
                          >
                            {d.name}
                            <small>
                              {d.info?.kind === "archive"
                                ? "Archive · Attached"
                                : `${d.info?.pages || 0} pages / sections · Attached`}
                            </small>
                          </a>
                        </span>
                      ))}
                    </div>
                  )}
                  <Composer
                    key={draftKey}
                    mode={modeNow}
                    locked
                    value={draft}
                    setValue={setDraft}
                    onSubmit={send}
                    busy={busy || !activeTask}
                    blocked={activeTask?.status === "approval"}
                    prefs={prefs}
                    notify={notify}
                    images={images}
                    setImages={setImages}
                    documents={documents}
                    setDocuments={setDocuments}
                    temporary={isTemporary}
                    fileLimit={me?.account?.limits?.file_mb || 100}
                    modelOptions={modelOptions?.[activeTask?.mode || mode]}
                    modelChoice={modelChoice}
                    setModelChoice={setModelChoice}
                  />
                  <p className="composer-note">
                    {work
                      ? "You’re in control. Review requests before OwnCMD continues."
                      : isTemporary
                        ? "Cleared when you leave. AI providers still process your messages."
                        : "OwnCMD can make mistakes. Check important details."}
                  </p>
                </div>
              )}
            </section>
            {previewPort && activeTask?.mode === "work" && (
              <AppPreview
                key={`${activeTask.id}:${previewPort}:${previewPath}`}
                task={activeTask}
                port={previewPort}
                path={previewPath}
                onClose={() => setPreviewPort(null)}
                onPause={() => command("pause")}
                notify={notify}
              />
            )}
            {showComputer && !previewPort && (
              <BrowserPanel
                key={activeTask.id}
                task={activeTask}
                onControl={control}
                onCommand={command}
                busy={actionBusy}
                notify={notify}
                onClose={() => setBrowserClosed(true)}
                onRequestInput={showInputRequest}
              />
            )}
          </div>
        )}
      </main>
      {toast && (
        <div className="toast" role="status">
          <span>{toast}</span>
          <IconButton
            name="close"
            label="Dismiss notification"
            onClick={() => setToast("")}
          />
        </div>
      )}
      {workspaceOpen && activeTask?.mode === "work" && (
        <Development
          key={activeTask.id}
          onStopped={workspaceStopped}
          onPreview={openPreview}
          task={activeTask}
          notify={notify}
          onClose={() => setWorkspaceOpen(false)}
          onPause={() => command("pause")}
        />
      )}
      {showWorkOffer && (
        <Modal
          title="Continue this in Work?"
          onClose={() => !handoffBusy && handoff("dismiss")}
        >
          <div className="work-handoff">
            <div className="handoff-symbol">
              <Icon name="work" size={28} />
            </div>
            <p className="handoff-reason">{proposal.reason}</p>
            <div className="handoff-capability">
              <Icon
                name={
                  proposal.capability === "browser"
                    ? "browser"
                    : proposal.capability === "code"
                      ? "code"
                      : "folder"
                }
              />
              <span>
                {proposal.capability === "browser"
                  ? "A browser to take action"
                  : proposal.capability === "code"
                    ? "A workspace to run and check code"
                    : "A workspace to create and edit files"}
              </span>
            </div>
            <p className="modal-copy">
              Your request and recent conversation will carry over. OwnCMD will
              start working after you confirm. Provider usage is recorded at
              cost.
            </p>
            {isTemporary && (
              <p className="handoff-privacy">
                <Icon name="shield" size={18} />
                Switching creates a saved Work conversation with the context you
                share.
              </p>
            )}
          </div>
          <div className="modal-actions">
            <button
              className="button"
              disabled={handoffBusy}
              onClick={() => handoff("dismiss")}
            >
              Stay in Chat
            </button>
            <button
              className="button primary"
              disabled={handoffBusy}
              onClick={() => handoff("accept")}
            >
              {handoffBusy ? "Please wait…" : "Switch to Work"}
              <Icon
                name="arrow"
                size={16}
                style={{ transform: "rotate(90deg)" }}
              />
            </button>
          </div>
        </Modal>
      )}
      {deleting && (
        <Modal
          title="Delete this conversation?"
          onClose={() => !actionBusy && setDeleting(null)}
        >
          <p className="modal-copy">
            “{deleting.title}” and its saved task history will be permanently
            removed.
          </p>
          <div className="modal-actions">
            <button
              className="button"
              disabled={actionBusy}
              onClick={() => setDeleting(null)}
            >
              Keep conversation
            </button>
            <button
              className="button danger"
              disabled={actionBusy}
              onClick={deleteTask}
            >
              {actionBusy ? "Deleting…" : "Delete conversation"}
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}
