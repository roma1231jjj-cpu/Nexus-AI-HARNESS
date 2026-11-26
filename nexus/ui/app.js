/* Nexus-Harness UI: сессии, поток частей, подтверждения, режимы. */

const $ = (id) => document.getElementById(id);
const NOSTREAM = new URLSearchParams(location.search).has("nostream");
const MODE_HINT = { plan: "hintPlanOnly", act: "hintAct", full: "hintFull" };
const state = {
  cfg: null,
  personas: [],
  modes: [],
  models: [],
  sessions: [],
  session: null,
  training: null,
  run: null,
  version: "",
  selectedCats: new Set(JSON.parse(localStorage.getItem("nexus-cats") || "[]")),
  runTimer: null,
  sse: null,
  sseTries: 0,
  resyncTimer: null,
  watchTimer: null,
  pollFails: 0,
  pending: null,
  busy: false,
};

/* ------------------------------------------------------------------ утилиты */
const esc = (s) => String(s).replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function md(text) {
  const blocks = String(text).split(/```/);
  return blocks.map((chunk, i) => {
    if (i % 2 === 1) {
      const body = chunk.replace(/^[a-z0-9+#-]*\n/i, "");
      return `<pre><code>${esc(body)}</code></pre>`;
    }
    let html = esc(chunk);
    html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
    html = html.replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>");
    html = html.replace(/(^|\n)(&gt;\s?.*)/g, "$1<span class='plan-block'>$2</span>");
    return html.split(/\n{2,}/).map((p) => p.trim() ? `<p>${p.replace(/\n/g, "<br>")}</p>` : "").join("");
  }).join("");
}

const shortJson = (obj) => {
  try {
    const s = JSON.stringify(obj ?? {});
    return s.length > 110 ? s.slice(0, 108) + "…" : s;
  } catch { return "{}"; }
};

const prettyJson = (obj) => {
  try { return JSON.stringify(obj ?? {}, null, 2); } catch { return "{}"; }
};

/* сервер отдаёт {"code": "...", "vars": {...}}, старый text/error остаётся фолбэком */
function codeText(obj, field) {
  if (!obj) return "";
  if (typeof obj === "string") return obj;
  if (obj.code) return t(obj.code, obj.vars || {});
  const value = obj[field || "text"];
  return value == null ? "" : String(value);
}

const evText = (part) => codeText(part, "text");

let bannerTimer = null;
let bannerSticky = false;
function notify(message, sticky) {
  const box = $("banner");
  if (!box) return;
  box.textContent = message;
  box.hidden = false;
  bannerSticky = !!sticky;
  clearTimeout(bannerTimer);
  if (!sticky) bannerTimer = setTimeout(() => { if (!bannerSticky) box.hidden = true; }, 7000);
}
function clearNotify() {
  const box = $("banner");
  clearTimeout(bannerTimer);
  bannerSticky = false;
  if (box) box.hidden = true;
}

async function guard(fn) {
  try {
    return await fn();
  } catch (err) {
    notify(t("actionFailed", { e: err.message }));
    console.error(err);
    return null;
  }
}

async function api(path, body, method) {
  const res = await fetch(path, {
    method: method || (body ? "POST" : "GET"),
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  let data = {};
  try { data = await res.json(); } catch { data = {}; }
  if (!res.ok && res.status !== 409) {
    const err = new Error(codeText(data, "error") || `${res.status} ${res.statusText}`);
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

const activateOnKey = (ev, fn) => {
  if (ev.key === "Enter" || ev.key === " " || ev.key === "Spacebar") {
    ev.preventDefault();
    fn();
  }
};

/* ------------------------------------------------------------------ отрисовка шапки */
function renderModes() {
  const box = $("modes");
  box.innerHTML = "";
  state.modes.forEach((mode) => {
    const active = state.cfg.mode === mode.id;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "mode" + (active ? " active" : "");
    btn.textContent = mode.name;
    btn.title = MODE_HINT[mode.id] ? t(MODE_HINT[mode.id]) : mode.hint || "";
    btn.setAttribute("aria-pressed", String(active));
    btn.onclick = () => guard(async () => {
      if (state.cfg.mode === mode.id) return;
      const prev = state.cfg.mode;
      state.cfg.mode = mode.id;
      renderModes();
      renderHint();
      try {
        await api("/api/config", { mode: mode.id });
      } catch (err) {
        state.cfg.mode = prev;
        renderModes();
        renderHint();
        throw err;
      }
    });
    box.appendChild(btn);
  });
}

function renderProvider() {
  const sel = $("provider");
  sel.innerHTML = "";
  Object.entries(state.cfg.providers).forEach(([id, conf]) => {
    const opt = document.createElement("option");
    opt.value = id;
    opt.textContent = providerLabel(id, conf);
    if (id === state.cfg.provider) opt.selected = true;
    sel.appendChild(opt);
  });
  sel.onchange = () => guard(async () => {
    const prevProvider = state.cfg.provider;
    const prevModel = state.cfg.model || "";
    const nextProvider = sel.value;
    // До ответа сервера держим прежний вариант, но запоминаем выбранный.
    sel.value = prevProvider;
    state.cfg.provider = nextProvider;
    state.cfg.model = "";
    $("model").value = "";
    try {
      const data = await api("/api/config", { provider: nextProvider, model: "" });
      state.model = data.model || "";
      sel.value = nextProvider;
    } catch (err) {
      state.cfg.provider = prevProvider;
      state.cfg.model = prevModel;
      state.model = prevModel;
      sel.value = prevProvider;
      $("model").value = prevModel;
      updateSendState();
      throw err;
    }
    updateSendState();
    await loadModels();
  });
}

function renderModels() {
  const list = $("modelList");
  list.innerHTML = "";
  state.models.forEach((m) => {
    const opt = document.createElement("option");
    opt.value = m;
    list.appendChild(opt);
  });
  $("model").value = state.cfg.model || "";
  $("model").onchange = () => guard(async () => {
    const prev = state.cfg.model || "";
    const next = $("model").value.trim();
    state.cfg.model = next;
    updateSendState();
    try {
      const data = await api("/api/config", { model: next });
      state.model = data.model || next;
    } catch (err) {
      state.cfg.model = prev;
      state.model = prev;
      $("model").value = prev;
      updateSendState();
      throw err;
    }
  });
}

function renderHint() {
  $("hint").textContent = t(MODE_HINT[state.cfg.mode] || "hintPlanOnly");
}

function renderSessions() {
  const box = $("sessions");
  box.innerHTML = "";
  (state.sessions || []).forEach((s) => {
    const row = document.createElement("div");
    row.className = "session" + (state.session && state.session.id === s.id ? " active" : "");
    row.setAttribute("role", "button");
    row.tabIndex = 0;
    const plain = s.auto_title || s.title === "Новая сессия" || s.title === "New chat";
    row.textContent = plain ? t("newChat") : s.title;
    row.title = t("messagesCount", { n: s.messages });
    row.onclick = () => guard(() => openSession(s.id));
    row.onkeydown = (ev) => activateOnKey(ev, () => guard(() => openSession(s.id)));
    box.appendChild(row);
  });
}

function renderTodos(todos) {
  const box = $("todos");
  const label = $("todoLabel");
  box.innerHTML = "";
  const items = todos || [];
  label.hidden = items.length === 0;
  items.forEach((todo) => {
    const row = document.createElement("div");
    row.className = "todo";
    row.dataset.s = todo.status;
    row.textContent = (todo.status === "done" ? "✓ " : todo.status === "active" ? "▸ " : "· ") + todo.text;
    box.appendChild(row);
  });
  if (!items.length) return;
  requestAnimationFrame(() => {
    if (box.scrollHeight <= box.clientHeight + 2) return;
    const bottom = box.getBoundingClientRect().bottom;
    const hidden = [...box.children].filter((el) => el.getBoundingClientRect().bottom > bottom + 1).length;
    if (!hidden) return;
    const more = document.createElement("div");
    more.className = "todo todo-more";
    more.textContent = t("todosMore", { n: hidden });
    box.appendChild(more);
  });
}

/* ------------------------------------------------------------------ поток сообщений */
function toolCard(part, result) {
  const wrap = document.createElement("div");
  wrap.className = "tool" + (result ? "" : " collapsed");
  const head = document.createElement("div");
  head.className = "tool-head";
  head.setAttribute("role", "button");
  head.tabIndex = 0;
  const argsJson = prettyJson(part.input || {});
  head.innerHTML =
    `<span class="tool-name">${esc(part.tool)}</span>` +
    `<span class="tool-args">${esc(shortJson(part.input || {}))}</span>` +
    `<span class="tool-status ${result ? (result.ok ? "ok" : "err") : ""}">` +
    `${result ? (result.ok ? t("done") : t("error")) : "…"}</span>`;
  const args = head.querySelector(".tool-args");
  if (args) args.title = argsJson;
  const published = !wrap.classList.contains("collapsed");
  head.setAttribute("aria-expanded", String(published));
  const toggle = () => {
    wrap.classList.toggle("collapsed");
    head.setAttribute("aria-expanded", String(!wrap.classList.contains("collapsed")));
  };
  head.onclick = toggle;
  head.onkeydown = (ev) => activateOnKey(ev, toggle);
  wrap.appendChild(head);
  const body = document.createElement("div");
  body.className = "tool-body";
  body.textContent = result ? (result.code ? evText(result) : (result.output || "")) : argsJson;
  wrap.appendChild(body);
  return wrap;
}

function renderMessages() {
  const stream = $("stream");
  stream.innerHTML = "";
  if (!state.session || !state.session.messages.length) {
    stream.innerHTML = `<div class="empty">
      <b>Nexus-Harness</b> ${esc(t("emptyTitle"))}<br>
      ${esc(t("emptyLine1"))}<br>
      ${esc(t("emptyLine2"))}
    </div>`;
    return;
  }
  // результаты инструментов вкладываем в карточку вызова, отдельные строки не рисуем
  const results = {};
  state.session.messages.forEach((m) => {
    if (m.role !== "tool") return;
    (m.parts || []).forEach((p) => { if (p.type === "tool_result") results[p.call_id] = p; });
  });
  state.session.messages.forEach((msg) => {
    if (msg.role === "tool") return;
    stream.appendChild(messageNode(msg, results));
  });
  scrollDown();
}

function messageNode(msg, results) {
  results = results || {};
  const wrap = document.createElement("div");
  wrap.className = "msg " + msg.role;
  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = msg.role === "user" ? t("avatarMe") : msg.role === "tool" ? "⚙" : "N";
  wrap.appendChild(avatar);

  const bubble = document.createElement("div");
  bubble.className = "bubble";

  const parts = msg.parts || [];
  parts.filter((p) => p.type === "text").forEach((part) => {
    const holder = document.createElement("div");
    holder.innerHTML = md(part.text);
    bubble.appendChild(holder);
  });
  parts.filter((p) => p.type === "tool_call").forEach((call) => {
    bubble.appendChild(toolCard(call, results[call.id] || null));
  });
  parts.filter((p) => p.type === "error").forEach((err) => {
    const div = document.createElement("div");
    div.className = "pill warn";
    div.textContent = evText(err);
    bubble.appendChild(div);
  });

  if (!bubble.childNodes.length) bubble.textContent = "…";
  wrap.appendChild(bubble);
  return wrap;
}

const scrollDown = () => {
  const stream = $("stream");
  stream.scrollTop = stream.scrollHeight;
};

/* ------------------------------------------------------------------ сессии */
async function openSession(id) {
  const session = await api(`/api/sessions/${id}`);
  state.session = session;
  state.session.messages = session.messages || [];
  state.session.todos = session.todos || [];
  state.cfg.mode = session.mode || state.cfg.mode;
  renderModes();
  renderHint();
  renderSessions();
  renderTodos(session.todos);
  renderMessages();
  connectSse(id);
  setBusy(!!session.running);
  clearNotify();
}

function connectSse(id) {
  if (NOSTREAM) return;
  if (state.sse) {
    state.sse.onerror = null;
    state.sse.onopen = null;
    state.sse.close();
  }
  const sse = new EventSource(`/api/sessions/${id}/events`);
  sse.onopen = () => {
    state.sseTries = 0;
    clearNotify();
  };
  sse.onmessage = (ev) => {
    state.sseTries = 0;
    if (bannerSticky) clearNotify();
    try {
      handleEvent(JSON.parse(ev.data));
    } catch (err) {
      console.error(err);
    }
  };
  sse.onerror = () => {
    notify(t("streamLost"), true);
    scheduleResync(id);
  };
  state.sse = sse;
}

function scheduleResync(id) {
  if (state.resyncTimer) clearTimeout(state.resyncTimer);
  const delay = Math.min(30000, 2000 * Math.pow(2, Math.min(state.sseTries, 4)));
  state.sseTries += 1;
  state.resyncTimer = setTimeout(() => guard(() => resync(id)), delay);
}

async function resync(id) {
  if (!state.session || state.session.id !== id) return;
  const session = await api(`/api/sessions/${id}`);
  state.session.messages = session.messages || [];
  state.session.todos = session.todos || [];
  state.session.running = !!session.running;
  renderMessages();
  renderTodos(state.session.todos);
  setBusy(!!session.running);
  connectSse(id);
  if (!session.running) clearNotify();
}

function armBusyWatch() {
  clearTimeout(state.watchTimer);
  if (!state.busy || !state.session) return;
  state.watchTimer = setTimeout(() => {
    if (!state.busy || !state.session) return;
    guard(() => resync(state.session.id));
  }, 20000);
}

function pushError(part) {
  if (!state.session) return;
  state.session.messages.push({
    id: "err_" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6),
    role: "assistant",
    parts: [{ type: "error", code: part.code || "", vars: part.vars || {}, text: part.text || "" }],
  });
  renderMessages();
}

function handleEvent(ev) {
  if (!state.session) return;
  switch (ev.type) {
    case "message": {
      state.session.messages.push(ev.message);
      renderMessages();
      break;
    }
    case "delta": {
      let msg = state.session.messages.find((m) => m.id === ev.message_id);
      if (!msg) {
        msg = { id: ev.message_id, role: "assistant", parts: [{ type: "text", text: "" }] };
        state.session.messages.push(msg);
      }
      const part = msg.parts.find((p) => p.type === "text");
      if (part) part.text += ev.text;
      else msg.parts.unshift({ type: "text", text: ev.text });
      const node = document.getElementById("tmp-assistant");
      if (node) node.replaceWith(messageNode(msg));
      else renderMessages();
      scrollDown();
      break;
    }
    case "tool_call": {
      let msg = state.session.messages.find((m) => m.id === ev.message_id);
      if (!msg) {
        msg = { id: ev.message_id, role: "assistant", parts: [] };
        state.session.messages.push(msg);
      }
      if (!msg.parts.some((p) => p.type === "tool_call" && p.id === ev.part.id)) msg.parts.push(ev.part);
      renderMessages();
      break;
    }
    case "tool_result": {
      const msg = { id: "tool_" + ev.part.call_id, role: "tool", parts: [ev.part] };
      state.session.messages.push(msg);
      renderMessages();
      break;
    }
    case "approval": {
      showApproval(ev);
      break;
    }
    case "todos": {
      state.session.todos = ev.todos;
      renderTodos(ev.todos);
      break;
    }
    case "error": {
      pushError(ev);
      break;
    }
    case "status": {
      setBusy(ev.state !== "idle");
      break;
    }
    case "done": {
      setBusy(false);
      hideApproval();
      guard(() => refreshSessions());
      break;
    }
  }
  armBusyWatch();
}

async function refreshSessions() {
  const data = await api("/api/sessions");
  state.sessions = data.sessions || [];
  renderSessions();
}

/* ------------------------------------------------------------------ подтверждения */
let approvalFocus = null;

function showApproval(ev) {
  state.pending = ev.call_id;
  approvalFocus = document.activeElement;
  $("modalTool").textContent = ev.tool;
  $("modalArgs").textContent = prettyJson(ev.input || {});
  $("modal").hidden = false;
  $("allow").focus();
}

function hideApproval() {
  state.pending = null;
  $("modal").hidden = true;
  if (approvalFocus && approvalFocus.focus) approvalFocus.focus();
  approvalFocus = null;
}

async function decide(decision) {
  if (!state.pending) return;
  const callId = state.pending;
  const allow = $("allow"), deny = $("deny");
  allow.disabled = true;
  deny.disabled = true;
  try {
    await api("/api/approve", { call_id: callId, decision });
    hideApproval();
  } catch (err) {
    notify(t("approveFailed", { e: err.message }), true);
    if (!$("modal").hidden) allow.focus();
  } finally {
    allow.disabled = false;
    deny.disabled = false;
  }
}

document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape" && !$("modal").hidden) decide("deny");
});

/* ------------------------------------------------------------------ отправка */
function updateSendState() {
  const model = String((state.model || (state.cfg && state.cfg.model)) || "").trim();
  $("send").disabled = state.busy || !model;
  $("send").title = model ? "" : t("needModel");
  $("stopBtn").hidden = !state.busy;
  $("send").textContent = state.busy ? t("sending") : t("send");
}

function setBusy(busy) {
  state.busy = busy;
  updateSendState();
  armBusyWatch();
}

async function send() {
  const input = $("input");
  const text = input.value.trim();
  if (!text || state.busy) return;
  if (!String((state.model || (state.cfg && state.cfg.model)) || "").trim()) {
    notify(t("needModel"));
    updateSendState();
    return;
  }
  await guard(async () => {
    if (!state.session) {
      state.session = await api("/api/sessions", {});
      state.session.messages = [];
      await refreshSessions();
      connectSse(state.session.id);
    }
    const sessionId = state.session.id;
    input.value = "";
    input.style.height = "auto";
    setBusy(true);
    try {
      await api(`/api/sessions/${sessionId}/message`, { text, mode: state.cfg.mode });
    } catch (err) {
      setBusy(false);
      pushError({ text: t("sendFailed", { e: err.message }) });
    }
    armBusyWatch();
  });
}

/* ------------------------------------------------------------------ обучение */
document.querySelectorAll(".tab").forEach((tab) => {
  tab.onclick = () => {
    document.querySelectorAll(".tab").forEach((item) => item.classList.toggle("active", item === tab));
    const train = tab.dataset.view === "train";
    $("stream").hidden = train;
    $("composerEl").hidden = train;
    $("trainView").hidden = !train;
    if (train) guard(() => loadTraining());
  };
});

async function loadTraining() {
  const data = await api("/api/training");
  state.training = data;
  renderTraining();
  pollRun();
}

function renderTraining() {
  const data = state.training;
  if (!data) return;
  renderCats();
  const sel = [...state.selectedCats];
  const chosen = (data.categories || []).filter((c) => sel.includes(c.id));
  const records = chosen.reduce((n, c) => n + c.records, 0);
  const ds = data.dataset || {};
  $("trainSummary").textContent = sel.length
    ? t("catsChosen", { n: chosen.length, records, train: ds.train ? ds.train.records : 0, val: ds.val ? ds.val.records : 0 })
    : t("catsNone", { n: data.total_records });

  const sel2 = $("addCat");
  const prev = sel2.value;
  sel2.innerHTML = "";
  (data.categories || []).forEach((c) => {
    const o = document.createElement("option");
    o.value = c.id;
    const cc = catText(c);
    o.textContent = `${cc.group} · ${cc.name}`;
    sel2.appendChild(o);
  });
  if (prev) sel2.value = prev;
}

function renderCats() {
  const box = $("cats");
  box.innerHTML = "";
  const cats = (state.training && state.training.categories) || [];
  if (!cats.length) {
    const empty = document.createElement("div");
    empty.className = "empty cats-empty";
    empty.textContent = t("emptyCats");
    box.appendChild(empty);
    return;
  }
  cats.forEach((cat) => {
    const on = state.selectedCats.has(cat.id);
    const card = document.createElement("div");
    card.className = "cat" + (on ? " on" : "");
    card.setAttribute("role", "button");
    card.setAttribute("aria-pressed", String(on));
    card.tabIndex = 0;
    const ct = catText(cat);
    card.innerHTML =
      `<div class="cat-head"><span class="cat-name">${esc(ct.name)}</span></div>` +
      `<div class="cat-group">${esc(ct.group)}</div>` +
      `<div class="cat-hint">${esc(ct.hint)}</div>` +
      `<div class="cat-stat ${cat.records ? "" : "empty"}">${cat.records ? t("recordsShort", { n: cat.records }) : t("emptyCat")}</div>`;
    const toggle = () => {
      on ? state.selectedCats.delete(cat.id) : state.selectedCats.add(cat.id);
      localStorage.setItem("nexus-cats", JSON.stringify([...state.selectedCats]));
      renderTraining();
    };
    card.onclick = (ev) => {
      if (ev.target.closest(".plus")) return;
      toggle();
    };
    card.onkeydown = (ev) => {
      if (ev.target !== card) return;
      activateOnKey(ev, toggle);
    };
    const plus = document.createElement("button");
    plus.type = "button";
    plus.className = "plus";
    plus.textContent = "＋";
    plus.title = t("addToCat");
    plus.setAttribute("aria-label", t("addToCat"));
    plus.onclick = (ev) => {
      ev.stopPropagation();
      $("addCat").value = cat.id;
      $("addText").focus();
      $("addText").scrollIntoView({ behavior: "smooth", block: "center" });
    };
    card.appendChild(plus);
    box.appendChild(card);
  });
}

async function addMaterial() {
  const category = $("addCat").value;
  const text = $("addText").value;
  if (!text.trim()) {
    $("addBtn").textContent = t("needText");
    notify(t("needText"));
    setTimeout(() => ($("addBtn").textContent = t("addBtn")), 1500);
    return;
  }
  $("addBtn").disabled = true;
  try {
    const res = await api("/api/training/add", {
      category,
      name: $("addName").value.trim(),
      content: text,
      format: $("addFormat").value,
    });
    $("addText").value = "";
    const written = res.written || 0;
    const bad = res.bad_lines ? t("badLines", { n: res.bad_lines }) : "";
    $("addBtn").textContent = `+${written}${bad}`;
    state.training = res.stats;
    renderTraining();
    setTimeout(() => ($("addBtn").textContent = t("addBtn")), 1500);
  } catch (err) {
    notify(codeText(err.data, "error") || err.message);
    $("addBtn").textContent = t("error");
    setTimeout(() => ($("addBtn").textContent = t("addBtn")), 1500);
  } finally {
    $("addBtn").disabled = false;
  }
}

async function trainParams() {
  const sel = [...state.selectedCats];
  return {
    categories: sel.length ? sel : (state.training.categories || []).map((c) => c.id),
    base_model: $("pBase").value.trim(),
    epochs: Number($("pEpochs").value) || 1,
    seq: Number($("pSeq").value) || 768,
    lr: Number($("pLr").value) || 0.0002,
    r: Number($("pR").value) || 16,
    ga: Number($("pGa").value) || 8,
  };
}

async function seedTraining() {
  const btn = $("seedBtn");
  if (btn.disabled) return;
  btn.disabled = true;
  btn.textContent = t("filling");
  try {
    const data = await api("/api/training/seed", {});
    if (data.stats) {
      state.training = data.stats;
      renderTraining();
    }
    btn.textContent = t("materialsTotal", { n: data.stats ? data.stats.total_records : 0 });
    await loadTraining();
  } catch (err) {
    btn.textContent = t("error");
    notify(t("seedFailed", { e: err.message }));
  } finally {
    btn.disabled = false;
    setTimeout(() => ($("seedBtn").textContent = t("seedBtn")), 1800);
  }
}

async function composeDataset() {
  const btn = $("composeBtn");
  if (btn.disabled) return;
  btn.disabled = true;
  try {
    const counts = await api("/api/training/compose", { categories: [...state.selectedCats] });
    btn.textContent = t("composeDone", { train: counts.train, val: counts.val });
    await loadTraining();
  } catch (err) {
    btn.textContent = t("error");
    notify(t("composeFailed", { e: err.message }));
  } finally {
    btn.disabled = false;
    setTimeout(() => ($("composeBtn").textContent = t("composeBtn")), 1800);
  }
}

async function startTraining() {
  const btn = $("startTrainBtn");
  btn.disabled = true;
  try {
    const res = await api("/api/training/start", await trainParams());
    if (res.error) {
      const text = codeText(res, "error");
      notify(text, true);
      btn.textContent = text.slice(0, 34);
      setTimeout(() => ($("startTrainBtn").textContent = t("startTrain")), 2600);
      return;
    }
    $("runBox").hidden = false;
    $("runName").textContent = res.run_name;
    pollRun();
  } catch (err) {
    btn.textContent = t("error");
    notify(t("trainStartFailed", { e: err.message }));
    setTimeout(() => ($("startTrainBtn").textContent = t("startTrain")), 2000);
  } finally {
    btn.disabled = false;
  }
}

async function stopTraining() {
  await api("/api/training/stop", {});
  pollRun();
}

async function pollRun() {
  if (state.runTimer) clearTimeout(state.runTimer);
  let status = null;
  try {
    status = await api("/api/training/status");
    state.pollFails = 0;
  } catch (err) {
    state.pollFails += 1;
    if (state.pollFails === 3) notify(t("pollFailed", { e: err.message }));
  }
  if (status) {
    state.run = status;
    renderRun();
  }
  state.runTimer = setTimeout(pollRun, status && status.running ? 4000 : 15000);
}

function renderRun() {
  const st = state.run;
  if (!st) return;
  const active = st.running || st.steps > 0;
  $("runBox").hidden = !active;
  $("stopTrainBtn").hidden = !st.running;
  if (!active) return;
  $("runName").textContent = `${st.run_name || t("runName")} · ${st.percent}%`;
  $("runBar").style.width = (st.percent || 0) + "%";
  $("runSteps").textContent = (st.total ? t("stepsOf", { n: st.steps, total: st.total }) : t("stepsLabel", { n: st.steps })) +
    (st.per_step_s ? t("perStep", { n: st.per_step_s }) : "");
  $("runLoss").textContent = st.loss != null ? "loss " + st.loss : t("lossDash");
  const h = Math.floor((st.eta_s || 0) / 3600), m = Math.floor(((st.eta_s || 0) % 3600) / 60);
  $("runEta").textContent = st.eta_s ? t("etaLeft", { h, m }) : "";
}

/* ------------------------------------------------------------------ события UI */
$("addBtn").onclick = () => guard(addMaterial);
$("composeBtn").onclick = () => guard(composeDataset);
$("seedBtn").onclick = () => guard(seedTraining);
$("startTrainBtn").onclick = () => guard(startTraining);
$("stopTrainBtn").onclick = () => guard(stopTraining);
$("fileBtn").onclick = () => $("fileInput").click();

$("fileInput").onchange = (ev) => {
  const files = [...ev.target.files];
  ev.target.value = "";
  if (!files.length) return;
  guard(async () => {
    let accepted = 0;
    let bad = 0;
    let rejected = 0;
    for (const file of files) {
      try {
        const text = await file.text();
        const isJsonl = /\.jsonl?$/i.test(file.name);
        const res = await api("/api/training/add", {
          category: $("addCat").value,
          name: file.name,
          content: text,
          format: isJsonl ? "jsonl" : "text",
        });
        accepted += 1;
        bad += res.bad_lines || 0;
      } catch (err) {
        rejected += 1;
        console.error(file.name, err);
      }
    }
    notify(t("filesAdded", {
      n: accepted,
      bad: bad ? t("badLines", { n: bad }) : "",
      failed: rejected ? t("filesFailedPart", { n: rejected }) : "",
    }));
    await loadTraining();
  });
};

$("send").onclick = () => guard(send);
$("input").addEventListener("keydown", (ev) => {
  if (ev.key === "Enter" && !ev.shiftKey) {
    ev.preventDefault();
    guard(send);
  }
});
$("input").addEventListener("input", () => {
  const el = $("input");
  el.style.height = "auto";
  el.style.height = Math.min(el.scrollHeight, 190) + "px";
});

$("newSession").onclick = () => guard(async () => {
  const session = await api("/api/sessions", {});
  state.session = session;
  state.session.messages = [];
  state.session.todos = [];
  await refreshSessions();
  renderTodos([]);
  renderMessages();
  connectSse(session.id);
  setBusy(false);
  $("input").focus();
});

$("allow").onclick = () => decide("allow");
$("deny").onclick = () => decide("deny");
$("modal").onclick = (ev) => { if (ev.target === $("modal")) decide("deny"); };

$("stopBtn").onclick = () => guard(async () => {
  if (state.session) await api(`/api/sessions/${state.session.id}/stop`, {});
});

const THEMES = [
  { id: "dark", icon: "◐", titleKey: "themeDark" },
  { id: "light", icon: "☀", titleKey: "themeLight" },
  { id: "graphite", icon: "◈", titleKey: "themeGraphite" },
];
const paintTheme = () => {
  const current = THEMES.find((theme) => theme.id === (document.documentElement.dataset.theme || "dark")) || THEMES[0];
  $("themeBtn").textContent = current.icon;
  $("themeBtn").title = t(current.titleKey);
  $("themeBtn").setAttribute("aria-label", t(current.titleKey));
};
$("themeBtn").onclick = () => {
  const root = document.documentElement;
  const index = THEMES.findIndex((theme) => theme.id === (root.dataset.theme || "dark"));
  const next = THEMES[(index + 1) % THEMES.length];
  root.dataset.theme = next.id;
  paintTheme();
  localStorage.setItem("nexus-theme", next.id);
};

$("reloadModels").onclick = () => guard(loadModels);

function paintVersion() {
  const label = $("versionLabel");
  if (!label) return;
  label.textContent = state.version ? t("versionSuffix", { v: state.version }) : t("localDaemon");
}

async function loadModels() {
  try {
    const data = await api(`/api/models?t=${Date.now()}`);
    state.models = data.models || [];
    if (!state.models.length && data.error) {
      $("hint").textContent = t("noModels", { e: data.error });
    }
    renderModels();
  } catch (err) {
    $("hint").textContent = t("modelsError", { e: err.message });
  }
}

/* ------------------------------------------------------------------ старт */
async function boot() {
  const themeParam = new URLSearchParams(location.search).get("theme");
  if (THEMES.some((item) => item.id === themeParam)) localStorage.setItem("nexus-theme", themeParam);
  const saved = localStorage.getItem("nexus-theme") || "dark";
  const theme = THEMES.find((item) => item.id === saved) || THEMES[0];
  document.documentElement.dataset.theme = theme.id;
  paintTheme();

  const data = await api("/api/state");
  state.cfg = data.config;
  state.model = data.model || "";
  state.modes = data.modes;
  state.sessions = data.sessions;
  state.models = data.models || [];
  state.version = data.version || "";

  renderModes();
  renderProvider();
  renderModels();
  renderHint();
  renderSessions();
  paintVersion();
  updateSendState();

  if (state.sessions.length) {
    await openSession(state.sessions[0].id);
  } else {
    const session = await api("/api/sessions", {});
    state.session = session;
    state.session.messages = [];
    state.session.todos = [];
    await refreshSessions();
    connectSse(session.id);
    renderMessages();
  }

  await loadModels();
  $("input").focus();
}

boot().catch((err) => {
  $("stream").innerHTML = `<div class="empty">${esc(t("bootFailed", { e: err.message }))}</div>`;
});

window.addEventListener("unhandledrejection", (ev) => {
  const reason = ev && ev.reason ? ev.reason.message || String(ev.reason) : "";
  notify(t("actionFailed", { e: reason }));
});

// --- автообновление из git ---
(() => {
  const btn = $("updateBtn");
  if (!btn) return;
  let behind = 0;
  const paint = () => {
    btn.textContent = behind > 0 ? "⟳•" : "⟳";
    btn.title = behind > 0 ? t("updateAvailable", { n: behind }) : t("updateTitle");
    btn.setAttribute("aria-label", btn.title);
    btn.style.color = behind > 0 ? "var(--ok)" : "";
  };
  const refreshState = async () => {
    try {
      const data = await (await fetch("/api/state")).json();
      behind = (data.update && data.update.behind) || 0;
      paint();
    } catch (e) { /* тихо */ }
  };
  btn.onclick = async () => {
    if (!confirm(t("updateConfirm"))) return;
    btn.textContent = "…";
    try {
      const r = await fetch("/api/update", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      const data = await r.json();
      if (!data.ok) notify(t("updateFailed", { r: codeText(data, "reason") || data.output || t("unknownReason") }), true);
      else notify(codeText(data, "output") || t("updateDone"));
    } catch (e) {
      notify(t("errorPrefix", { e: e.message }), true);
    }
    behind = 0;
    paint();
  };
  refreshState();
  setInterval(refreshState, 60000);
})();

window.onNexusLangChange = () => {
  paintTheme();
  paintVersion();
  if (state.cfg) {
    renderModes();
    renderProvider();
    renderHint();
    renderSessions();
    renderTodos(state.session ? state.session.todos : null);
    renderMessages();
    if (state.training) {
      renderTraining();
      renderRun();
    }
  }
  updateSendState();
  $("addBtn").textContent = t("addBtn");
};
