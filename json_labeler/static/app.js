const PAGE_SIZE_KEY = "jsonLabeler.pageSize";

function storedPageSize() {
  const value = Number(localStorage.getItem(PAGE_SIZE_KEY)) || 20;
  return Math.min(Math.max(1, Math.floor(value)), 200);
}

const state = {
  items: [],
  labels: {},
  stats: { total: 0, labeled: 0, pass: 0, fail: 0, unlabeled: 0 },
  currentPage: 1,
  pageSize: storedPageSize(),
  selectedKey: "",
  hoverKey: "",
  zoom: 1,
};

const els = {};
let toastTimer = 0;

function initElements() {
  Object.assign(els, {
    inputJsonPath: document.querySelector("#inputJsonPath"),
    loadBtn: document.querySelector("#loadBtn"),
    progressPath: document.querySelector("#progressPath"),
    exportDir: document.querySelector("#exportDir"),
    annotatedFilename: document.querySelector("#annotatedFilename"),
    acceptedFilename: document.querySelector("#acceptedFilename"),
    rejectedFilename: document.querySelector("#rejectedFilename"),
    exportBtn: document.querySelector("#exportBtn"),
    statsText: document.querySelector("#statsText"),
    pageSizeInput: document.querySelector("#pageSizeInput"),
    prevBtn: document.querySelector("#prevBtn"),
    pageText: document.querySelector("#pageText"),
    nextBtn: document.querySelector("#nextBtn"),
    pageJumpInput: document.querySelector("#pageJumpInput"),
    jumpBtn: document.querySelector("#jumpBtn"),
    content: document.querySelector("#content"),
    toast: document.querySelector("#toast"),
  });

  els.pageSizeInput.value = String(state.pageSize);
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
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

async function loadData() {
  const inputJsonPath = els.inputJsonPath.value.trim();
  if (!inputJsonPath) {
    showToast("Enter an input JSON path first.");
    return;
  }

  els.loadBtn.disabled = true;
  els.loadBtn.textContent = "Loading...";
  try {
    const data = await postJson("/api/load", { input_json_path: inputJsonPath });
    state.items = Array.isArray(data.items) ? data.items : [];
    state.labels = data.labels && typeof data.labels === "object" ? data.labels : {};
    state.stats = data.stats || state.stats;
    state.selectedKey = firstUnlabeledKey() || state.items[0]?.sample_key || "";
    state.currentPage = state.selectedKey ? pageForKey(state.selectedKey) : 1;
    state.hoverKey = "";
    els.progressPath.value = data.progress_path || "Not loaded";
    render();
    showToast(`Loaded ${state.items.length} samples.`);
  } catch (error) {
    showToast(error.message || "Load failed.");
  } finally {
    els.loadBtn.disabled = false;
    els.loadBtn.textContent = "Load/Resume";
  }
}

function totalPages() {
  return Math.max(1, Math.ceil(state.items.length / state.pageSize));
}

function clampPage() {
  state.currentPage = Math.min(Math.max(1, state.currentPage), totalPages());
}

function updateStats(stats = state.stats) {
  state.stats = stats || state.stats;
  els.statsText.textContent =
    `Total ${state.stats.total || 0} | ` +
    `Labeled ${state.stats.labeled || 0} | ` +
    `Pass ${state.stats.pass || 0} | ` +
    `Fail ${state.stats.fail || 0} | ` +
    `Unlabeled ${state.stats.unlabeled || 0}`;
  els.pageText.textContent = `Page ${state.currentPage} / ${totalPages()}`;
  els.pageJumpInput.value = String(state.currentPage);
  els.prevBtn.disabled = state.currentPage <= 1;
  els.nextBtn.disabled = state.currentPage >= totalPages();
}

function currentPageItems() {
  const start = (state.currentPage - 1) * state.pageSize;
  return state.items.slice(start, start + state.pageSize);
}

function firstUnlabeledKey() {
  const item = state.items.find((candidate) => {
    const label = state.labels[candidate.sample_key]?.human_label || "";
    return label === "";
  });
  return item?.sample_key || "";
}

function pageForKey(sampleKey) {
  const index = state.items.findIndex((item) => item.sample_key === sampleKey);
  if (index < 0) return state.currentPage;
  return Math.floor(index / state.pageSize) + 1;
}

function imageBlock(title, path, url, error, extraClass = "") {
  const safeTitle = escapeHtml(title);
  const safePath = escapeHtml(path || "");
  if (error || !url) {
    return `<div class="image-box image-missing ${extraClass}">
      <div class="image-title">${safeTitle}</div>
      <div class="image-error">${escapeHtml(error || "image unavailable")}</div>
      <div class="image-path">${safePath}</div>
    </div>`;
  }
  return `<figure class="image-box ${extraClass}">
    <figcaption class="image-title">${safeTitle}</figcaption>
    <img src="${escapeHtml(url)}" alt="${safeTitle}" data-source-path="${safePath}">
    <div class="image-path" title="${safePath}">${safePath}</div>
  </figure>`;
}

function renderCard(item) {
  const key = item.sample_key || "";
  const label = state.labels[key]?.human_label || "";
  const selected = key === state.selectedKey ? " selected" : "";
  const hovered = key === state.hoverKey ? " hovered" : "";
  const labelClass = label ? ` label-${label}` : "";
  const prompt = item.prompt || item.text_prompt || item.caption || "";
  const titlePath = item.target_path || item.file_name || "";

  return `<article class="sample-card${selected}${hovered}${labelClass}" data-key="${escapeHtml(key)}">
    <header class="card-header">
      <strong>#${Number(item.index || 0) + 1}</strong>
      <span class="sample-path" title="${escapeHtml(titlePath)}">${escapeHtml(titlePath || key)}</span>
      <span class="label-pill">${escapeHtml(label || "unlabeled")}</span>
    </header>
    <div class="image-row" style="--zoom:${state.zoom}">
      ${imageBlock("cond_1", item.source_path || item.cond_1, item.source, item.image_errors?.cond_1)}
      ${imageBlock("cond_2", item.reference_path || item.cond_2, item.reference, item.image_errors?.cond_2)}
      ${imageBlock("file_name", item.target_path || item.file_name, item.target, item.image_errors?.file_name, "target-image")}
    </div>
    <section class="prompt" aria-label="Prompt">${escapeHtml(prompt || "No prompt text")}</section>
    <footer class="actions">
      <button type="button" data-action="label" data-label="pass" data-key="${escapeHtml(key)}">Pass</button>
      <button type="button" data-action="label" data-label="fail" data-key="${escapeHtml(key)}">Fail</button>
      <button type="button" data-action="label" data-label="" data-key="${escapeHtml(key)}">Clear</button>
    </footer>
  </article>`;
}

function render() {
  clampPage();
  const items = currentPageItems();
  els.content.innerHTML = items.length
    ? items.map(renderCard).join("")
    : `<section class="empty-state">Load a JSON file to begin labeling.</section>`;
  updateStats();
}

function selectFirstVisible() {
  state.selectedKey = currentPageItems()[0]?.sample_key || "";
}

function prevPage() {
  if (state.currentPage <= 1) return;
  state.currentPage -= 1;
  selectFirstVisible();
  render();
}

function nextPage() {
  if (state.currentPage >= totalPages()) return;
  state.currentPage += 1;
  selectFirstVisible();
  render();
}

function jumpPage() {
  const value = Number(els.pageJumpInput.value);
  if (!Number.isFinite(value)) return;
  state.currentPage = Math.min(Math.max(1, Math.floor(value)), totalPages());
  selectFirstVisible();
  render();
}

function changePageSize() {
  const keyToKeep = state.selectedKey || currentPageItems()[0]?.sample_key || "";
  const nextSize = Math.min(Math.max(1, Number(els.pageSizeInput.value) || 20), 200);
  state.pageSize = nextSize;
  localStorage.setItem(PAGE_SIZE_KEY, String(nextSize));
  els.pageSizeInput.value = String(nextSize);
  state.currentPage = keyToKeep ? pageForKey(keyToKeep) : 1;
  render();
}

function onContentClick(event) {
  const card = event.target.closest(".sample-card");
  if (card) state.selectedKey = card.dataset.key || "";

  const button = event.target.closest("button[data-action='label']");
  if (button) {
    showToast("Label actions will be enabled in Task 5.");
    render();
    return;
  }

  if (card) render();
}

function onContentHover(event) {
  const card = event.target.closest(".sample-card");
  if (!card || state.hoverKey === card.dataset.key) return;
  state.hoverKey = card.dataset.key || "";
}

function onContentLeave(event) {
  if (event.relatedTarget && els.content.contains(event.relatedTarget)) return;
  if (!state.hoverKey) return;
  state.hoverKey = "";
}

function bindEvents() {
  els.loadBtn.addEventListener("click", loadData);
  els.exportBtn.addEventListener("click", () => showToast("Export will be enabled in a later task."));
  els.prevBtn.addEventListener("click", prevPage);
  els.nextBtn.addEventListener("click", nextPage);
  els.jumpBtn.addEventListener("click", jumpPage);
  els.pageJumpInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") jumpPage();
  });
  els.pageSizeInput.addEventListener("change", changePageSize);
  els.content.addEventListener("click", onContentClick);
  els.content.addEventListener("mouseover", onContentHover);
  els.content.addEventListener("mouseout", onContentLeave);
}

initElements();
bindEvents();
render();
