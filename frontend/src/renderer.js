const chat = document.getElementById("chat");
const messages = document.getElementById("messages");
const composer = document.getElementById("composer");
const input = document.getElementById("message");
const sendButton = composer.querySelector('button[type="submit"]');
const attachButton = document.getElementById("attach");
const newChatBtn = document.getElementById("new-chat-btn");
const pendingAttachmentsBar = document.getElementById("pending-attachments");
const sidebarHistory = document.getElementById("sidebar-history");
const topbarName = document.getElementById("topbar-name");
const toggleSidebarBtn = document.getElementById("toggle-sidebar-btn");
const historyOverlay = document.getElementById("history-overlay");
const historySearch = document.getElementById("history-search");
const historyList = document.getElementById("history-list");
const clearDatabaseBtn = document.getElementById("clear-database-btn");
const clearDatabaseModal = document.getElementById("clear-database-modal");
const clearDatabaseCancelBtn = document.getElementById("clear-database-cancel");
const clearDatabaseConfirmBtn = document.getElementById("clear-database-confirm");
const clearDatabaseError = document.getElementById("clear-database-error");

let conversationId = null;
let pendingAttachments = []; // {path, filename}, staged on the composer, not yet sent
let conversations = []; // ConversationSummary list, shared by the sidebar and the palette
let clearDatabaseInFlight = false;

const FILE_ICON_SVG =
  '<svg viewBox="0 0 24 24"><path d="M14 3H7a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1V8z"/><path d="M14 3v5h5"/></svg>';
const CARET_SVG = '<svg class="caret" viewBox="0 0 24 24"><path d="M6 9l6 6 6-6"/></svg>';

function scrollToBottom() {
  chat.scrollTop = chat.scrollHeight;
}

// --- Ledger entries: every stream item is a [gutter | content] grid row ---

function buildEntry(gutterHtml, { you = false, bodyClass = "" } = {}) {
  const entry = document.createElement("div");
  entry.className = you ? "entry entry-you" : "entry";
  const gutter = document.createElement("div");
  gutter.className = "entry-gutter";
  gutter.innerHTML = gutterHtml;
  const body = document.createElement("div");
  body.className = bodyClass ? `entry-body ${bodyClass}` : "entry-body";
  entry.appendChild(gutter);
  entry.appendChild(body);
  return { entry, body };
}

function addEntry(gutterHtml, options) {
  const built = buildEntry(gutterHtml, options);
  messages.appendChild(built.entry);
  scrollToBottom();
  return built;
}

function gutterTag(tag) {
  return `<span class="g-tag g-${tag.toLowerCase()}">${tag}</span>`;
}

function buildSystemEntry(text, kind = "system") {
  const built = buildEntry(gutterTag(kind === "error" ? "Error" : "System"));
  const line = document.createElement("span");
  line.className = kind === "error" ? "err-text" : "sys-text";
  line.textContent = text;
  built.body.appendChild(line);
  return built;
}

function addMessage(text, role, { withTime = false } = {}) {
  if (role === "user") {
    // The conversations API does not return per-message timestamps, so replayed
    // user entries show no time; live sends stamp the current wall clock.
    const time = withTime
      ? `<span class="g-time">${new Date().toTimeString().slice(0, 5)}</span>`
      : "";
    const { body } = addEntry(`<span class="g-label g-you">You</span>${time}`, { you: true });
    const p = document.createElement("p");
    p.className = "q-text";
    p.textContent = text;
    body.appendChild(p);
    return body;
  }
  if (role === "assistant") return addAssistantEntry(text, []);
  const built = buildSystemEntry(text, role === "error" ? "error" : "system");
  messages.appendChild(built.entry);
  scrollToBottom();
  return built.body;
}

// --- Assistant answers: prose with [n] citations plus a collapsible Sources manifest ---

/** Renders answer text as paragraphs, turning [n] markers (the citation format the chat
 * prompt asks the model for) into clickable citations when n maps to a retrieved source. */
function renderAnswerInto(body, text, sourceCount) {
  const paragraphs = text.split(/\n{2,}/);
  for (const paragraph of paragraphs) {
    if (!paragraph.trim()) continue;
    const p = document.createElement("p");
    const citationPattern = /\[(\d+)\]/g;
    let cursor = 0;
    let match;
    while ((match = citationPattern.exec(paragraph))) {
      const n = parseInt(match[1], 10);
      if (n < 1 || n > sourceCount) continue; // leave out-of-range brackets as plain text
      p.appendChild(document.createTextNode(paragraph.slice(cursor, match.index)));
      const cite = document.createElement("span");
      cite.className = "cite";
      cite.dataset.n = String(n);
      cite.textContent = String(n);
      p.appendChild(cite);
      cursor = citationPattern.lastIndex;
    }
    p.appendChild(document.createTextNode(paragraph.slice(cursor)));
    body.appendChild(p);
  }
}

