/* Smart Archive frontend logic */
const $ = (id) => document.getElementById(id);

const state = { settings: null, tree: null, doc: null, plan: null, folders: [] };

/* ---------- theme ---------- */
function setTheme(t) {
  document.documentElement.dataset.theme = t;
  localStorage.setItem("sa-theme", t);
  $("btn-theme").textContent = t === "dark" ? "☀️" : "🌙";
}
setTheme(localStorage.getItem("sa-theme") || "dark");
$("btn-theme").onclick = () =>
  setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");

/* ---------- toast ---------- */
function toast(msg, err = false) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.toggle("err", err);
  t.classList.remove("hidden");
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.add("hidden"), 6000);
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || res.statusText);
  return data;
}

/* ---------- settings & status ---------- */
async function loadSettings() {
  const d = await api("/api/settings");
  state.settings = d.settings;
  $("archive-root-label").textContent = d.settings.archive_root;
  $("model-label").textContent = d.settings.model;
  $("auto-mode").checked = d.settings.mode === "auto";
  const pill = $("ai-status");
  pill.classList.remove("status-unknown", "status-ok", "status-bad");
  if (d.ollama[0]) { pill.classList.add("status-ok"); pill.textContent = "● AI online"; }
  else { pill.classList.add("status-bad"); pill.title = d.ollama[1]; pill.textContent = "● AI offline"; }
}

$("btn-settings").onclick = () => {
  const s = state.settings;
  $("s-root").value = s.archive_root; $("s-ollama").value = s.ollama_url;
  $("s-model").value = s.model; $("s-lang").value = s.language_hint;
  $("settings-modal").showModal();
};
$("s-cancel").onclick = () => $("settings-modal").close();
$("s-save").onclick = async () => {
  await api("/api/settings", { method: "PUT", body: {
    archive_root: $("s-root").value.trim(), ollama_url: $("s-ollama").value.trim(),
    model: $("s-model").value.trim(), language_hint: $("s-lang").value,
  }});
  $("settings-modal").close();
  await loadSettings(); await loadTree();
  toast("Settings saved ✓");
};

$("auto-mode").onchange = async (e) => {
  await api("/api/settings", { method: "PUT", body: { mode: e.target.checked ? "auto" : "review" } });
  toast(e.target.checked ? "Auto-Archive Mode enabled" : "Review Mode enabled");
};

