const PAGE_SIZE_KEY = "jsonLabeler.pageSize";
const IMAGES_PER_ROW_KEY = "jsonLabeler.imagesPerRow";
const SESSION_KEY = "jsonLabeler.sessionId";

function createSessionId() {
  if (window.crypto?.randomUUID) {
    return window.crypto.randomUUID();
  }
  return `session-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function storedSessionId() {
  let sessionId = sessionStorage.getItem(SESSION_KEY);
  if (!sessionId) {
    sessionId = createSessionId();
    sessionStorage.setItem(SESSION_KEY, sessionId);
  }
  return sessionId;
}

function storedPageSize() {
  const value = Number(localStorage.getItem(PAGE_SIZE_KEY)) || 20;
  return Math.min(Math.max(1, Math.floor(value)), 200);
}

function storedImagesPerRow() {
  const value = Number(localStorage.getItem(IMAGES_PER_ROW_KEY)) || 4;
  return Math.min(Math.max(1, Math.floor(value)), 8);
}

const state = {
  sessionId: storedSessionId(),
  groups: [],
  labels: {},
  groupProgress: {},
  stats: {
    groups_total: 0,
    groups_reviewed: 0,
    groups_unreviewed: 0,
    targets_total: 0,
    pass: 0,
    fail: 0,
    unlabeled_as_fail: 0,
  },
  currentPage: 1,
  totalPages: 1,
  pageSize: storedPageSize(),
  imagesPerRow: storedImagesPerRow(),
  selectedKey: "",
  hoverKey: "",
  imageViews: {},
  activePan: null,
  loaded: false,
};

const els = {};
let toastTimer = 0;

function initElements() {
  Object.assign(els, {
    inputJsonPath: document.querySelector("#inputJsonPath"),
    targetDirs: document.querySelector("#targetDirs"),
    loadBtn: document.querySelector("#loadBtn"),
    progressPath: document.querySelector("#progressPath"),
    exportDir: document.querySelector("#exportDir"),
    annotatedFilename: document.querySelector("#annotatedFilename"),
    acceptedFilename: document.querySelector("#acceptedFilename"),
    rejectedFilename: document.querySelector("#rejectedFilename"),
    exportBtn: document.querySelector("#exportBtn"),
    statsText: document.querySelector("#statsText"),
    pageSizeInput: document.querySelector("#pageSizeInput"),
    imagesPerRowInput: document.querySelector("#imagesPerRowInput"),
    prevBtn: document.querySelector("#prevBtn"),
    pageText: document.querySelector("#pageText"),
    nextBtn: document.querySelector("#nextBtn"),
    pageJumpInput: document.querySelector("#pageJumpInput"),
    jumpBtn: document.querySelector("#jumpBtn"),
    content: document.querySelector("#content"),
    toast: document.querySelector("#toast"),
  });

  els.pageSizeInput.value = String(state.pageSize);
  els.imagesPerRowInput.value = String(state.imagesPerRow);
}

async function postJson(url, payload) {
  const body = {
    ...(payload || {}),
    session_id: state.sessionId,
  };
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.success === false) {
    throw new Error(data.error || `Request failed: ${response.status}`);
  }
  return data;
}

function showToast(message) {
  window.clearTimeout(toastTimer);
  els.toast.textContent = message;
  els.toast.classList.add("visible");
  toastTimer = window.setTimeout(() => {
    els.toast.classList.remove("visible");
  }, 2400);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function targetDirsFromInput() {
  return els.targetDirs.value
    .split(/[\n,;]+/)
    .map((value) => value.trim())
    .filter(Boolean);
}

async function loadData() {
  const inputJsonPath = els.inputJsonPath.value.trim();
  if (!inputJsonPath) {
    showToast("Enter an input JSON path first.");
    return;
  }

  els.loadBtn.disabled = true;
  els.loadBtn.textContent = "Loading...";
  try {
    const data = await postJson("/api/load", {
      input_json_path: inputJsonPath,
      target_dirs: targetDirsFromInput(),
    });
    state.groups = [];
    state.labels = data.labels && typeof data.labels === "object" ? data.labels : {};
    state.groupProgress = data.group_progress && typeof data.group_progress === "object" ? data.group_progress : {};
    state.stats = data.stats || state.stats;
    state.loaded = true;
    if (data.session_id) {
      state.sessionId = data.session_id;
      sessionStorage.setItem(SESSION_KEY, state.sessionId);
    }
    const firstGroup = data.first_unreviewed_group || null;
    state.currentPage = firstGroup ? pageForIndex(firstGroup.index) : 1;
    state.selectedKey = "";
    state.hoverKey = "";
    els.progressPath.value = data.progress_path || "Not loaded";
    await fetchPage(state.currentPage, state.selectedKey);
    showToast(`Loaded ${state.stats.groups_total || 0} groups.`);
  } catch (error) {
    showToast(error.message || "Load failed.");
  } finally {
    els.loadBtn.disabled = false;
    els.loadBtn.textContent = "Load/Resume";
  }
}

function totalPages() {
  const total = state.stats.groups_total || 0;
  return Math.max(1, state.totalPages || Math.ceil(total / state.pageSize));
}

function clampPage() {
  state.currentPage = Math.min(Math.max(1, state.currentPage), totalPages());
}

function updateStats(stats = state.stats) {
  state.stats = stats || state.stats;
  els.statsText.textContent =
    `Groups ${state.stats.groups_total || 0} | ` +
    `Reviewed ${state.stats.groups_reviewed || 0} | ` +
    `Unreviewed ${state.stats.groups_unreviewed || 0} | ` +
    `Targets ${state.stats.targets_total || 0} | ` +
    `Pass ${state.stats.pass || 0} | ` +
    `Fail ${state.stats.fail || 0} | ` +
    `Unlabeled-as-fail ${state.stats.unlabeled_as_fail || 0}`;
  els.pageText.textContent = `Page ${state.currentPage} / ${totalPages()}`;
  els.pageJumpInput.value = String(state.currentPage);
  els.prevBtn.disabled = state.currentPage <= 1;
  els.nextBtn.disabled = state.currentPage >= totalPages();
}

function currentPageGroups() {
  return state.groups;
}

function firstVisibleTargetKey() {
  for (const group of state.groups) {
    const target = (group.targets || [])[0];
    if (target?.sample_key) return target.sample_key;
  }
  return "";
}

function pageForIndex(index) {
  if (!Number.isFinite(Number(index)) || Number(index) < 0) return state.currentPage;
  return Math.floor(index / state.pageSize) + 1;
}

function mergeLabels(labels) {
  if (!labels || typeof labels !== "object") return;
  Object.entries(labels).forEach(([key, value]) => {
    state.labels[key] = value;
  });
}

function mergeGroupProgress(groupProgress) {
  if (!groupProgress || typeof groupProgress !== "object") return;
  state.groupProgress = { ...state.groupProgress, ...groupProgress };
}

function resetImageViews() {
  state.imageViews = {};
  state.activePan = null;
}

async function fetchPage(page, preferredKey = "") {
  if (!state.loaded) {
    render();
    return;
  }

  els.content.innerHTML = `<section class="empty-state">Loading page...</section>`;
  const data = await postJson("/api/page", {
    page,
    page_size: state.pageSize,
  });
  state.groups = Array.isArray(data.groups) ? data.groups : [];
  mergeLabels(data.labels);
  mergeGroupProgress(data.group_progress);
  state.stats = data.stats || state.stats;
  state.currentPage = data.page || page;
  state.totalPages = data.total_pages || totalPages();
  state.pageSize = data.page_size || state.pageSize;
  els.pageSizeInput.value = String(state.pageSize);
  resetImageViews();

  const hasPreferred = preferredKey && state.groups.some((group) =>
    (group.targets || []).some((target) => target.sample_key === preferredKey)
  );
  state.selectedKey = hasPreferred ? preferredKey : firstVisibleTargetKey();
  state.hoverKey = "";
  render();
}

function imageViewId(sampleKey, role) {
  return `${sampleKey}:${role}`;
}

function comparisonImageViewId(groupKey) {
  return `${groupKey}:compare`;
}

function getImageView(viewId) {
  if (!state.imageViews[viewId]) {
    state.imageViews[viewId] = { scale: 1, x: 0, y: 0 };
  }
  return state.imageViews[viewId];
}

function imageTransformStyle(viewId) {
  const view = getImageView(viewId);
  return `transform: translate3d(${view.x}px, ${view.y}px, 0) scale(${view.scale});`;
}

function applyImageViewToElement(viewId, img) {
  img.style.transform = imageTransformStyle(viewId).replace("transform: ", "").replace(";", "");
}

function applyImageView(viewId) {
  els.content.querySelectorAll(`.image-box[data-view-id="${CSS.escape(viewId)}"] img`).forEach((img) => {
    applyImageViewToElement(viewId, img);
  });
}

function imageBlock(title, path, url, error, sampleKey, role, extraClass = "", syncViewId = "") {
  const safeTitle = escapeHtml(title);
  const safePath = escapeHtml(path || "");
  const viewId = syncViewId || imageViewId(sampleKey, role);
  const safeViewId = escapeHtml(viewId);
  const syncAttribute = syncViewId ? ` data-sync-view="${safeViewId}"` : "";
  if (error || !url) {
    return `<div class="image-box image-missing ${extraClass}" data-view-id="${safeViewId}"${syncAttribute}>
      <div class="image-title">${safeTitle}</div>
      <div class="image-error">${escapeHtml(error || "image unavailable")}</div>
      <div class="image-path">${safePath}</div>
    </div>`;
  }
  return `<figure class="image-box ${extraClass}" data-view-id="${safeViewId}"${syncAttribute}>
    <figcaption class="image-title">${safeTitle}</figcaption>
    <div class="image-stage">
      <img src="${escapeHtml(url)}" alt="${safeTitle}" data-source-path="${safePath}" loading="lazy" decoding="async" style="${imageTransformStyle(viewId)}">
    </div>
    <div class="image-path" title="${safePath}">${safePath}</div>
  </figure>`;
}

function renderSharedImageCard(group, title, path, url, error, role) {
  const syncViewId = role === "source" ? comparisonImageViewId(group.group_key || "") : "";
  return `<article class="shared-image-card">
    ${imageBlock(title, path, url, error, group.group_key || "", role, "", syncViewId)}
  </article>`;
}

function renderTargetCard(group, target) {
  const key = target.sample_key || "";
  const label = state.labels[key]?.human_label || "";
  const selected = key === state.selectedKey ? " selected" : "";
  const hovered = key === state.hoverKey ? " hovered" : "";
  const labelClass = label ? ` label-${label}` : "";
  const titlePath = target.target_path || target.file_name || "";
  const title = target.target_dir_name || `Target ${Number(target.target_index || 0) + 1}`;

  return `<article class="target-card${selected}${hovered}${labelClass}" data-key="${escapeHtml(key)}" data-group-key="${escapeHtml(group.group_key || "")}">
    <header class="target-header">
      <strong>${escapeHtml(title)}</strong>
      <span class="sample-path" title="${escapeHtml(titlePath)}">${escapeHtml(titlePath || key)}</span>
      <span class="label-pill">${escapeHtml(label || "unlabeled")}</span>
    </header>
    ${imageBlock("file_name", target.target_path || target.file_name, target.target, target.image_errors?.file_name, key, "target", "target-image", comparisonImageViewId(group.group_key || ""))}
    <footer class="actions">
      <button type="button" data-action="label" data-label="pass" data-key="${escapeHtml(key)}">Pass</button>
      <button type="button" data-action="label" data-label="fail" data-key="${escapeHtml(key)}">Fail</button>
      <button type="button" data-action="label" data-label="" data-key="${escapeHtml(key)}">Clear</button>
    </footer>
  </article>`;
}

function renderGroupCard(group) {
  const reviewed = state.groupProgress[group.group_key]?.reviewed === true;
  const prompt = group.prompt || "";
  const targets = Array.isArray(group.targets) ? group.targets : [];
  const warning = targets.length
    ? ""
    : `<div class="group-warning">No target image matched ${escapeHtml(group.basename || "this record")}.</div>`;

  return `<section class="group-card${reviewed ? " reviewed" : ""}" data-group-key="${escapeHtml(group.group_key || "")}" style="--images-per-row: ${state.imagesPerRow};">
    <header class="group-header">
      <strong>#${Number(group.index || 0) + 1}</strong>
      <span class="sample-path" title="${escapeHtml(group.basename || "")}">${escapeHtml(group.basename || group.group_key || "")}</span>
      <span class="label-pill">${reviewed ? "reviewed" : "unreviewed"}</span>
    </header>
    <section class="prompt" aria-label="Prompt">${escapeHtml(prompt || "No prompt text")}</section>
    ${warning}
    <div class="image-grid">
      ${renderSharedImageCard(group, "cond_1", group.source_path || "", group.source, group.image_errors?.cond_1, "source")}
      ${renderSharedImageCard(group, "cond_2", group.reference_path || "", group.reference, group.image_errors?.cond_2, "reference")}
      ${targets.map((target) => renderTargetCard(group, target)).join("")}
    </div>
  </section>`;
}

function render() {
  clampPage();
  const groups = currentPageGroups();
  els.content.innerHTML = groups.length
    ? groups.map(renderGroupCard).join("")
    : `<section class="empty-state">Load a JSON file to begin labeling.</section>`;
  updateStats();
}

function selectFirstVisible() {
  state.selectedKey = firstVisibleTargetKey();
}

async function prevPage() {
  if (state.currentPage <= 1) return;
  await fetchPage(state.currentPage - 1);
}

async function nextPage() {
  if (state.currentPage >= totalPages()) return;
  await fetchPage(state.currentPage + 1);
}

async function jumpPage() {
  const value = Number(els.pageJumpInput.value);
  if (!Number.isFinite(value)) return;
  await fetchPage(Math.min(Math.max(1, Math.floor(value)), totalPages()));
}

async function changePageSize() {
  const selectedGroup = state.groups.find((group) =>
    (group.targets || []).some((target) => target.sample_key === state.selectedKey)
  );
  const indexToKeep = selectedGroup?.index ?? ((state.currentPage - 1) * state.pageSize);
  const keyToKeep = state.selectedKey || "";
  const nextSize = Math.min(Math.max(1, Number(els.pageSizeInput.value) || 20), 200);
  state.pageSize = nextSize;
  localStorage.setItem(PAGE_SIZE_KEY, String(nextSize));
  els.pageSizeInput.value = String(nextSize);
  await fetchPage(pageForIndex(indexToKeep), keyToKeep);
}

function changeImagesPerRow() {
  const nextValue = Math.min(Math.max(1, Number(els.imagesPerRowInput.value) || 4), 8);
  state.imagesPerRow = nextValue;
  localStorage.setItem(IMAGES_PER_ROW_KEY, String(nextValue));
  els.imagesPerRowInput.value = String(nextValue);
  render();
}

function onContentClick(event) {
  const card = event.target.closest(".target-card");
  if (card) state.selectedKey = card.dataset.key || "";

  const button = event.target.closest("button[data-action='label']");
  if (button) {
    setLabel(button.dataset.key || "", button.dataset.label || "")
      .catch((error) => showToast(error.message || "Label failed."));
    return;
  }

  if (card) render();
}

function onContentHover(event) {
  const card = event.target.closest(".target-card");
  if (!card || state.hoverKey === card.dataset.key) return;
  state.hoverKey = card.dataset.key || "";
}

function onContentLeave(event) {
  if (event.relatedTarget && els.content.contains(event.relatedTarget)) return;
  if (!state.hoverKey) return;
  state.hoverKey = "";
}

function activeKey() {
  return state.hoverKey || state.selectedKey || firstVisibleTargetKey();
}

async function setLabel(sampleKey, humanLabel) {
  if (!sampleKey) {
    showToast("No target selected.");
    return;
  }

  const data = await postJson("/api/label", {
    sample_key: sampleKey,
    human_label: humanLabel,
  });

  state.labels[sampleKey] = data.label || { human_label: humanLabel };
  state.groupProgress = data.group_progress || state.groupProgress;
  state.stats = data.stats || state.stats;
  state.selectedKey = sampleKey;
  render();
  showToast(humanLabel ? `Saved ${humanLabel}.` : "Label cleared.");
}

async function exportData() {
  const exportDir = els.exportDir.value.trim();
  if (!exportDir) {
    showToast("Enter an export directory first.");
    return;
  }

  els.exportBtn.disabled = true;
  els.exportBtn.textContent = "Exporting...";
  try {
    const data = await postJson("/api/export", {
      export_dir: exportDir,
      annotated_filename: els.annotatedFilename.value.trim(),
      pass_filename: els.acceptedFilename.value.trim(),
      fail_filename: els.rejectedFilename.value.trim(),
    });
    const counts = data.counts || {};
    showToast(`Exported all ${counts.annotated || 0}, pass ${counts.pass || 0}, fail ${counts.fail || 0}.`);
  } finally {
    els.exportBtn.disabled = false;
    els.exportBtn.textContent = "Export";
  }
}

function findTargetByKey(sampleKey) {
  for (const group of state.groups) {
    const item = (group.targets || []).find((candidate) => candidate.sample_key === sampleKey);
    if (item) return item;
  }
  return null;
}

function onImageMouseDown(event) {
  if (event.button !== 0) return;
  const imageBox = event.target.closest(".image-box");
  const img = imageBox?.querySelector("img");
  if (!imageBox || !img) return;

  const card = event.target.closest(".target-card");
  if (card) {
    state.selectedKey = card.dataset.key || "";
  }

  startImageCompare(event, imageBox, img);
  const viewId = imageBox.dataset.viewId || "";
  const view = getImageView(viewId);
  state.activePan = {
    viewId,
    img,
    startX: event.clientX,
    startY: event.clientY,
    originX: view.x,
    originY: view.y,
  };
  img.classList.add("dragging");
  event.preventDefault();
}

function startImageCompare(event, imageBox, img) {
  if (!imageBox.classList.contains("target-image")) return;

  const card = event.target.closest(".target-card");
  const item = findTargetByKey(card?.dataset.key || "");
  if (!img || !item?.source) return;

  img.dataset.targetSrc = img.src;
  img.src = item.source;
}

function onImageMouseMove(event) {
  if (!state.activePan) return;
  const view = getImageView(state.activePan.viewId);
  view.x = state.activePan.originX + event.clientX - state.activePan.startX;
  view.y = state.activePan.originY + event.clientY - state.activePan.startY;
  applyImageView(state.activePan.viewId);
  event.preventDefault();
}

function onImageMouseUp() {
  if (state.activePan?.img) {
    state.activePan.img.classList.remove("dragging");
  }
  state.activePan = null;
  els.content.querySelectorAll(".target-image img[data-target-src]").forEach((img) => {
    img.src = img.dataset.targetSrc;
    delete img.dataset.targetSrc;
  });
}

function onImageWheel(event) {
  const imageBox = event.target.closest(".image-box");
  const img = imageBox?.querySelector("img");
  if (!imageBox || !img) return;

  const viewId = imageBox.dataset.viewId || "";
  const view = getImageView(viewId);
  const delta = event.deltaY < 0 ? 0.12 : -0.12;
  view.scale = Math.min(6, Math.max(0.4, Number((view.scale + delta).toFixed(2))));
  applyImageView(viewId);
  event.preventDefault();
}

function onImageDoubleClick(event) {
  const imageBox = event.target.closest(".image-box");
  const img = imageBox?.querySelector("img");
  if (!imageBox || !img) return;

  const viewId = imageBox.dataset.viewId || "";
  state.imageViews[viewId] = { scale: 1, x: 0, y: 0 };
  applyImageView(viewId);
  event.preventDefault();
}

function isEditingText(event) {
  const target = event.target;
  if (!target) return false;
  return target.tagName === "INPUT" ||
    target.tagName === "TEXTAREA" ||
    target.tagName === "SELECT" ||
    target.isContentEditable;
}

function onKeyDown(event) {
  if (isEditingText(event)) return;

  if (event.key === "ArrowLeft") {
    event.preventDefault();
    prevPage().catch((error) => showToast(error.message || "Page load failed."));
  } else if (event.key === "ArrowRight") {
    event.preventDefault();
    nextPage().catch((error) => showToast(error.message || "Page load failed."));
  } else if (event.key.toLowerCase() === "a") {
    event.preventDefault();
    setLabel(activeKey(), "pass").catch((error) => showToast(error.message || "Label failed."));
  } else if (event.key.toLowerCase() === "d") {
    event.preventDefault();
    setLabel(activeKey(), "fail").catch((error) => showToast(error.message || "Label failed."));
  } else if (event.key.toLowerCase() === "c") {
    event.preventDefault();
    setLabel(activeKey(), "").catch((error) => showToast(error.message || "Label failed."));
  }
}

function bindEvents() {
  els.loadBtn.addEventListener("click", loadData);
  els.exportBtn.addEventListener("click", () => exportData().catch((error) => showToast(error.message || "Export failed.")));
  els.prevBtn.addEventListener("click", () => prevPage().catch((error) => showToast(error.message || "Page load failed.")));
  els.nextBtn.addEventListener("click", () => nextPage().catch((error) => showToast(error.message || "Page load failed.")));
  els.jumpBtn.addEventListener("click", () => jumpPage().catch((error) => showToast(error.message || "Page load failed.")));
  els.pageJumpInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") jumpPage().catch((error) => showToast(error.message || "Page load failed."));
  });
  els.pageSizeInput.addEventListener("change", () => changePageSize().catch((error) => showToast(error.message || "Page load failed.")));
  els.imagesPerRowInput.addEventListener("change", changeImagesPerRow);
  els.content.addEventListener("click", onContentClick);
  els.content.addEventListener("mouseover", onContentHover);
  els.content.addEventListener("mouseout", onContentLeave);
  els.content.addEventListener("mousedown", onImageMouseDown);
  els.content.addEventListener("wheel", onImageWheel, { passive: false });
  els.content.addEventListener("dblclick", onImageDoubleClick);
  document.addEventListener("mousemove", onImageMouseMove);
  document.addEventListener("mouseup", onImageMouseUp);
  document.addEventListener("keydown", onKeyDown);
}

initElements();
bindEvents();
render();