function buildSources(sources) {
  const sourcesEl = document.createElement("div");
  sourcesEl.className = "sources";

  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "sources-toggle";
  toggle.innerHTML = `${CARET_SVG}Sources<span class="count">${sources.length}</span>`;
  sourcesEl.appendChild(toggle);

  const list = document.createElement("div");
  list.className = "sources-list";
  sources.forEach((source, index) => {
    const row = document.createElement("div");
    row.className = "src";
    const n = document.createElement("span");
    n.className = "src-n";
    n.textContent = String(index + 1);
    row.appendChild(n);
    const path = document.createElement("span");
    path.className = "src-path";
    path.textContent = source.document_path;
    row.appendChild(path);
    if (source.section) {
      const section = document.createElement("span");
      section.className = "src-sec";
      section.textContent = source.section;
      row.appendChild(section);
    }
    if (source.project_name) {
      const project = document.createElement("span");
      project.className = "src-proj";
      project.textContent = source.project_name;
      row.appendChild(project);
    }
    list.appendChild(row);
  });
  sourcesEl.appendChild(list);
  return sourcesEl;
}

function addAssistantEntry(text, sources) {
  const { body } = addEntry('<span class="g-label">Assistant</span>', { bodyClass: "turn-a" });
  renderAnswerInto(body, text, sources ? sources.length : 0);
  if (sources && sources.length > 0) body.appendChild(buildSources(sources));
  scrollToBottom();
  return body;
}

// Sources collapse and citation clicks, delegated so replayed and live entries behave alike.
messages.addEventListener("click", (event) => {
  const toggle = event.target.closest(".sources-toggle");
  if (toggle) {
    toggle.closest(".sources").classList.toggle("collapsed");
    return;
  }
  const cite = event.target.closest(".cite");
  if (cite) {
    const sourcesEl = cite.closest(".entry-body")?.querySelector(".sources");
    if (!sourcesEl) return;
    const row = sourcesEl.querySelectorAll(".src")[Number(cite.dataset.n) - 1];
    if (!row) return;
    sourcesEl.classList.remove("collapsed");
    row.classList.add("flash");
    setTimeout(() => row.classList.remove("flash"), 900);
  }
});

// --- Thinking stage: spinner + label + live elapsed counter (no token counts: /chat is a
// single non-streaming request, so there is nothing real to show) ---

function addThinking() {
  const { entry, body } = addEntry('<span class="g-label">Assistant</span>', {
    bodyClass: "turn-a",
  });
  body.innerHTML =
    '<div class="pending"><span class="spinner"></span><span class="pending-label">thinking</span><span class="pending-meta">0s</span></div>';
  const meta = body.querySelector(".pending-meta");
  const started = Date.now();
  const timer = setInterval(() => {
    meta.textContent = `${Math.floor((Date.now() - started) / 1000)}s`;
  }, 250);
  return { entry, body, timer };
}

// --- File chips (staged attachments and attachment results) ---

function buildFileChip(filename, { removable = false } = {}) {
  const chip = document.createElement("span");
  chip.className = "file-chip";
  chip.innerHTML = FILE_ICON_SVG;
  const name = document.createElement("span");
  name.className = "fname";
  name.textContent = filename;
  chip.appendChild(name);
  if (removable) {
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "x";
    remove.title = "Remove attachment";
    remove.textContent = "×";
    chip.appendChild(remove);
  }
  return chip;
}

function renderPendingAttachments() {
  pendingAttachmentsBar.innerHTML = "";
  for (const attachment of pendingAttachments) {
    const chip = buildFileChip(attachment.filename, { removable: true });
    chip.querySelector(".x").addEventListener("click", () => {
      pendingAttachments = pendingAttachments.filter((a) => a !== attachment);
      renderPendingAttachments();
    });
    pendingAttachmentsBar.appendChild(chip);
  }
}

/** Stage dropped/picked paths on the composer: a file stages itself, a folder stages every
 * supported file it contains. Either way, nothing reaches the backend until send. */
async function stagePaths(paths) {
  if (!paths || paths.length === 0) return;
  const filePaths = [];
  for (const path of paths) {
    filePaths.push(...(await window.openproject.listFiles(path)));
  }
  if (filePaths.length === 0) {
    addMessage("No supported files (.md, .mdx, .pdf) found in the selected item(s).", "error");
    return;
  }
  for (const path of filePaths) {
    if (!pendingAttachments.some((a) => a.path === path)) {
      pendingAttachments.push({ path, filename: path.split("/").pop() });
    }
  }
  renderPendingAttachments();
}

// --- Attachment results after send: one Memory entry of file-chip rows ---

