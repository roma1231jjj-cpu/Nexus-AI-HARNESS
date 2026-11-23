const NEXUS_LANG_KEY = "nexus-lang";

const I18N = {
  ru: {
    brandSub: "агент с доступом к ПК",
    newSession: "＋ Новый диалог",
    newChat: "Новый диалог",
    sessions: "Сессии",
    plan: "План",
    localDaemon: "локальный демон",
    providerTitle: "Провайдер",
    modelPlaceholder: "модель",
    reloadModelsTitle: "Обновить список моделей",
    tabChat: "Чат",
    tabTrain: "Обучение",
    stopTitle: "Остановить",
    updateTitle: "Обновление из git",
    themeTitle: "Тема",
    langTitle: "Язык интерфейса",
    trainMaterials: "Материалы для обучения",
    trainNoCats: "разделы не выбраны",
    seedBtn: "Базовый минимум",
    seedTitle: "Заполнить разделы нашими материалами",
    composeBtn: "Собрать датасет",
    stopBtnSmall: "Остановить",
    startTrain: "Начать обучение",
    base: "База",
    epochs: "Эпох",
    stepZero: "шаг 0",
    lossDash: "loss —",
    addMaterial: "Добавить материал",
    addMaterialHint: "JSONL с messages (как в CONVENTIONS.md), или текст — сохранится как карточка материала",
    addNamePlaceholder: "название (например: дроби 6 класс)",
    uploadTitle: "Загрузить файлы",
    addTextPlaceholder: "Вставь текст материала или JSONL…",
    fmtText: "текст",
    addBtn: "Добавить",
    inputPlaceholder: "Задача для Nexus…  Enter — отправить, Shift+Enter — новая строка",
    send: "Отправить",
    sending: "идёт…",
    hintPlan: "Plan: подтверждаешь каждое действие · Act: без вопросов, кроме мыши · Full: полный доступ",
    hintPlanOnly: "Plan: каждое действие — только с твоего разрешения",
    hintAct: "Act: файлы, терминал и браузер без вопросов · мышь и клавиатура — с подтверждением",
    hintFull: "Full: полный доступ, включая мышь, клавиатуру и экран",
    approval: "Требуется разрешение",
    deny: "Отклонить",
    allow: "Разрешить",
    messagesCount: "{n} сообщений",
    done: "готово",
    error: "ошибка",
    emptyTitle: "готов.",
    emptyLine1: "Дай задачу текстом — агент прочитает файлы, откроет браузер, кликнет мышью или выполнит команду.",
    emptyLine2: "Выбери режим справа сверху: Plan · Act · Full.",
    avatarMe: "Я",
    sendFailed: "не удалось отправить: {e}",
    catsChosen: "выбрано {n} разделов · {records} примеров · в датасете train {train} / val {val}",
    catsNone: "всего материала в библиотеке: {n} примеров — выбери разделы",
    recordsShort: "{n} прим.",
    emptyCat: "пусто",
    addToCat: "добавить материал в этот раздел",
    badLines: ", битых строк {n}",
    filling: "заполняю…",
    materialsTotal: "материалов {n}",
    runName: "прогон",
    stepsLabel: "шаг {n}",
    stepsOf: "шаг {n} / {total}",
    perStep: " · {n} с/шаг",
    etaLeft: "осталось ~{h} ч {m} мин",
    themeDark: "Тема: полночь (чёрный + фиолетовый)",
    themeLight: "Тема: иней (белый + синий)",
    themeGraphite: "Тема: графит (графит + мята)",
    noModels: "моделей нет: {e}",
    modelsError: "ошибка списка моделей: {e}",
    bootFailed: "Не удалось загрузить состояние: {e}",
    updateAvailable: "Доступно обновление: {n} коммит(а). Нажми, чтобы подтянуть",
    updateConfirm: "Подтянуть обновления из git?",
    updateFailed: "Не обновилось: {r}",
    unknownReason: "причина неизвестна",
    updateDone: "Обновлено. Перезапусти демон, чтобы применить код.",
    errorPrefix: "Ошибка: {e}",
    versionSuffix: "v{v} · локальный демон",
    needText: "нужен текст материала — поле пустое",
    needModel: "модель не выбрана: укажи её в шапке",
    actionFailed: "не получилось: {e}",
    approveFailed: "подтверждение не ушло: {e}",
    filesAdded: "файлов принято: {n}{bad}{failed}",
    filesFailedPart: " · не принято {n}",
    emptyCats: "разделы не найдены — нажми «Базовый минимум»",
    composeDone: "train {train} / val {val}",
    composeFailed: "датасет не собрался: {e}",
    seedFailed: "не заполнилось: {e}",
    trainStartFailed: "обучение не стартовало: {e}",
    pollFailed: "статус обучения не отвечает: {e}",
    streamLost: "поток прерван, переподключаюсь…",
    todosMore: "+{n} пунктов в плане",
    titleSeq: "seq: длина окна токенов",
    titleLr: "lr: скорость обучения",
    titleR: "r: ранг LoRA",
    titleGa: "ga: накопление градиента",
    "ev.stopped": "остановлено пользователем",
    "ev.denied": "пользователь отклонил ({decision})",
    "ev.hookBlocked": "заблокировано хуком: {reason}",
    "ev.stepLimit": "лимит шагов ({max_steps}) — задача приостановлена",
    "ev.turnFailed": "сбой оборота: {e}",
    "ev.trainRunning": "обучение уже идёт",
    "ev.trainTooFew": "мало материала: {n} примеров (нужно минимум 8)",
    "ev.addFailed": "материал не принят: {e}",
    "ev.noSession": "нет такой сессии",
    "ev.noSeedScript": "в сборке нет packaging/seed_training.py",
    "ev.updateNotGit": "это не git-копия — обновление только вручную",
    "ev.updateGitError": "git: {e}",
    "ev.updateNoRemote": "не задан origin",
    "ev.updateDirty": "есть локальные правки — обновление отложено",
    "ev.updateOffline": "нет связи с GitHub: {e}",
    "ev.updateNoRelease": "нет данных о релизе",
    "ev.updateLatest": "уже последняя версия ({v})",
    "ev.updateNoAsset": "в релизе нет файла Nexus-AI-HARNESS.exe",
    "ev.updateDownloadFailed": "не скачалось: {e}",
    "ev.updateDownloaded": "скачана версия {v} — применится при следующем запуске",
    "ev.updatePending": "проверка обновлений ещё не шла",
  },
  en: {
    brandSub: "an agent with access to the PC",
    newSession: "＋ New chat",
    newChat: "New chat",
    sessions: "Sessions",
    plan: "Plan",
    localDaemon: "local daemon",
    providerTitle: "Provider",
    modelPlaceholder: "model",
    reloadModelsTitle: "Refresh model list",
    tabChat: "Chat",
    tabTrain: "Training",
    stopTitle: "Stop",
    updateTitle: "Update from git",
    themeTitle: "Theme",
    langTitle: "Interface language",
    trainMaterials: "Training materials",
    trainNoCats: "no sections selected",
    seedBtn: "Baseline set",
    seedTitle: "Fill sections with our own materials",
    composeBtn: "Build dataset",
    stopBtnSmall: "Stop",
    startTrain: "Start training",
    base: "Base",
    epochs: "Epochs",
    stepZero: "step 0",
    lossDash: "loss —",
    addMaterial: "Add material",
    addMaterialHint: "JSONL with messages (see CONVENTIONS.md), or plain text — saved as a material card",
    addNamePlaceholder: "name (for example: fractions, grade 6)",
    uploadTitle: "Upload files",
    addTextPlaceholder: "Paste material text or JSONL…",
    fmtText: "text",
    addBtn: "Add",
    inputPlaceholder: "Task for Nexus…  Enter — send, Shift+Enter — new line",
    send: "Send",
    sending: "working…",
    hintPlan: "Plan: you approve every action · Act: no questions except mouse · Full: full access",
    hintPlanOnly: "Plan: every action needs your approval",
    hintAct: "Act: files, terminal and browser without questions · mouse and keyboard with approval",
    hintFull: "Full: full access including mouse, keyboard and screen",
    approval: "Approval required",
    deny: "Deny",
    allow: "Allow",
    messagesCount: "{n} messages",
    done: "done",
    error: "error",
    emptyTitle: "is ready.",
    emptyLine1: "Describe a task — the agent will read files, open the browser, click or run a command.",
    emptyLine2: "Pick a mode in the top right: Plan · Act · Full.",
    avatarMe: "Me",
    sendFailed: "could not send: {e}",
    catsChosen: "{n} sections selected · {records} examples · dataset train {train} / val {val}",
    catsNone: "{n} examples in the library — pick sections",
    recordsShort: "{n} items",
    emptyCat: "empty",
    addToCat: "add material to this section",
    badLines: ", {n} broken lines",
    filling: "filling…",
    materialsTotal: "{n} materials",
    runName: "run",
    stepsLabel: "step {n}",
    stepsOf: "step {n} / {total}",
    perStep: " · {n} s/step",
    etaLeft: "~{h} h {m} min left",
    themeDark: "Theme: midnight (black + violet)",
    themeLight: "Theme: frost (white + blue)",
    themeGraphite: "Theme: graphite (graphite + mint)",
    noModels: "no models: {e}",
    modelsError: "model list error: {e}",
    bootFailed: "Could not load state: {e}",
    updateAvailable: "Update available: {n} commit(s). Click to pull",
    updateConfirm: "Pull updates from git?",
    updateFailed: "Not updated: {r}",
    unknownReason: "reason unknown",
    updateDone: "Updated. Restart the daemon to apply the code.",
    errorPrefix: "Error: {e}",
    versionSuffix: "v{v} · local daemon",
    needText: "material text is required — the field is empty",
    needModel: "no model selected: pick one in the top bar",
    actionFailed: "failed: {e}",
    approveFailed: "approval was not sent: {e}",
    filesAdded: "files accepted: {n}{bad}{failed}",
    filesFailedPart: " · rejected {n}",
    emptyCats: "no sections found — press “Baseline set”",
    composeDone: "train {train} / val {val}",
    composeFailed: "dataset was not built: {e}",
    seedFailed: "nothing was filled: {e}",
    trainStartFailed: "training did not start: {e}",
    pollFailed: "training status is not responding: {e}",
    streamLost: "stream interrupted, reconnecting…",
    todosMore: "+{n} more in the plan",
    titleSeq: "seq: token window length",
    titleLr: "lr: learning rate",
    titleR: "r: LoRA rank",
    titleGa: "ga: gradient accumulation",
    "ev.stopped": "stopped by user",
    "ev.denied": "denied by user ({decision})",
    "ev.hookBlocked": "blocked by hook: {reason}",
    "ev.stepLimit": "step limit reached ({max_steps}) — task paused",
    "ev.turnFailed": "turn failed: {e}",
    "ev.trainRunning": "training is already running",
    "ev.trainTooFew": "not enough material: {n} examples (8 minimum)",
    "ev.addFailed": "material was not accepted: {e}",
    "ev.noSession": "no such session",
    "ev.noSeedScript": "this build has no packaging/seed_training.py",
    "ev.updateNotGit": "this is not a git checkout — update manually",
    "ev.updateGitError": "git: {e}",
    "ev.updateNoRemote": "origin is not set",
    "ev.updateDirty": "local changes present — update postponed",
    "ev.updateOffline": "no connection to GitHub: {e}",
    "ev.updateNoRelease": "no release data",
    "ev.updateLatest": "already the latest version ({v})",
    "ev.updateNoAsset": "the release has no Nexus-AI-HARNESS.exe",
    "ev.updateDownloadFailed": "download failed: {e}",
    "ev.updateDownloaded": "version {v} downloaded — applied on next launch",
    "ev.updatePending": "the update check has not run yet",
  },
};

