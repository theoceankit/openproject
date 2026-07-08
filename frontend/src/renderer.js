const chat = document.getElementById("chat");
const messages = document.getElementById("messages");
const composer = document.getElementById("composer");
const input = document.getElementById("message");
const sendButton = composer.querySelector('button[type="submit"]');
const attachButton = document.getElementById("attach");
const newChatBtn = document.getElementById("new-chat-btn");
const pendingAttachmentsBar = document.getElementById("pending-attachments");

let conversationId = null;
let pendingAttachments = []; // {path, filename}, staged on the composer, not yet sent

newChatBtn.addEventListener("click", () => {
  messages.innerHTML = "";
  conversationId = null;
  pendingAttachments = [];
  renderPendingAttachments();
  input.focus();
});

function renderPendingAttachments() {
  pendingAttachmentsBar.innerHTML = "";
  pendingAttachmentsBar.classList.toggle("hidden", pendingAttachments.length === 0);
  for (const attachment of pendingAttachments) {
    const chip = document.createElement("div");
    chip.className =
      "flex items-center gap-xs bg-surface-container border border-white/10 rounded-full pl-sm pr-xs py-[3px]";

    const label = document.createElement("span");
    label.className = "font-code-label text-[11px] text-on-surface-variant";
    label.textContent = attachment.filename;

    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.title = "Remove attachment";
    removeBtn.className =
      "material-symbols-outlined text-[13px] text-on-surface-variant/60 hover:text-primary w-4 h-4 flex items-center justify-center rounded-full hover:bg-white/10";
    removeBtn.textContent = "close";
    removeBtn.addEventListener("click", () => {
      pendingAttachments = pendingAttachments.filter((a) => a !== attachment);
      renderPendingAttachments();
    });

    chip.appendChild(label);
    chip.appendChild(removeBtn);
    pendingAttachmentsBar.appendChild(chip);
  }
}

/** Route dropped/picked paths: files are staged on the composer, folders are bulk-ingested immediately. */
async function stagePaths(paths) {
  if (!paths || paths.length === 0) return;
  const folderPaths = [];
  for (const path of paths) {
    const { isDirectory } = await window.openproject.statPath(path);
    if (isDirectory) {
      folderPaths.push(path);
    } else if (!pendingAttachments.some((a) => a.path === path)) {
      pendingAttachments.push({ path, filename: path.split("/").pop() });
    }
  }
  renderPendingAttachments();
  if (folderPaths.length > 0) await ingestPaths(folderPaths);
}

function addMessage(text, role) {
  const wrapper = document.createElement("div");
  let contentEl;

  if (role === "user") {
    wrapper.className = "flex justify-end w-full";
    const card = document.createElement("div");
    card.className = "bg-surface-container-high border border-white/5 rounded-xl p-sm max-w-[80%] shadow-sm";
    const p = document.createElement("p");
    p.className = "font-body-base text-body-base text-primary leading-relaxed whitespace-pre-wrap";
    p.textContent = text;
    card.appendChild(p);
    wrapper.appendChild(card);
    contentEl = card;
  } else if (role === "assistant") {
    wrapper.className = "flex flex-col items-start w-full";
    const card = document.createElement("div");
    card.className = "bg-surface-container border border-white/5 rounded-xl p-sm w-full";
    const p = document.createElement("p");
    p.className = "font-body-base text-body-base text-on-surface leading-relaxed whitespace-pre-wrap";
    p.textContent = text;
    card.appendChild(p);
    wrapper.appendChild(card);
    contentEl = card;
  } else if (role === "error") {
    wrapper.className = "flex flex-col items-start w-full";
    const card = document.createElement("div");
    card.className = "rounded-xl p-md w-full";
    card.style.cssText = "background:rgba(147,0,10,0.15);border:1px solid rgba(255,180,171,0.2)";
    const p = document.createElement("p");
    p.className = "font-body-base text-body-base leading-relaxed";
    p.style.color = "#ffb4ab";
    p.textContent = text;
    card.appendChild(p);
    wrapper.appendChild(card);
    contentEl = card;
  } else {
    // system — icon + label, no card background
    wrapper.className = "flex items-center gap-xs";
    const icon = document.createElement("span");
    icon.className = "material-symbols-outlined text-[13px] text-on-surface-variant/40";
    icon.textContent = "info";
    const label = document.createElement("span");
    label.className = "font-code-label text-[11px] text-on-surface-variant/40";
    label.textContent = text;
    wrapper.appendChild(icon);
    wrapper.appendChild(label);
    contentEl = wrapper;
  }

  messages.appendChild(wrapper);
  chat.scrollTop = chat.scrollHeight;
  return contentEl;
}