function addAttachmentResults(attachments) {
  for (const attachment of attachments) {
    if (attachment.status === "failed") {
      addMessage(`${attachment.filename}: ${attachment.error || "could not attach"}`, "error");
    }
  }

  const successful = attachments.filter((a) => a.status !== "failed");
  if (successful.length === 0) return;

  const { body } = addEntry(gutterTag("Memory"), { bodyClass: "ledger-col" });

  const rows = successful.map((attachment) => {
    const line = document.createElement("div");
    line.className = "ledger-line";
    line.appendChild(buildFileChip(attachment.filename));
    const spacer = document.createElement("span");
    spacer.className = "spacer";
    line.appendChild(spacer);
    const saveBtn = document.createElement("button");
    saveBtn.type = "button";
    saveBtn.className = "act";
    saveBtn.textContent = "save to memory";
    saveBtn.addEventListener("click", () => promoteAttachment(attachment, saveBtn));
    line.appendChild(saveBtn);
    body.appendChild(line);
    return { attachment, buttonEl: saveBtn };
  });

  if (successful.length > 1) {
    const actions = document.createElement("div");
    actions.className = "ledger-actions";
    const bulkBtn = document.createElement("button");
    bulkBtn.type = "button";
    bulkBtn.className = "act";
    bulkBtn.textContent = "save all to memory";
    bulkBtn.addEventListener("click", async () => {
      bulkBtn.disabled = true;
      bulkBtn.textContent = "saving all…";
      for (const row of rows) {
        if (!row.buttonEl.isConnected) continue; // already saved individually
        await promoteAttachment(row.attachment, row.buttonEl);
      }
      actions.remove();
    });
    actions.appendChild(bulkBtn);
    body.appendChild(actions);
  }

  scrollToBottom();
}

async function promoteAttachment(attachment, buttonEl) {
  buttonEl.disabled = true;
  buttonEl.textContent = "saving…";
  try {
    const response = await fetch(
      `${window.openproject.backendUrl}/documents/${attachment.document_id}/promote`,
      { method: "POST" },
    );
    if (!response.ok) {
      const detail = await response.json().catch(() => null);
      throw new Error(detail?.detail || `Backend returned ${response.status}`);
    }
    const result = await response.json();
    const note = document.createElement("span");
    note.className = "saved";
    note.textContent =
      result.project_resolution === "ambiguous" ? "saved, project unclear" : "saved to memory";
    buttonEl.replaceWith(note);
    if (result.project_resolution === "ambiguous") await loadPendingResolutions();
  } catch (error) {
    buttonEl.disabled = false;
    buttonEl.textContent = "save to memory";
    addMessage(`Could not save ${attachment.filename}: ${error.message}`, "error");
  }
}

// --- Paginated fetch helpers ---

const PAGE_SIZE = 100;

async function fetchAllPages(path) {
  const items = [];
  let offset = 0;
  for (;;) {
    const response = await fetch(
      `${window.openproject.backendUrl}${path}?limit=${PAGE_SIZE}&offset=${offset}`,
    );
    if (!response.ok) throw new Error(`Backend returned ${response.status}`);
    const body = await response.json();
    items.push(...body.items);
    offset += body.items.length;
    if (body.items.length === 0 || offset >= body.total) return items;
  }
}

async function fetchProjects() {
  try {
    return await fetchAllPages("/projects");
  } catch {
    return [];
  }
}

// --- Sessions: sidebar list, topbar title, and the Ctrl/Cmd+K palette share `conversations` ---

function setTopbarTitle(title) {
  topbarName.textContent = (title || "new session").toLowerCase();
}

function formatSessionDate(isoString) {
  if (!isoString) return "";
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) return "";
  const startOfDay = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const dayDiff = Math.round((startOfDay(new Date()) - startOfDay(date)) / 86400000);
  if (dayDiff <= 0) return "today";
  if (dayDiff === 1) return "yesterday";
  return date.toLocaleDateString("en-US", { month: "short", day: "2-digit" }).toLowerCase();
}

function renderHistoryList() {
  sidebarHistory.innerHTML = "";
  if (conversations.length === 0) {
    sidebarHistory.innerHTML = '<p class="sidebar-empty">no sessions yet</p>';
    return;
  }
  for (const conversation of conversations) {
    const item = document.createElement("button");
    item.type = "button";
    item.className = conversation.id === conversationId ? "sess sel" : "sess";
    item.dataset.conversationId = conversation.id;
    item.innerHTML = `
      <span class="sess-top">
        <span class="sess-title"></span>
        <span class="sess-date"></span>
      </span>
      <span class="sess-preview"></span>`;
    item.querySelector(".sess-title").textContent = conversation.title || "New conversation";
    item.querySelector(".sess-date").textContent = formatSessionDate(conversation.updated_at);
    item.querySelector(".sess-preview").textContent = conversation.preview || "";
    item.addEventListener("click", () => openConversation(conversation.id));
    sidebarHistory.appendChild(item);
  }
}