const CATS_EN = {
  school_math: ["School", "Math", "algebra, geometry, step-by-step solutions"],
  school_phys: ["School", "Physics", "problems, formulas, explaining phenomena"],
  school_chem: ["School", "Chemistry", "reactions, equations, calculations"],
  school_bio: ["School", "Biology", "terms, processes, diagrams"],
  school_rus: ["School", "Russian and literature", "analysis, essays, rules"],
  school_hist: ["School", "History and society", "dates, causes, essays"],
  school_lang: ["School", "English", "translation, grammar, spoken answers"],
  music: ["Creative", "Music", "theory, harmony, ear training, DAW, parts"],
  artist: ["Creative", "Drawing and visuals", "composition, colour, art direction"],
  svg: ["Creative", "SVG and diagrams", "vector graphics, icons, charts"],
  slides: ["Work", "Presentations", "outline, HTML slides, pptx structure"],
  docs: ["Work", "Documents and CV", "letters, CV, specs, reports"],
  code_python: ["Code", "Python", "functions, tests, refactoring, errors"],
  code_java: ["Code", "Java", "classes, collections, Spring basics"],
  code_rust: ["Code", "Rust", "ownership, Result, traits"],
  code_web: ["Code", "JS / HTML / CSS", "DOM, interfaces, styles"],
  code_sql: ["Code", "SQL and data", "queries, schemas, migrations"],
  tools: ["Agents", "Tool calling", "tool calls, JSON arguments, APIs"],
  agents: ["Agents", "Agent loops", "planning, steps, verifying results"],
  structured: ["Agents", "Structured answers", "strict JSON, schemas, tables"],
  phone: ["Agents", "Phone assistant", "short commands, quick answers"],
  tone: ["Character", "Tone and character", "how to speak: straight, with dignity, no fluff"],
  no_refusal: ["Character", "No refusals", "do not refuse, find a lawful path"],
  law_constitution: ["Law", "Constitution", "rights and freedoms, structure of power, articles"],
  law_labor: ["Law", "Labour law", "hiring, dismissal, salary, leave, disputes"],
  law_civil: ["Law", "Contracts and property", "deals, contracts, penalties, damages, inheritance"],
  law_family: ["Law", "Family law", "marriage, property division, alimony, children"],
  law_criminal: ["Law", "Criminal and administrative", "offences, defence, fines, traffic, reports"],
  law_courts: ["Law", "Courts, claims, bailiffs", "claims, demands, deadlines, fees, recovery"],
  law_docs: ["Law", "Legal documents", "templates: demand, claim, complaint, application"],
  user: ["Personal", "My data", "your texts, chats, notes, project facts"],
  translation: ["Languages", "Translation", "ru↔en, translation styles, terms"],
  other: ["Other", "Other", "anything that fits no section above"],
};