function addSpinner(text) {
  const wrapper = document.createElement("div");
  wrapper.className = "flex items-center gap-sm";
  const iconWrap = document.createElement("div");
  iconWrap.className = "w-5 h-5 flex items-center justify-center rounded-full border border-white/10 bg-surface-container-high shrink-0";
  const spinnerEl = document.createElement("div");
  spinnerEl.className = "w-3 h-3 rounded-full border-2 border-white/20 border-t-white/70 animate-spin";
  iconWrap.appendChild(spinnerEl);
  const label = document.createElement("span");
  label.className = "font-code-label text-[11px] text-on-surface-variant/60";
  label.textContent = text;
  wrapper.appendChild(iconWrap);
  wrapper.appendChild(label);
  messages.appendChild(wrapper);
  chat.scrollTop = chat.scrollHeight;
  return wrapper;
}

function addAttachmentBadge(filename, projectNote) {
  const wrapper = document.createElement("div");
  wrapper.className = "flex items-center gap-xs bg-surface-container-high/50 border border-white/10 rounded-full px-sm py-xs w-fit";
  const dot = document.createElement("div");
  dot.className = "w-2 h-2 rounded-full shrink-0";
  dot.style.background = "#8EBC9E";
  const label = document.createElement("span");
  label.className = "font-code-label text-[11px] text-on-surface-variant";
  label.textContent = projectNote ? `${filename} · ${projectNote}` : filename;
  wrapper.appendChild(dot);
  wrapper.appendChild(label);
  messages.appendChild(wrapper);
  chat.scrollTop = chat.scrollHeight;
}

function addAttachmentResults(attachments) {
  for (const attachment of attachments) {
    if (attachment.status === "failed") {
      addMessage(`${attachment.filename}: ${attachment.error || "could not attach"}`, "error");
    } else {
      addAttachmentResultBadge(attachment);
    }
  }
}

function addAttachmentResultBadge(attachment) {
  const wrapper = document.createElement("div");
  wrapper.className =
    "flex items-center gap-sm bg-surface-container-high/50 border border-white/10 rounded-full pl-sm pr-xs py-xs w-fit";

  const dot = document.createElement("div");
  dot.className = "w-2 h-2 rounded-full shrink-0";
  dot.style.background = "#7C9FDB";

  const label = document.createElement("span");
  label.className = "font-code-label text-[11px] text-on-surface-variant";
  label.textContent = `${attachment.filename} · attached to this conversation, not saved`;

  const saveBtn = document.createElement("button");
  saveBtn.type = "button";
  saveBtn.textContent = "Save to memory";
  saveBtn.className =
    "font-ui-label text-[11px] text-primary hover:opacity-80 transition-opacity px-sm py-[2px] rounded-full border border-white/10 shrink-0";
  saveBtn.addEventListener("click", () => promoteAttachment(attachment, saveBtn, label));

  wrapper.appendChild(dot);
  wrapper.appendChild(label);
  wrapper.appendChild(saveBtn);
  messages.appendChild(wrapper);
  chat.scrollTop = chat.scrollHeight;
}