function setActiveHistoryItem() {
  for (const item of sidebarHistory.querySelectorAll(".sess")) {
    item.classList.toggle("sel", item.dataset.conversationId === conversationId);
  }
}

async function loadConversationHistory() {
  try {
    conversations = await fetchAllPages("/conversations");
    renderHistoryList();
  } catch (error) {
    addMessage(`Could not load conversation history: ${error.message}`, "error");
  }
}

async function openConversation(id) {
  try {
    const response = await fetch(`${window.openproject.backendUrl}/conversations/${id}`);
    if (!response.ok) throw new Error(`Backend returned ${response.status}`);
    const data = await response.json();

    messages.innerHTML = "";
    conversationId = data.id;
    pendingAttachments = [];
    renderPendingAttachments();

    if (data.attachments.length > 0) {
      const names = data.attachments.map((a) => a.path.split(/[\\/]/).pop()).join(", ");
      addMessage(`Attached: ${names}`, "system");
    }
    for (const message of data.messages) {
      if (message.role === "assistant") {
        addAssistantEntry(message.content, message.sources);
      } else {
        addMessage(message.content, message.role);
      }
    }
    setActiveHistoryItem();
    setTopbarTitle(data.title);
    input.focus();
  } catch (error) {
    addMessage(`Could not load conversation: ${error.message}`, "error");
  }
}

function prependHistoryItem(conversation) {
  conversations.unshift(conversation);
  renderHistoryList();
}

function resetConversationView() {
  messages.innerHTML = "";
  conversationId = null;
  pendingAttachments = [];
  renderPendingAttachments();
  setActiveHistoryItem();
  setTopbarTitle(null);
}

newChatBtn.addEventListener("click", () => {
  resetConversationView();
  input.focus();
});

// --- Ambiguous project resolutions: a Resolve entry holding an amber decision card ---

async function loadPendingResolutions() {
  try {
    const resolutions = await fetchAllPages("/project-resolutions");
    if (resolutions.length === 0) return;
    const projects = await fetchProjects();
    for (const resolution of resolutions) {
      addResolutionCard(resolution, projects);
    }
  } catch (error) {
    addMessage(`Could not load pending project resolutions: ${error.message}`, "error");
  }
}

function addResolutionCard(resolution, projects) {
  let selectedProjectId = projects.length > 0 ? projects[0].id : null;
  let isNewProject = projects.length === 0;
  const optionEls = [];
  let newOptionEl = null;

  const { entry, body } = addEntry(gutterTag("Resolve"));
  entry.dataset.resolutionType = "project-resolution";

  const card = document.createElement("section");
  card.className = "decision";

  const filename = resolution.document_path.split("/").pop();
  const title = document.createElement("span");
  title.className = "decision-title";
  const code = document.createElement("code");
  code.textContent = filename;
  title.append("Which project does ");
  title.appendChild(code);
  title.append(" belong to?");
  card.appendChild(title);

  const subtitle = document.createElement("p");
  subtitle.className = "decision-sub";
  subtitle.textContent = resolution.candidate_description
    ? `Candidate "${resolution.candidate_name}" (${resolution.candidate_description}). The document matches more than one known project.`
    : "The document matches more than one known project. Choose where to attach it.";
  card.appendChild(subtitle);

  function updateSelection(projectId, newMode) {
    selectedProjectId = projectId;
    isNewProject = newMode;
    for (const { el, project } of optionEls) {
      el.classList.toggle("sel", !newMode && project.id === projectId);
    }
    if (newOptionEl) newOptionEl.classList.toggle("sel", newMode);
  }

  if (projects.length > 0) {
    const group = document.createElement("div");
    group.className = "opt-group";
    const label = document.createElement("div");
    label.className = "opt-label";
    label.textContent = "Attach to existing";
    group.appendChild(label);

    for (const project of projects) {
      const option = document.createElement("div");
      option.className = project.id === selectedProjectId ? "opt sel" : "opt";
      const radio = document.createElement("span");
      radio.className = "opt-radio";
      option.appendChild(radio);
      const name = document.createElement("span");
      name.className = "opt-name";
      name.textContent = project.name;
      option.appendChild(name);
      option.addEventListener("click", () => updateSelection(project.id, false));
      optionEls.push({ el: option, project });
      group.appendChild(option);
    }
    card.appendChild(group);
  }

  const newGroup = document.createElement("div");
  newGroup.className = "opt-group";
  const newLabel = document.createElement("div");
  newLabel.className = "opt-label";
  newLabel.textContent = "Or create new";
  newGroup.appendChild(newLabel);

  newOptionEl = document.createElement("div");
  newOptionEl.className = isNewProject ? "opt sel" : "opt";
  const newRadio = document.createElement("span");
  newRadio.className = "opt-radio";
  newOptionEl.appendChild(newRadio);
  const newInput = document.createElement("input");
  newInput.type = "text";
  newInput.value = resolution.candidate_name;
  newOptionEl.appendChild(newInput);
  newInput.addEventListener("focus", () => updateSelection(null, true));
  newOptionEl.addEventListener("click", (event) => {
    if (event.target !== newInput) newInput.focus();
  });
  newGroup.appendChild(newOptionEl);
  card.appendChild(newGroup);

  const footer = document.createElement("div");
  footer.className = "decision-foot";

  const dismissBtn = document.createElement("button");
  dismissBtn.type = "button";
  dismissBtn.className = "btn btn-ghost";
  dismissBtn.textContent = "dismiss";
  dismissBtn.addEventListener("click", () => entry.remove());
  footer.appendChild(dismissBtn);

  const attachBtn = document.createElement("button");
  attachBtn.type = "button";
  attachBtn.className = "btn btn-primary";
  attachBtn.textContent = "attach";
  attachBtn.addEventListener("click", () => {
    const projectName = isNewProject
      ? newInput.value.trim() || resolution.candidate_name
      : projects.find((p) => p.id === selectedProjectId)?.name;
    resolveProjectResolution(resolution, isNewProject ? null : selectedProjectId, entry, projectName);
  });
  footer.appendChild(attachBtn);

  card.appendChild(footer);
  body.appendChild(card);
  scrollToBottom();
}