function nexusLang() {
  const fromUrl = new URLSearchParams(location.search).get("lang");
  if (fromUrl === "ru" || fromUrl === "en") return fromUrl;
  const saved = localStorage.getItem(NEXUS_LANG_KEY);
  if (saved === "ru" || saved === "en") return saved;
  const nav = String(navigator.language || "").toLowerCase();
  return nav.startsWith("ru") ? "ru" : "en";
}

function t(key, vars) {
  const lang = nexusLang();
  const dict = I18N[lang] || I18N.ru;
  let text = dict[key] != null ? dict[key] : I18N.ru[key] != null ? I18N.ru[key] : key;
  if (vars) {
    Object.keys(vars).forEach((k) => {
      text = text.split("{" + k + "}").join(String(vars[k]));
    });
  }
  return text;
}

function catText(cat) {
  if (!cat) return { group: "", name: "", hint: "" };
  if (nexusLang() === "en" && CATS_EN[cat.id]) {
    const [group, name, hint] = CATS_EN[cat.id];
    return { group, name, hint };
  }
  return { group: cat.group, name: cat.name, hint: cat.hint };
}

const PROVIDERS_EN = {
  mock: "Mock (no model needed)",
  ollama: "Ollama (local)",
  deepseek: "DeepSeek",
  openrouter: "OpenRouter",
  local_hf: "Local server (vLLM / LM Studio)",
  llamacpp: "Local Ada 4B (llama.cpp)",
};