/* ---------- tree ---------- */
function renderTree(node, container) {
  const ul = document.createElement("ul");
  const li = document.createElement("li");
  const count = node.file_count ? ` <span class="cnt">(${node.file_count})</span>` : "";
  li.innerHTML = `📁 ${escapeHtml(node.name)}/${count}`;
  li.onclick = (e) => {
    e.stopPropagation();
    document.querySelectorAll(".tree li.selected").forEach(el => el.classList.remove("selected"));
    li.classList.add("selected");
    if (!node.path.startsWith(state.settings.archive_root)) return;
    const rel = node.path.slice(state.settings.archive_root.length).replace(/^\//, "");
    $("p-target").value = rel;
  };
  ul.appendChild(li);
  if (node.children?.length) {
    const sub = document.createElement("ul");
    node.children.forEach(c => renderTreeInto(c, sub));
    ul.appendChild(sub);
  }
  container.appendChild(ul);
}
function renderTreeInto(node, container) {
  const li = document.createElement("li");
  const count = node.file_count ? ` <span class="cnt">(${node.file_count})</span>` : "";
  li.innerHTML = `📁 ${escapeHtml(node.name)}/${count}`;
  li.onclick = (e) => {
    e.stopPropagation();
    document.querySelectorAll(".tree li.selected").forEach(el => el.classList.remove("selected"));
    li.classList.add("selected");
    const rel = node.path.slice(state.settings.archive_root.length).replace(/^\//, "");
    $("p-target").value = rel;
  };
  if (node.children?.length) {
    const sub = document.createElement("ul");
    node.children.forEach(c => renderTreeInto(c, sub));
    li.appendChild(sub);
  }
  container.appendChild(li);
}
function escapeHtml(s) { const d = document.createElement("div"); d.textContent = s ?? ""; return d.innerHTML; }

async function loadTree() {
  const d = await api("/api/tree");
  state.tree = d.tree;
  state.folders = flatten(d.tree);
  $("tree").innerHTML = "";
  renderTree(d.tree, $("tree"));
  $("folder-list").innerHTML = state.folders
    .map(f => `<option value="${escapeHtml(f)}">`).join("");
}
function flatten(node, acc = [], rel = "") {
  const name = node.name || "";
  const r = rel ? `${rel}/${name}` : "";
  if (r) acc.push(r);
  (node.children || []).forEach(c => flatten(c, acc, r));
  return acc;
}
$("btn-refresh-tree").onclick = loadTree;

/* ---------- folder browser ---------- */
let browsePath = "";
async function browseTo(path) {
  try {
    const d = await api(`/api/browse?path=${encodeURIComponent(path)}`);
    browsePath = d.current;
    $("b-current").textContent = d.current;
    $("b-up").disabled = !d.parent;
    const list = $("b-list");
    list.innerHTML = d.dirs.length
      ? d.dirs.map(x => `<li data-path="${escapeHtml(x.path)}">📁 ${escapeHtml(x.name)}</li>`).join("")
      : `<li class="empty-li">No subfolders here</li>`;
    list.querySelectorAll("li[data-path]").forEach(li => {
      li.onclick = () => browseTo(li.dataset.path);
    });
  } catch (e) { toast(e.message, true); }
}
function pywebviewReady(timeoutMs = 1500) {
  if (window.pywebview?.api?.select_folder) return Promise.resolve(true);
  return new Promise((resolve) => {
    const t0 = Date.now();
    const iv = setInterval(() => {
      if (window.pywebview?.api?.select_folder) { clearInterval(iv); resolve(true); }
      else if (Date.now() - t0 > timeoutMs) { clearInterval(iv); resolve(false); }
    }, 100);
  });
}

$("s-browse").onclick = async () => {
  // Desktop mode: use the real system folder chooser (native dialog with absolute path)
  if (await pywebviewReady()) {
    try {
      const path = await window.pywebview.api.select_folder($("s-root").value.trim() || "");
      if (path) { $("s-root").value = path; toast("Folder selected ✓"); }
      return;
    } catch (e) { toast(e.message || String(e), true); return; }
  }
  // Browser mode: in-app folder picker
  browseTo($("s-root").value.trim() || "");
  $("browser-modal").showModal();
};
$("b-up").onclick = () => {
  if (browsePath) browseTo(browsePath.replace(/\/[^/]+\/?$/, "") || "/");
};
$("b-cancel").onclick = () => $("browser-modal").close();
$("b-select").onclick = () => {
  $("s-root").value = browsePath;
  $("browser-modal").close();
};

/* ---------- upload ---------- */
const dz = $("dropzone");
dz.onclick = (e) => { if (e.target.tagName !== "BUTTON") $("file-input").click(); };
$("btn-browse").onclick = () => $("file-input").click();
$("file-input").onchange = (e) => e.target.files[0] && uploadFile(e.target.files[0]);
["dragenter", "dragover"].forEach(ev => dz.addEventListener(ev, (e) => {
  e.preventDefault(); dz.classList.add("dragover");
}));
["dragleave", "drop"].forEach(ev => dz.addEventListener(ev, (e) => {
  e.preventDefault(); dz.classList.remove("dragover");
}));
dz.addEventListener("drop", (e) => e.dataTransfer.files[0] && uploadFile(e.dataTransfer.files[0]));

$("btn-scan").onclick = async () => {
  setBusy("Capturing from scanner…");
  try {
    const d = await api("/api/capture/scan", { method: "POST", body: {} });
    setDoc({ path: d.path, name: d.name, size: d.size });
    await analyze();
  } catch (e) { toast(e.message, true); }
  setBusy(false);
};
$("btn-webcam").onclick = async () => {
  setBusy("Capturing from webcam…");
  try {
    const d = await api("/api/capture/webcam", { method: "POST", body: {} });
    setDoc({ path: d.path, name: d.name, size: d.size });
    await analyze();
  } catch (e) { toast(e.message, true); }
  setBusy(false);
};

async function uploadFile(file) {
  if (file.size > 25 * 1024 * 1024) return toast("File too large (>25 MB)", true);
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch("/api/upload", { method: "POST", body: fd });
  const d = await res.json();
  if (!res.ok) return toast(d.detail || "Upload failed", true);
  setDoc({ path: d.path, name: d.name, size: d.size });
  await analyze();
}

function setDoc(d) {
  state.doc = d;
  $("preview-area").classList.remove("hidden");
  $("preview-img").src = `/api/file?path=${encodeURIComponent(d.path)}&t=${Date.now()}`;
  $("preview-name").textContent = d.name;
  $("preview-size").textContent = `${(d.size / 1024).toFixed(0)} KB`;
}
$("btn-clear-doc").onclick = () => {
  state.doc = null; state.plan = null;
  $("preview-area").classList.add("hidden");
  $("plan").classList.add("hidden"); $("plan-empty").classList.remove("hidden");
};

function setBusy(text) {
  const l = $("preview-loading");
  if (text) { $("loading-text").textContent = text; l.classList.remove("hidden"); }
  else l.classList.add("hidden");
}

/* ---------- AI analyze ---------- */
async function analyze() {
  if (!state.doc) return;
  $("plan-empty").classList.add("hidden");
  $("plan").classList.add("hidden");
  setBusy("Gemma is reading your document…");
  try {
    const d = await api("/api/analyze", { method: "POST", body: { path: state.doc.path } });
    fillPlan(d.plan);
    if (state.settings.mode === "auto" && !state.plan) {
      fillPlan(d.plan);
      await doArchive(); // auto mode: file immediately
    }
  } catch (e) {
    toast(e.message, true);
    $("plan-empty").classList.remove("hidden");
  }
  setBusy(false);
}

function fillPlan(plan) {
  state.plan = plan;
  $("plan").classList.remove("hidden");
  $("plan-empty").classList.add("hidden");
  $("p-title").value = plan.title || "";
  $("p-type").value = plan.doc_type || "";
  $("p-target").value = plan.target_dir || "";
  $("p-create").checked = !!plan.create_folder && !plan.target_dir_exists;
  $("p-filename").value = plan.filename || "";
  $("p-sum-ar").textContent = plan.summary_ar || "—";
  $("p-sum-en").textContent = plan.summary_en || "—";
  const conf = Math.round((plan.confidence || 0) * 100);
  const pill = $("p-confidence");
  pill.textContent = `confidence ${conf}%`;
  pill.style.color = conf >= 70 ? "var(--ok)" : conf >= 45 ? "var(--warn)" : "var(--err)";
}

/* ---------- archive ---------- */
$("btn-archive").onclick = doArchive;

async function doArchive() {
  const body = {
    path: state.doc.path,
    target_dir: $("p-target").value.trim(),
    filename: $("p-filename").value.trim(),
    create_folder: $("p-create").checked,
    meta: { title: $("p-title").value, doc_type: $("p-type").value,
            summary_ar: $("p-sum-ar").textContent, summary_en: $("p-sum-en").textContent },
  };
  if (!body.target_dir || !body.filename) return toast("Target folder and filename are required", true);
  $("btn-archive").disabled = true;
  setBusy("Converting to PDF and filing…");
  try {
    const d = await api("/api/archive", { method: "POST", body });
    const b = $("result-banner");
    b.classList.remove("hidden", "err");
    b.innerHTML = `✅ Saved: <strong>${escapeHtml(d.result.saved_path)}</strong>`;
    toast(`PDF archived → ${d.result.saved_path}`);
    renderActivity(d.activity);
    await loadTree();
    state.plan = null;
  } catch (e) {
    $("result-banner").classList.remove("hidden");
    $("result-banner").classList.add("err");
    $("result-banner").textContent = `❌ ${e.message}`;
    toast(e.message, true);
  }
  $("btn-archive").disabled = false;
  setBusy(false);
}

/* ---------- activity ---------- */
function renderActivity(entries) {
  const list = $("activity-list");
  list.innerHTML = (entries || []).map(e => `
    <li>
      <div>
        <div><strong>${escapeHtml(e.filename)}</strong> <span class="cnt">${escapeHtml(e.doc_type || "")}</span></div>
        <div class="path">${escapeHtml(e.folder)}</div>
      </div>
      <a href="/api/file?path=${encodeURIComponent(e.saved_path)}" target="_blank">Open ↗</a>
    </li>`).join("") || `<li class="path">No archives yet.</li>`;
}
$("btn-clear-activity").onclick = async () => {
  const d = await api("/api/activity", { method: "DELETE" });
  renderActivity(d.activity);
};

/* ---------- boot ---------- */
(async () => {
  await loadSettings();
  await loadTree();
  const d = await api("/api/activity");
  renderActivity(d.activity);
})();