async function resolveProjectResolution(resolution, projectId, entryEl, projectName) {
  const buttons = entryEl.querySelectorAll("button");
  for (const button of buttons) button.disabled = true;

  try {
    const response = await fetch(
      `${window.openproject.backendUrl}/project-resolutions/${resolution.id}/resolve`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_id: projectId }),
      },
    );

    if (!response.ok) {
      const detail = await response.json().catch(() => null);
      throw new Error(detail?.detail || `Backend returned ${response.status}`);
    }

    const filename = resolution.document_path.split("/").pop();
    entryEl.replaceWith(
      buildSystemEntry(`${filename} attached to project "${projectName}"`).entry,
    );

    for (const remaining of document.querySelectorAll('[data-resolution-type="project-resolution"]')) {
      remaining.remove();
    }
    await loadPendingResolutions();
  } catch (error) {
    addMessage(
      `Could not resolve project for ${resolution.document_path}: ${error.message}`,
      "error",
    );
    for (const button of buttons) button.disabled = false;
  }
}

// --- Pending facts: a Fact entry with a "Remember this?" decision card ---

async function loadPendingFacts() {
  try {
    const facts = await fetchAllPages("/facts/pending");
    for (const fact of facts) addFactCard(fact);
  } catch (error) {
    addMessage(`Could not load pending facts: ${error.message}`, "error");
  }
}

function addFactCard(fact) {
  const { entry, body } = addEntry(gutterTag("Fact"));

  const card = document.createElement("section");
  card.className = "decision";

  const title = document.createElement("span");
  title.className = "decision-title";
  title.textContent = "Remember this?";
  card.appendChild(title);

  const line = document.createElement("div");
  line.className = "fact-line";
  const subject = document.createElement("span");
  subject.className = "fname";
  subject.textContent = fact.subject;
  line.appendChild(subject);
  const note = document.createElement("span");
  note.className = "lnote";
  note.textContent = `${fact.predicate}: ${fact.object}`;
  line.appendChild(note);
  card.appendChild(line);

  const footer = document.createElement("div");
  footer.className = "decision-foot";

  const discardBtn = document.createElement("button");
  discardBtn.type = "button";
  discardBtn.className = "btn btn-ghost";
  discardBtn.textContent = "discard";
  discardBtn.addEventListener("click", () => resolveFactCard(fact, false, entry));
  footer.appendChild(discardBtn);

  const rememberBtn = document.createElement("button");
  rememberBtn.type = "button";
  rememberBtn.className = "btn btn-primary";
  rememberBtn.textContent = "remember";
  rememberBtn.addEventListener("click", () => resolveFactCard(fact, true, entry));
  footer.appendChild(rememberBtn);

  card.appendChild(footer);
  body.appendChild(card);
  scrollToBottom();
}