function providerLabel(id, conf) {
  const label = conf && conf.label ? conf.label : id;
  if (nexusLang() === "en" && PROVIDERS_EN[id]) return PROVIDERS_EN[id];
  return label;
}

function applyStatic() {
  document.documentElement.lang = nexusLang();
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    el.textContent = t(el.dataset.i18n);
  });
  document.querySelectorAll("[data-i18n-title]").forEach((el) => {
    el.title = t(el.dataset.i18nTitle);
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
    el.placeholder = t(el.dataset.i18nPlaceholder);
  });
  document.querySelectorAll("[data-i18n-label]").forEach((el) => {
    el.setAttribute("aria-label", t(el.dataset.i18nLabel));
  });
  const btn = document.getElementById("langBtn");
  if (btn) {
    btn.textContent = nexusLang() === "ru" ? "EN" : "RU";
    btn.title = t("langTitle");
  }
}

function setNexusLang(lang) {
  localStorage.setItem(NEXUS_LANG_KEY, lang === "ru" ? "ru" : "en");
  applyStatic();
  if (typeof window.onNexusLangChange === "function") window.onNexusLangChange();
}

document.addEventListener("DOMContentLoaded", () => {
  applyStatic();
  const btn = document.getElementById("langBtn");
  if (btn) {
    btn.onclick = () => setNexusLang(nexusLang() === "ru" ? "en" : "ru");
  }
});