async function promoteAttachment(attachment, buttonEl, labelEl) {
  buttonEl.disabled = true;
  buttonEl.textContent = "Saving…";
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
    buttonEl.remove();
    const note = result.project_resolution === "ambiguous" ? "saved, project unclear" : "saved to memory";
    labelEl.textContent = `${attachment.filename} · ${note}`;
    if (result.project_resolution === "ambiguous") await loadPendingResolutions();
  } catch (error) {
    buttonEl.disabled = false;
    buttonEl.textContent = "Save to memory";
    addMessage(`Could not save ${attachment.filename}: ${error.message}`, "error");
  }
}

function addSources(container, sources) {
  if (!sources || sources.length === 0) return;
  const sourcesEl = document.createElement("div");
  sourcesEl.className = "flex flex-wrap items-center gap-xs mt-sm pt-sm border-t border-white/5";
  const label = document.createElement("span");
  label.className = "font-code-label text-[10px] text-on-surface-variant/30 uppercase tracking-wider";
  label.textContent = "Sources";
  sourcesEl.appendChild(label);
  for (const source of sources) {
    const badge = document.createElement("span");
    badge.className = "font-code-label text-[10px] text-on-surface-variant/50 bg-white/[0.04] border border-white/[0.06] px-xs py-[2px] rounded";
    const loc = source.section
      ? `${source.document_path} (${source.section})`
      : source.document_path;
    badge.textContent = source.project_name ? `[${source.project_name}] ${loc}` : loc;
    sourcesEl.appendChild(badge);
  }
  container.appendChild(sourcesEl);
}

function describeIngestResult(result) {
  if (result.status === "failed") {
    return `${result.path}: failed (${result.error})`;
  }
  if (result.status === "unchanged") {
    return `${result.path}: unchanged`;
  }
  const chunkLabel = `${result.chunks} chunk${result.chunks === 1 ? "" : "s"}`;
  let projectNote = "";
  if (result.project_resolution === "match") projectNote = ", linked to existing project";
  else if (result.project_resolution === "new") projectNote = ", new project created";
  else if (result.project_resolution === "ambiguous") projectNote = ", project unclear (needs confirmation)";
  else if (result.error) projectNote = `, extraction failed (${result.error})`;
  return `${result.path}: ${result.status} (${chunkLabel}${projectNote})`;
}

async function ingestPath(path) {
  const filename = path.split("/").pop();
  const spinner = addSpinner(`indexing ${filename}…`);
  try {
    const response = await fetch(`${window.openproject.backendUrl}/documents/ingest`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    });

    if (!response.ok) {
      const detail = await response.json().catch(() => null);
      throw new Error(detail?.detail || `Backend returned ${response.status}`);
    }

    const results = await response.json();
    spinner.remove();
    for (const result of results) {
      if (result.status === "failed" || result.error) {
        addMessage(describeIngestResult(result), "error");
      } else if (result.status === "unchanged") {
        addMessage(`${filename}: unchanged`, "system");
      } else {
        let projectNote = "";
        if (result.project_resolution === "match") projectNote = "linked to project";
        else if (result.project_resolution === "new") projectNote = "new project created";
        else if (result.project_resolution === "ambiguous") projectNote = "project unclear";
        addAttachmentBadge(filename, projectNote);
      }
    }
  } catch (error) {
    spinner.remove();
    addMessage(`Could not ingest ${path}: ${error.message}`, "error");
  }
}