async function resolveFactCard(fact, confirm, entryEl) {
  const buttons = entryEl.querySelectorAll("button");
  for (const button of buttons) button.disabled = true;

  try {
    const response = await fetch(`${window.openproject.backendUrl}/facts/${fact.id}/resolve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm }),
    });

    if (!response.ok) {
      const detail = await response.json().catch(() => null);
      throw new Error(detail?.detail || `Backend returned ${response.status}`);
    }

    entryEl.replaceWith(buildSystemEntry(confirm ? "fact recorded" : "fact discarded").entry);
  } catch (error) {
    addMessage(`Could not resolve fact: ${error.message}`, "error");
    for (const button of buttons) button.disabled = false;
  }
}

// --- Overlays: shared toggling, backdrop clicks, Escape ---

function toggleOverlay(overlay, show) {
  overlay.classList.toggle("hidden", !show);
}

const settingsModal = document.getElementById("settings-modal");

historyOverlay.addEventListener("click", (event) => {
  if (event.target === historyOverlay) toggleOverlay(historyOverlay, false);
});
settingsModal.addEventListener("click", (event) => {
  if (event.target === settingsModal) toggleOverlay(settingsModal, false);
});
clearDatabaseModal.addEventListener("click", (event) => {
  if (event.target === clearDatabaseModal && !clearDatabaseInFlight) hideClearDatabaseModal();
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    toggleOverlay(historyOverlay, false);
    toggleOverlay(settingsModal, false);
    if (!clearDatabaseInFlight) hideClearDatabaseModal();
  }
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    const show = historyOverlay.classList.contains("hidden");
    toggleOverlay(historyOverlay, show);
    if (show) {
      historySearch.value = "";
      renderPalette("");
      historySearch.focus();
    }
  }
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "b") {
    event.preventDefault();
    document.body.classList.toggle("sidebar-hidden");
  }
});

toggleSidebarBtn.addEventListener("click", () => {
  document.body.classList.toggle("sidebar-hidden");
});

// --- History search palette: client-side filter over the loaded conversation list ---

let paletteIndex = 0;

function paletteItems() {
  return [...historyList.querySelectorAll(".palette-item")];
}

function setPaletteIndex(index) {
  const items = paletteItems();
  if (items.length === 0) return;
  paletteIndex = Math.max(0, Math.min(index, items.length - 1));
  items.forEach((item, i) => item.classList.toggle("active", i === paletteIndex));
  items[paletteIndex].scrollIntoView({ block: "nearest" });
}

function renderPalette(filter) {
  historyList.innerHTML = "";
  const query = filter.trim().toLowerCase();
  const found = conversations.filter(
    (c) =>
      (c.title || "").toLowerCase().includes(query) ||
      (c.preview || "").toLowerCase().includes(query),
  );
  if (found.length === 0) {
    historyList.innerHTML = '<div class="palette-empty">no conversations match</div>';
    return;
  }
  for (const conversation of found) {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "palette-item";
    item.innerHTML = `
      <div class="palette-item-top">
        <span class="palette-item-title"></span>
        <span class="palette-item-date"></span>
      </div>
      <span class="palette-item-preview"></span>`;
    item.querySelector(".palette-item-title").textContent =
      conversation.title || "New conversation";
    item.querySelector(".palette-item-date").textContent = formatSessionDate(
      conversation.updated_at,
    );
    item.querySelector(".palette-item-preview").textContent = conversation.preview || "";
    item.addEventListener("click", () => {
      toggleOverlay(historyOverlay, false);
      openConversation(conversation.id);
    });
    historyList.appendChild(item);
  }
  setPaletteIndex(0);
}

historySearch.addEventListener("input", () => renderPalette(historySearch.value));
historySearch.addEventListener("keydown", (event) => {
  if (event.key === "ArrowDown") {
    event.preventDefault();
    setPaletteIndex(paletteIndex + 1);
  } else if (event.key === "ArrowUp") {
    event.preventDefault();
    setPaletteIndex(paletteIndex - 1);
  } else if (event.key === "Enter") {
    event.preventDefault();
    paletteItems()[paletteIndex]?.click();
  }
});

// --- Settings modal ---

const settingsBtn = document.getElementById("settings-btn");
const settingsNavButtons = document.querySelectorAll(".snav");
const settingsPanels = document.querySelectorAll("[data-settings-panel]");

function setActiveSettingsSection(section) {
  settingsNavButtons.forEach((btn) => btn.classList.toggle("sel", btn.dataset.section === section));
  settingsPanels.forEach((panel) =>
    panel.classList.toggle("sel", panel.dataset.settingsPanel === section),
  );
}

settingsBtn.addEventListener("click", () => {
  setActiveSettingsSection("models");
  toggleOverlay(settingsModal, true);
});
settingsNavButtons.forEach((btn) => {
  btn.addEventListener("click", () => setActiveSettingsSection(btn.dataset.section));
});

// Model dropdowns: custom-styled combobox (a native <select>'s open list can't be themed).
// Options come from GET /settings/models (models actually pulled in Ollama); each selection
// autosaves via PATCH /settings/models. Cloud providers aren't implemented yet, so there is no
// cloud option group here (see documentation/docs/architecture/model-providers.mdx).
const modelSettingsStatus = document.getElementById("model-settings-status");
const modelSettingsError = document.getElementById("model-settings-error");
let modelSettingsStatusTimer = null;

function modelSettingsField(container) {
  return container.dataset.task ? `${container.dataset.task}_model` : "default_model";
}

function showModelSettingsStatus(text) {
  modelSettingsStatus.textContent = text;
  clearTimeout(modelSettingsStatusTimer);
  if (text) modelSettingsStatusTimer = setTimeout(() => (modelSettingsStatus.textContent = ""), 2000);
}

function showModelSettingsError(message) {
  modelSettingsError.textContent = message;
  modelSettingsError.classList.remove("hidden");
}

function clearModelSettingsError() {
  modelSettingsError.classList.add("hidden");
}

function modelDropdownOptionHtml(value, label) {
  return `<button type="button" data-value="${value}" class="model-dropdown-option">
    <span>${label}</span>
    <span class="model-dropdown-check">✓</span>
  </button>`;
}

function setModelDropdownValue(container, value) {
  container.dataset.value = value;
  container.querySelector(".model-dropdown-value").textContent = value === "" ? "use default" : value;
  container.querySelectorAll(".model-dropdown-option").forEach((option) => {
    option.classList.toggle("sel", option.dataset.value === value);
  });
}

function closeAllModelDropdowns() {
  document.querySelectorAll(".model-dropdown-menu").forEach((menu) => menu.classList.add("hidden"));
}

async function patchModelSettings(field, value) {
  const response = await fetch(`${window.openproject.backendUrl}/settings/models`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ [field]: value === "" ? null : value }),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Backend returned ${response.status}`);
  }
  return response.json();
}

