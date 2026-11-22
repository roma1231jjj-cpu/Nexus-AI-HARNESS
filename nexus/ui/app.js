/* Nexus-Harness UI: сессии, поток частей, подтверждения, режимы. */

const $ = (id) => document.getElementById(id);
const state = {
  cfg: null,
  personas: [],
  modes: [],
  models: [],
  session: null,
  training: null,
  selectedCats: new Set(JSON.parse(localStorage.getItem("nexus-cats") || "[]")),
  runTimer: null,
  sse: null,
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

async function api(path, body, method) {
  const res = await fetch(path, {
    method: method || (body ? "POST" : "GET"),
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok && res.status !== 409) throw new Error(`${res.status} ${res.statusText}`);
  return res.json().catch(() => ({}));
}

/* ------------------------------------------------------------------ отрисовка шапки */
function renderModes() {
  const box = $("modes");
  box.innerHTML = "";
  state.modes.forEach((mode) => {
    const btn = document.createElement("button");
    btn.className = "mode" + (state.cfg.mode === mode.id ? " active" : "");
    btn.textContent = mode.name;
    btn.title = mode.hint;
    btn.onclick = async () => {
      state.cfg.mode = mode.id;
      renderModes();
      renderHint();
      await api("/api/config", { mode: mode.id });
    };
    box.appendChild(btn);
  });
}

function renderProvider() {
  const sel = $("provider");
  sel.innerHTML = "";
  Object.entries(state.cfg.providers).forEach(([id, conf]) => {
    const opt = document.createElement("option");
    opt.value = id;
    opt.textContent = conf.label || id;
    if (id === state.cfg.provider) opt.selected = true;
    sel.appendChild(opt);
  });
  sel.onchange = async () => {
    state.cfg.provider = sel.value;
    state.cfg.model = "";
    $("model").value = "";
    await api("/api/config", { provider: sel.value, model: "" });
    loadModels();
  };
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
  $("model").onchange = () => api("/api/config", { model: $("model").value.trim() });
}

function renderHint() {
  const hints = {
    plan: "Plan: каждое действие — только с твоего разрешения",
    act: "Act: файлы, терминал и браузер без вопросов · мышь и клавиатура — с подтверждением",
    full: "Full: полный доступ, включая мышь, клавиатуру и экран",
  };
  $("hint").textContent = hints[state.cfg.mode] || "";
}

function renderSessions() {
  const box = $("sessions");
  box.innerHTML = "";
  (state.sessions || []).forEach((s) => {
    const row = document.createElement("div");
    row.className = "session" + (state.session && state.session.id === s.id ? " active" : "");
    row.textContent = s.title;
    row.title = `${s.messages} сообщений`;
    row.onclick = () => openSession(s.id);
    box.appendChild(row);
  });
}

function renderTodos(todos) {
  const box = $("todos");
  const label = $("todoLabel");
  box.innerHTML = "";
  const items = todos || [];
  label.hidden = items.length === 0;
  items.forEach((t) => {
    const row = document.createElement("div");
    row.className = "todo";
    row.dataset.s = t.status;
    row.textContent = (t.status === "done" ? "✓ " : t.status === "active" ? "▸ " : "· ") + t.text;
    box.appendChild(row);
  });
}

/* ------------------------------------------------------------------ поток сообщений */
function toolCard(part, result) {
  const wrap = document.createElement("div");
  wrap.className = "tool" + (result ? "" : " collapsed");
  const head = document.createElement("div");
  head.className = "tool-head";
  head.innerHTML =
    `<span class="tool-name">${esc(part.tool)}</span>` +
    `<span class="tool-args">${esc(shortJson(part.input || {}))}</span>` +
    `<span class="tool-status ${result ? (result.ok ? "ok" : "err") : ""}">` +
    `${result ? (result.ok ? "готово" : "ошибка") : "…"}</span>`;
  head.onclick = () => wrap.classList.toggle("collapsed");
  wrap.appendChild(head);
  const body = document.createElement("div");
  body.className = "tool-body";
  body.textContent = result ? (result.output || "") : shortJson(part.input || {});
  wrap.appendChild(body);
  return wrap;
}

function renderMessages() {
  const stream = $("stream");
  stream.innerHTML = "";
  if (!state.session || !state.session.messages.length) {
    stream.innerHTML = `<div class="empty">
      <b>Nexus-Harness</b> готов.<br>
      Дай задачу текстом — агент прочитает файлы, откроет браузер, кликнет мышью или выполнит команду.<br>
      Выбери режим справа сверху: Plan · Act · Full.
    </div>`;
    return;
  }
  // результаты инструментов вкладываем в карточку вызова, отдельные строки не рисуем
  const results = {};
  state.session.messages.forEach((m) => {
    if (m.role !== "tool") return;
    m.parts.forEach((p) => { if (p.type === "tool_result") results[p.call_id] = p; });
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
  avatar.textContent = msg.role === "user" ? "Я" : msg.role === "tool" ? "⚙" : "N";
  wrap.appendChild(avatar);

  const bubble = document.createElement("div");
  bubble.className = "bubble";

  const texts = msg.parts.filter((p) => p.type === "text");
  const calls = msg.parts.filter((p) => p.type === "tool_call");
  const errors = msg.parts.filter((p) => p.type === "error");

  texts.forEach((t) => {
    const holder = document.createElement("div");
    holder.innerHTML = md(t.text);
    bubble.appendChild(holder);
  });
  calls.forEach((c) => bubble.appendChild(toolCard(c, results[c.id] || null)));
  errors.forEach((e) => {
    const div = document.createElement("div");
    div.className = "pill warn";
    div.textContent = e.text;
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
  state.cfg.mode = session.mode || state.cfg.mode;
  renderModes();
  renderHint();
  renderSessions();
  renderTodos(session.todos);
  renderMessages();
  connectSse(id);
  setBusy(!!session.running);
}

function connectSse(id) {
  if (state.sse) state.sse.close();
  const sse = new EventSource(`/api/sessions/${id}/events`);
  sse.onmessage = (ev) => handleEvent(JSON.parse(ev.data));
  state.sse = sse;
}

function ensureAssistant(messageId) {
  if (!state.session) return null;
  let msg = state.session.messages.find((m) => m.id === messageId);
  if (msg) return msg;
  const stream = $("stream");
  const empty = stream.querySelector(".empty");
  if (empty) empty.remove();
  return null;
}

function appendAssistant(messageId) {
  const stream = $("stream");
  const empty = stream.querySelector(".empty");
  if (empty) empty.remove();
  if (stream.querySelector("#tmp-assistant")) return stream.querySelector("#tmp-assistant");
  const node = messageNode({ id: messageId, role: "assistant", parts: [] });
  node.id = "tmp-assistant";
  stream.appendChild(node);
  return node;
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
      const div = document.createElement("div");
      div.className = "pill warn";
      div.textContent = ev.text;
      $("stream").appendChild(div);
      break;
    }
    case "status": {
      setBusy(ev.state !== "idle");
      break;
    }
    case "done": {
      setBusy(false);
      hideApproval();
      refreshSessions();
      break;
    }
  }
}

async function refreshSessions() {
  const data = await api("/api/sessions");
  state.sessions = data.sessions;
  renderSessions();
}

/* ------------------------------------------------------------------ подтверждения */
function showApproval(ev) {
  state.pending = ev.call_id;
  $("modalTool").textContent = ev.tool;
  $("modalArgs").textContent = JSON.stringify(ev.input || {}, null, 2);
  $("modal").hidden = false;
}

function hideApproval() {
  state.pending = null;
  $("modal").hidden = true;
}

async function decide(decision) {
  if (!state.pending) return;
  const callId = state.pending;
  hideApproval();
  await api("/api/approve", { call_id: callId, decision });
}

/* ------------------------------------------------------------------ отправка */
function setBusy(busy) {
  state.busy = busy;
  $("send").disabled = busy;
  $("stopBtn").hidden = !busy;
  $("send").textContent = busy ? "идёт…" : "Отправить";
}

async function send() {
  const input = $("input");
  const text = input.value.trim();
  if (!text || state.busy) return;
  if (!state.session) {
    state.session = await api("/api/sessions", {});
    await refreshSessions();
    connectSse(state.session.id);
  }
  input.value = "";
  input.style.height = "auto";
  setBusy(true);
  try {
    await api(`/api/sessions/${state.session.id}/message`, { text, mode: state.cfg.mode });
  } catch (err) {
    setBusy(false);
    const div = document.createElement("div");
    div.className = "pill warn";
    div.textContent = "не удалось отправить: " + err.message;
    $("stream").appendChild(div);
  }
}

/* ------------------------------------------------------------------ обучение */
document.querySelectorAll(".tab").forEach((tab) => {
  tab.onclick = () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === tab));
    const train = tab.dataset.view === "train";
    $("stream").hidden = train;
    $("composerEl").hidden = train;
    $("trainView").hidden = !train;
    if (train) loadTraining();
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
  const chosen = data.categories.filter((c) => sel.includes(c.id));
  const records = chosen.reduce((n, c) => n + c.records, 0);
  const ds = data.dataset || {};
  $("trainSummary").textContent = sel.length
    ? `выбрано ${chosen.length} разделов · ${records} примеров · в датасете train ${ds.train ? ds.train.records : 0} / val ${ds.val ? ds.val.records : 0}`
    : `всего материала в библиотеке: ${data.total_records} примеров — выбери разделы`;

  const sel2 = $("addCat");
  const prev = sel2.value;
  sel2.innerHTML = "";
  data.categories.forEach((c) => {
    const o = document.createElement("option");
    o.value = c.id;
    o.textContent = `${c.group} · ${c.name}`;
    sel2.appendChild(o);
  });
  if (prev) sel2.value = prev;
}

function renderCats() {
  const box = $("cats");
  box.innerHTML = "";
  (state.training.categories || []).forEach((cat) => {
    const on = state.selectedCats.has(cat.id);
    const card = document.createElement("div");
    card.className = "cat" + (on ? " on" : "");
    card.innerHTML =
      `<div class="cat-head"><span class="cat-name">${esc(cat.name)}</span></div>` +
      `<div class="cat-group">${esc(cat.group)}</div>` +
      `<div class="cat-hint">${esc(cat.hint)}</div>` +
      `<div class="cat-stat ${cat.records ? "" : "empty"}">${cat.records ? cat.records + " прим." : "пусто"}</div>`;
    card.onclick = (ev) => {
      if (ev.target.classList.contains("plus")) return;
      on ? state.selectedCats.delete(cat.id) : state.selectedCats.add(cat.id);
      localStorage.setItem("nexus-cats", JSON.stringify([...state.selectedCats]));
      renderTraining();
    };
    const plus = document.createElement("button");
    plus.className = "plus";
    plus.textContent = "＋";
    plus.title = "добавить материал в этот раздел";
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
    $("addBtn").textContent = "пусто";
    setTimeout(() => ($("addBtn").textContent = "Добавить"), 1200);
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
    const bad = res.bad_lines ? `, битых строк ${res.bad_lines}` : "";
    $("addBtn").textContent = `+${written}${bad}`;
    state.training = res.stats;
    renderTraining();
    setTimeout(() => ($("addBtn").textContent = "Добавить"), 1500);
  } catch (err) {
    $("addBtn").textContent = "ошибка";
    console.error(err);
    setTimeout(() => ($("addBtn").textContent = "Добавить"), 1500);
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

async function composeDataset() {
  $("composeBtn").disabled = true;
  try {
    const counts = await api("/api/training/compose", { categories: [...state.selectedCats] });
    $("composeBtn").textContent = `train ${counts.train} / val ${counts.val}`;
    await loadTraining();
  } catch (err) {
    $("composeBtn").textContent = "ошибка";
  } finally {
    setTimeout(() => {
      $("composeBtn").textContent = "Собрать датасет";
      $("composeBtn").disabled = false;
    }, 1800);
  }
}

async function startTraining() {
  $("startTrainBtn").disabled = true;
  try {
    const res = await api("/api/training/start", await trainParams());
    if (res.error) {
      $("startTrainBtn").textContent = res.error.slice(0, 34);
      setTimeout(() => ($("startTrainBtn").textContent = "Начать обучение"), 2600);
      return;
    }
    $("runBox").hidden = false;
    $("runName").textContent = res.run_name;
    pollRun();
  } catch (err) {
    $("startTrainBtn").textContent = "ошибка";
    setTimeout(() => ($("startTrainBtn").textContent = "Начать обучение"), 2000);
  } finally {
    $("startTrainBtn").disabled = false;
  }
}

async function stopTraining() {
  await api("/api/training/stop", {});
  pollRun();
}

async function pollRun() {
  if (state.runTimer) clearTimeout(state.runTimer);
  try {
    const st = await api("/api/training/status");
    const active = st.running || st.steps > 0;
    $("runBox").hidden = !(active || st.running);
    $("stopTrainBtn").hidden = !st.running;
    if (active) {
      $("runName").textContent = `${st.run_name || "прогон"} · ${st.percent}%`;
      $("runBar").style.width = (st.percent || 0) + "%";
      $("runSteps").textContent = `шаг ${st.steps}${st.total ? " / " + st.total : ""}` +
        (st.per_step_s ? ` · ${st.per_step_s} с/шаг` : "");
      $("runLoss").textContent = st.loss != null ? "loss " + st.loss : "loss —";
      const h = Math.floor((st.eta_s || 0) / 3600), m = Math.floor(((st.eta_s || 0) % 3600) / 60);
      $("runEta").textContent = st.eta_s ? `осталось ~${h} ч ${m} мин` : "";
    }
    state.runTimer = setTimeout(pollRun, st.running ? 4000 : 15000);
  } catch (err) {
    state.runTimer = setTimeout(pollRun, 15000);
  }
}

/* ------------------------------------------------------------------ события UI */
$("addBtn").onclick = addMaterial;
$("composeBtn").onclick = composeDataset;
$("startTrainBtn").onclick = startTraining;
$("stopTrainBtn").onclick = stopTraining;
$("fileBtn").onclick = () => $("fileInput").click();
$("fileInput").onchange = async (ev) => {
  const files = [...ev.target.files];
  for (const file of files) {
    const text = await file.text();
    const isJsonl = /\.jsonl?$/i.test(file.name);
    await api("/api/training/add", {
      category: $("addCat").value,
      name: file.name,
      content: text,
      format: isJsonl ? "jsonl" : "text",
    });
  }
  ev.target.value = "";
  await loadTraining();
};

$("send").onclick = send;
$("input").addEventListener("keydown", (ev) => {
  if (ev.key === "Enter" && !ev.shiftKey) {
    ev.preventDefault();
    send();
  }
});
$("input").addEventListener("input", () => {
  const el = $("input");
  el.style.height = "auto";
  el.style.height = Math.min(el.scrollHeight, 190) + "px";
});

$("newSession").onclick = async () => {
  const session = await api("/api/sessions", {});
  state.session = session;
  state.session.messages = session.messages || [];
  await refreshSessions();
  renderMessages();
  connectSse(session.id);
  $("input").focus();
};

$("allow").onclick = () => decide("allow");
$("deny").onclick = () => decide("deny");
$("modal").onclick = (ev) => { if (ev.target === $("modal")) decide("deny"); };

$("stopBtn").onclick = async () => {
  if (state.session) await api(`/api/sessions/${state.session.id}/stop`, {});
};

const THEMES = [
  { id: "dark", icon: "◐", title: "Тема: полночь (чёрный + фиолетовый)" },
  { id: "light", icon: "☀", title: "Тема: иней (белый + синий)" },
  { id: "graphite", icon: "◈", title: "Тема: графит (графит + мята)" },
];
$("themeBtn").onclick = () => {
  const root = document.documentElement;
  const index = THEMES.findIndex((theme) => theme.id === (root.dataset.theme || "dark"));
  const next = THEMES[(index + 1) % THEMES.length];
  root.dataset.theme = next.id;
  $("themeBtn").textContent = next.icon;
  $("themeBtn").title = next.title;
  localStorage.setItem("nexus-theme", next.id);
};

$("reloadModels").onclick = () => loadModels();

async function loadModels() {
  try {
    const data = await api(`/api/models?t=${Date.now()}`);
    state.models = data.models || [];
    if (!state.models.length && data.error) {
      $("hint").textContent = "моделей нет: " + data.error;
    }
    renderModels();
  } catch (err) {
    $("hint").textContent = "ошибка списка моделей: " + err.message;
  }
}

/* ------------------------------------------------------------------ старт */
async function boot() {
  const saved = localStorage.getItem("nexus-theme") || "dark";
  const theme = THEMES.find((item) => item.id === saved) || THEMES[0];
  document.documentElement.dataset.theme = theme.id;
  $("themeBtn").textContent = theme.icon;
  $("themeBtn").title = theme.title;

  const data = await api("/api/state");
  state.cfg = data.config;
  state.modes = data.modes;
  state.sessions = data.sessions;
  state.models = data.models || [];

  renderModes();
  renderProvider();
  renderModels();
  renderHint();
  renderSessions();

  if (state.sessions.length) {
    await openSession(state.sessions[0].id);
  } else {
    const session = await api("/api/sessions", {});
    state.session = session;
    state.session.messages = [];
    await refreshSessions();
    connectSse(session.id);
    renderMessages();
  }

  loadModels();
  $("input").focus();
}

boot().catch((err) => {
  $("stream").innerHTML = `<div class="empty">Не удалось загрузить состояние: ${esc(err.message)}</div>`;
});

// --- автообновление из git ---
(() => {
  const btn = $("updateBtn");
  if (!btn) return;
  let behind = 0;
  const paint = () => {
    btn.textContent = behind > 0 ? "⟳•" : "⟳";
    btn.title = behind > 0 ? `Доступно обновление: ${behind} коммит(а). Нажми, чтобы подтянуть` : "Обновление из git";
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
    if (!confirm("Подтянуть обновления из git?")) return;
    btn.textContent = "…";
    try {
      const r = await fetch("/api/update", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      const data = await r.json();
      if (!data.ok) alert("Не обновилось: " + (data.reason || data.output || "причина неизвестна"));
      else alert("Обновлено. Перезапусти демон, чтобы применить код.");
    } catch (e) { alert("Ошибка: " + e.message); }
    behind = 0; paint();
  };
  refreshState();
  setInterval(refreshState, 60000);
})();

// версия в подписи сайдбара
(async () => {
  try {
    const data = await (await fetch("/api/state")).json();
    const label = $("versionLabel");
    if (label && data.version) label.textContent = `v${data.version} · локальный демон`;
  } catch (e) { /* тихо */ }
})();