async function ingestPaths(paths) {
  if (!paths || paths.length === 0) return;
  attachButton.disabled = true;
  try {
    for (const path of paths) {
      await ingestPath(path);
    }
  } finally {
    attachButton.disabled = false;
  }
  await loadPendingResolutions();
}

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
  // Selection state
  let selectedProjectId = projects.length > 0 ? projects[0].id : null;
  let isNewProject = projects.length === 0;
  const optionEls = [];

  // Assigned during DOM building, referenced in updateSelection closure
  let newProjectRow, newProjectInput, newRadio;

  function updateSelection(pid, newMode) {
    selectedProjectId = pid;
    isNewProject = newMode;

    for (const { el, radio, name, project } of optionEls) {
      const sel = !newMode && project.id === pid;
      el.className = `flex items-center justify-between p-sm border rounded-lg cursor-pointer transition-colors ${sel ? "border-white/20 bg-white/5" : "border-white/5 hover:bg-white/5"}`;
      radio.className = `w-4 h-4 rounded-full border-2 flex items-center justify-center ${sel ? "border-primary" : "border-white/20"}`;
      radio.innerHTML = sel ? '<div class="w-2 h-2 rounded-full bg-primary"></div>' : "";
      name.className = `font-body-base text-body-base transition-colors ${sel ? "text-primary" : "text-on-surface-variant"}`;
    }

    if (newProjectRow) {
      newProjectRow.className = `flex items-center p-sm border rounded-lg transition-colors cursor-text ${newMode ? "border-white/20 bg-white/5" : "border-white/5 hover:border-white/10"}`;
      newRadio.className = `w-4 h-4 rounded-full border-2 flex items-center justify-center shrink-0 mr-sm ${newMode ? "border-primary" : "border-white/20"}`;
      newRadio.innerHTML = newMode ? '<div class="w-2 h-2 rounded-full bg-primary"></div>' : "";
    }
  }

  // Outer wrapper
  const wrapper = document.createElement("div");
  wrapper.className = "flex flex-col gap-xs w-full mt-sm";
  wrapper.dataset.resolutionType = "project-resolution";

  // Amber indicator row
  const indicator = document.createElement("div");
  indicator.className = "flex items-center gap-xs px-sm";
  const indDot = document.createElement("div");
  indDot.className = "w-2 h-2 rounded-full shrink-0";
  indDot.style.background = "#E5B567";
  const indLabel = document.createElement("span");
  indLabel.className = "font-code-label text-[10px] uppercase tracking-wider";
  indLabel.style.color = "#E5B567";
  indLabel.textContent = "Your decision needed";
  indicator.appendChild(indDot);
  indicator.appendChild(indLabel);
  wrapper.appendChild(indicator);

  // Card
  const card = document.createElement("div");
  card.className = "bg-surface border border-white/10 rounded-xl p-lg w-full shadow-[0_8px_32px_rgba(0,0,0,0.4)]";

  // Title
  const filename = resolution.document_path.split("/").pop();
  const title = document.createElement("h4");
  title.className = "font-body-base text-[15px] text-primary mb-xs";
  const filenameSpan = document.createElement("span");
  filenameSpan.className = "font-code-label bg-white/5 px-1 rounded text-[13px]";
  filenameSpan.textContent = filename;
  title.append("Which project does ");
  title.appendChild(filenameSpan);
  title.append(" belong to?");
  card.appendChild(title);

  // Subtitle
  const subtitle = document.createElement("p");
  subtitle.className = "font-body-sm text-body-sm text-on-surface-variant mb-lg";
  subtitle.textContent = resolution.candidate_description
    ? `Candidate: "${resolution.candidate_name}" — ${resolution.candidate_description}`
    : "The file matches several projects. Choose where to attach it.";
  card.appendChild(subtitle);

  // Existing projects
  if (projects.length > 0) {
    const existingSection = document.createElement("div");
    existingSection.className = "flex flex-col gap-xs mb-lg";

    const sectionLabel = document.createElement("p");
    sectionLabel.className = "font-code-label text-on-surface-variant/50 text-[10px] uppercase mb-xs";
    sectionLabel.textContent = "Add to existing";
    existingSection.appendChild(sectionLabel);

    for (const project of projects) {
      const sel = project.id === selectedProjectId;
      const option = document.createElement("div");
      option.className = `flex items-center justify-between p-sm border rounded-lg cursor-pointer transition-colors ${sel ? "border-white/20 bg-white/5" : "border-white/5 hover:bg-white/5"}`;

      const left = document.createElement("div");
      left.className = "flex items-center gap-sm";

      const radio = document.createElement("div");
      radio.className = `w-4 h-4 rounded-full border-2 flex items-center justify-center ${sel ? "border-primary" : "border-white/20"}`;
      if (sel) radio.innerHTML = '<div class="w-2 h-2 rounded-full bg-primary"></div>';

      const name = document.createElement("span");
      name.className = `font-body-base text-body-base transition-colors ${sel ? "text-primary" : "text-on-surface-variant"}`;
      name.textContent = project.name;

      left.appendChild(radio);
      left.appendChild(name);
      option.appendChild(left);

      optionEls.push({ el: option, radio, name, project });
      option.addEventListener("click", () => updateSelection(project.id, false));
      existingSection.appendChild(option);
    }

    card.appendChild(existingSection);
  }

  // New project
  const newSection = document.createElement("div");
  newSection.className = "flex flex-col gap-xs mb-lg";

  const newSectionLabel = document.createElement("p");
  newSectionLabel.className = "font-code-label text-on-surface-variant/50 text-[10px] uppercase mb-xs";
  newSectionLabel.textContent = "Create new project";
  newSection.appendChild(newSectionLabel);

  newProjectRow = document.createElement("div");
  newProjectRow.className = `flex items-center p-sm border rounded-lg transition-colors cursor-text ${isNewProject ? "border-white/20 bg-white/5" : "border-white/5 hover:border-white/10"}`;

  newRadio = document.createElement("div");
  newRadio.className = `w-4 h-4 rounded-full border-2 flex items-center justify-center shrink-0 mr-sm ${isNewProject ? "border-primary" : "border-white/20"}`;
  if (isNewProject) newRadio.innerHTML = '<div class="w-2 h-2 rounded-full bg-primary"></div>';

  newProjectInput = document.createElement("input");
  newProjectInput.type = "text";
  newProjectInput.value = resolution.candidate_name;
  newProjectInput.className = "bg-transparent border-none outline-none text-body-base font-body-base text-primary w-full focus:ring-0 p-0";

  newProjectInput.addEventListener("focus", () => updateSelection(null, true));
  newProjectRow.addEventListener("click", (e) => {
    if (e.target !== newProjectInput) newProjectInput.focus();
  });

  newProjectRow.appendChild(newRadio);
  newProjectRow.appendChild(newProjectInput);
  newSection.appendChild(newProjectRow);
  card.appendChild(newSection);

  // Footer
  const footer = document.createElement("div");
  footer.className = "flex justify-end gap-sm pt-sm border-t border-white/5";

  const cancelBtn = document.createElement("button");
  cancelBtn.type = "button";
  cancelBtn.textContent = "Cancel";
  cancelBtn.className = "px-md py-[6px] rounded font-ui-label text-ui-label text-on-surface-variant hover:text-primary hover:bg-white/5 transition-colors border border-transparent";
  cancelBtn.addEventListener("click", () => wrapper.remove());

  const attachBtn = document.createElement("button");
  attachBtn.type = "button";
  attachBtn.textContent = "Attach";
  attachBtn.className = "px-md py-[6px] rounded font-ui-label text-ui-label text-on-primary bg-primary hover:opacity-90 transition-opacity";
  attachBtn.addEventListener("click", () => {
    resolveProjectResolution(resolution, isNewProject ? null : selectedProjectId, wrapper);
  });

  footer.appendChild(cancelBtn);
  footer.appendChild(attachBtn);
  card.appendChild(footer);
  wrapper.appendChild(card);
  messages.appendChild(wrapper);
  chat.scrollTop = chat.scrollHeight;
}