function renderEmbeddingsRow(container, embeddingsModel) {
  container.querySelector(".model-dropdown-value").textContent = embeddingsModel;
}

function initEditableModelDropdown(container, availableModels, currentValue) {
  const isOverride = Boolean(container.dataset.task);
  const field = modelSettingsField(container);
  const menu = container.querySelector(".model-dropdown-menu");
  const trigger = container.querySelector(".model-dropdown-trigger");

  menu.innerHTML =
    (isOverride ? modelDropdownOptionHtml("", "use default") : "") +
    availableModels.map((model) => modelDropdownOptionHtml(model, model)).join("");
  setModelDropdownValue(container, currentValue || "");

  trigger.addEventListener("click", (event) => {
    event.stopPropagation();
    const wasOpen = !menu.classList.contains("hidden");
    closeAllModelDropdowns();
    menu.classList.toggle("hidden", wasOpen);
  });

  menu.addEventListener("click", async (event) => {
    const option = event.target.closest(".model-dropdown-option");
    if (!option) return;
    menu.classList.add("hidden");
    const newValue = option.dataset.value;
    const previousValue = container.dataset.value || "";
    if (newValue === previousValue) return;

    clearModelSettingsError();
    setModelDropdownValue(container, newValue);
    showModelSettingsStatus("saving…");
    try {
      await patchModelSettings(field, newValue);
      showModelSettingsStatus("saved");
    } catch (error) {
      setModelDropdownValue(container, previousValue);
      showModelSettingsStatus("");
      showModelSettingsError(`Could not save model setting: ${error.message}`);
    }
  });
}

async function initModelDropdowns() {
  const containers = Array.from(document.querySelectorAll(".model-dropdown"));
  containers.forEach((container) => container.querySelector(".model-dropdown-value").textContent = "loading…");

  let settings;
  try {
    const response = await fetch(`${window.openproject.backendUrl}/settings/models`);
    if (!response.ok) throw new Error(`Backend returned ${response.status}`);
    settings = await response.json();
  } catch (error) {
    containers.forEach((container) => {
      container.querySelector(".model-dropdown-trigger").disabled = true;
      container.querySelector(".model-dropdown-value").textContent = "unavailable";
    });
    showModelSettingsError(`Could not load model settings: ${error.message}`);
    return;
  }

  containers.forEach((container) => {
    if (container.dataset.task === "embeddings") {
      renderEmbeddingsRow(container, settings.embeddings_model);
      return;
    }
    const field = modelSettingsField(container);
    initEditableModelDropdown(container, settings.available_llm_models, settings[field]);
  });
}
initModelDropdowns();
document.addEventListener("click", closeAllModelDropdowns);

// Statistics panel: GET /stats once at startup (mirrors initModelDropdowns() above), same
// call whether or not the user ever opens the Statistics tab.
const statsError = document.getElementById("stats-error");

function formatStatCount(value) {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return String(value);
}

async function loadStats() {
  let stats;
  try {
    const response = await fetch(`${window.openproject.backendUrl}/stats`);
    if (!response.ok) throw new Error(`Backend returned ${response.status}`);
    stats = await response.json();
  } catch (error) {
    statsError.textContent = `Could not load statistics: ${error.message}`;
    statsError.classList.remove("hidden");
    return;
  }

  const values = { ...stats.corpus, ...stats.usage };
  document.querySelectorAll("[data-stat]").forEach((el) => {
    el.textContent = formatStatCount(values[el.dataset.stat]);
  });
}
loadStats();