async function resolveProjectResolution(resolution, projectId, cardEl) {
  const buttons = cardEl.querySelectorAll("button");
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

    cardEl.remove();
    addMessage(`${resolution.document_path}: project resolved`, "system");

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

async function loadPendingFacts() {
  try {
    const facts = await fetchAllPages("/facts/pending");
    for (const fact of facts) addFactCard(fact);
  } catch (error) {
    addMessage(`Could not load pending facts: ${error.message}`, "error");
  }
}

function addFactCard(fact) {
  const wrapper = document.createElement("div");
  wrapper.className = "flex flex-col gap-xs w-full mt-sm";

  // Blue indicator row
  const indicator = document.createElement("div");
  indicator.className = "flex items-center gap-xs px-sm";
  const indDot = document.createElement("div");
  indDot.className = "w-2 h-2 rounded-full shrink-0";
  indDot.style.background = "#7C9FDB";
  const indLabel = document.createElement("span");
  indLabel.className = "font-code-label text-[10px] uppercase tracking-wider";
  indLabel.style.color = "#7C9FDB";
  indLabel.textContent = "Confirm fact";
  indicator.appendChild(indDot);
  indicator.appendChild(indLabel);
  wrapper.appendChild(indicator);

  // Card
  const card = document.createElement("div");
  card.className = "bg-surface border border-white/10 rounded-xl p-lg w-full shadow-[0_8px_32px_rgba(0,0,0,0.4)]";

  const title = document.createElement("h4");
  title.className = "font-body-base text-[15px] text-primary mb-sm";
  title.textContent = "Remember this?";
  card.appendChild(title);

  const factText = document.createElement("p");
  factText.className = "font-code-label text-[13px] text-on-surface bg-surface-container-high/50 border border-white/5 rounded-lg px-sm py-xs mb-lg";
  factText.textContent = `${fact.subject} ${fact.predicate}: ${fact.object}`;
  card.appendChild(factText);

  const footer = document.createElement("div");
  footer.className = "flex justify-end gap-sm pt-sm border-t border-white/5";

  const noBtn = document.createElement("button");
  noBtn.type = "button";
  noBtn.textContent = "Discard";
  noBtn.className = "px-md py-[6px] rounded font-ui-label text-ui-label text-on-surface-variant hover:text-primary hover:bg-white/5 transition-colors border border-transparent";
  noBtn.addEventListener("click", () => resolveFactCard(fact, false, wrapper));

  const yesBtn = document.createElement("button");
  yesBtn.type = "button";
  yesBtn.textContent = "Remember";
  yesBtn.className = "px-md py-[6px] rounded font-ui-label text-ui-label text-on-primary bg-primary hover:opacity-90 transition-opacity";
  yesBtn.addEventListener("click", () => resolveFactCard(fact, true, wrapper));

  footer.appendChild(noBtn);
  footer.appendChild(yesBtn);
  card.appendChild(footer);
  wrapper.appendChild(card);
  messages.appendChild(wrapper);
  chat.scrollTop = chat.scrollHeight;
}

async function resolveFactCard(fact, confirm, cardEl) {
  const buttons = cardEl.querySelectorAll("button");
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

    cardEl.remove();
    addMessage(confirm ? "Recorded." : "Discarded.", "system");
  } catch (error) {
    addMessage(`Could not resolve fact: ${error.message}`, "error");
    for (const button of buttons) button.disabled = false;
  }
}