// Secret fields (API tokens, bot tokens, signing secrets): show/hide toggle only, no validation.
document.querySelectorAll("[data-toggle-password]").forEach((toggleBtn) => {
  toggleBtn.addEventListener("click", () => {
    const secretInput = toggleBtn.closest(".field-input").querySelector("input");
    const isHidden = secretInput.type === "password";
    secretInput.type = isHidden ? "text" : "password";
    toggleBtn.textContent = isHidden ? "hide" : "show";
  });
});

// --- Clear database ---

function hideClearDatabaseModal() {
  clearDatabaseModal.classList.add("hidden");
  clearDatabaseError.classList.add("hidden");
  clearDatabaseError.textContent = "";
}

clearDatabaseBtn.addEventListener("click", () => {
  clearDatabaseModal.classList.remove("hidden");
});

clearDatabaseCancelBtn.addEventListener("click", () => {
  if (clearDatabaseInFlight) return;
  hideClearDatabaseModal();
});

clearDatabaseConfirmBtn.addEventListener("click", async () => {
  clearDatabaseInFlight = true;
  clearDatabaseConfirmBtn.disabled = true;
  clearDatabaseConfirmBtn.textContent = "clearing…";
  clearDatabaseCancelBtn.disabled = true;
  try {
    const response = await fetch(`${window.openproject.backendUrl}/admin/reset`, { method: "POST" });
    if (!response.ok) throw new Error(`Backend returned ${response.status}`);

    hideClearDatabaseModal();
    toggleOverlay(settingsModal, false);
    resetConversationView();
    conversations = [];
    renderHistoryList();
    addMessage("database cleared, all local state reset", "system");
  } catch (error) {
    clearDatabaseError.textContent = `Could not clear database: ${error.message}`;
    clearDatabaseError.classList.remove("hidden");
  } finally {
    clearDatabaseInFlight = false;
    clearDatabaseConfirmBtn.disabled = false;
    clearDatabaseConfirmBtn.textContent = "clear database";
    clearDatabaseCancelBtn.disabled = false;
  }
});

// --- Attach picker and drag-and-drop staging ---

attachButton.addEventListener("click", async () => {
  const paths = await window.openproject.selectPaths();
  await stagePaths(paths);
});

for (const eventName of ["dragenter", "dragover"]) {
  document.addEventListener(eventName, (event) => {
    event.preventDefault();
    document.body.classList.add("dragover");
  });
}

for (const eventName of ["dragleave", "drop"]) {
  document.addEventListener(eventName, (event) => {
    event.preventDefault();
    document.body.classList.remove("dragover");
  });
}

document.addEventListener("drop", async (event) => {
  const paths = [...event.dataTransfer.files].map((file) =>
    window.openproject.getPathForFile(file),
  );
  await stagePaths(paths);
});

// --- Startup ---

loadPendingResolutions();
loadPendingFacts();
loadConversationHistory();

// --- Send flow ---

input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    if (!sendButton.disabled) composer.requestSubmit();
  }
});

input.addEventListener("input", () => {
  input.style.height = "auto";
  input.style.height = `${input.scrollHeight}px`;
});

composer.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (sendButton.disabled) return;
  const message = input.value.trim();
  if (!message) return;

  const attachmentsToSend = pendingAttachments;
  const wasNewConversation = conversationId === null;
  pendingAttachments = [];
  renderPendingAttachments();

  addMessage(message, "user", { withTime: true });
  input.value = "";
  input.style.height = "auto";
  sendButton.disabled = true;

  const thinking = addThinking();
  try {
    const response = await fetch(`${window.openproject.backendUrl}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        conversation_id: conversationId,
        attachments: attachmentsToSend.map((a) => a.path),
      }),
    });

    if (!response.ok) throw new Error(`Backend returned ${response.status}`);

    const data = await response.json();
    conversationId = data.conversation_id;
    clearInterval(thinking.timer);
    thinking.body.innerHTML = "";
    renderAnswerInto(thinking.body, data.answer, data.sources ? data.sources.length : 0);
    if (data.sources && data.sources.length > 0) thinking.body.appendChild(buildSources(data.sources));
    scrollToBottom();
    if (data.attachments && data.attachments.length > 0) addAttachmentResults(data.attachments);
    if (data.pending_fact) addFactCard(data.pending_fact);
    if (wasNewConversation && data.title) {
      prependHistoryItem({
        id: data.conversation_id,
        title: data.title,
        preview: data.answer,
        updated_at: new Date().toISOString(),
      });
      setTopbarTitle(data.title);
    }
  } catch (error) {
    clearInterval(thinking.timer);
    thinking.entry.remove();
    addMessage(`Could not reach the backend: ${error.message}`, "error");
  } finally {
    sendButton.disabled = false;
    input.focus();
  }
});