attachButton.addEventListener("click", async () => {
  const paths = await window.openproject.selectPaths();
  await stagePaths(paths);
});

for (const eventName of ["dragenter", "dragover"]) {
  document.addEventListener(eventName, (event) => {
    event.preventDefault();
    chat.classList.add("dragover");
  });
}

for (const eventName of ["dragleave", "drop"]) {
  document.addEventListener(eventName, (event) => {
    event.preventDefault();
    chat.classList.remove("dragover");
  });
}

document.addEventListener("drop", async (event) => {
  const paths = [...event.dataTransfer.files].map((file) =>
    window.openproject.getPathForFile(file),
  );
  await stagePaths(paths);
});

loadPendingResolutions();
loadPendingFacts();

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
  pendingAttachments = [];
  renderPendingAttachments();

  addMessage(message, "user");
  input.value = "";
  input.style.height = "auto";
  sendButton.disabled = true;

  const spinner = addSpinner("thinking…");
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
    spinner.remove();
    if (data.attachments && data.attachments.length > 0) addAttachmentResults(data.attachments);
    const answerEl = addMessage(data.answer, "assistant");
    addSources(answerEl, data.sources);
    if (data.pending_fact) addFactCard(data.pending_fact);
  } catch (error) {
    spinner.remove();
    addMessage(`Could not reach the backend: ${error.message}`, "error");
  } finally {
    sendButton.disabled = false;
    input.focus();
  }
});
