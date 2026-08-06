/* JobRadar app logic. All data comes through window.pywebview.api — JS never
   builds SQL and never receives unsanitised HTML. */

"use strict";

const $ = (sel) => document.querySelector(sel);
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
};

window.addEventListener("error", (e) => {
  const b = document.querySelector("#banner");
  if (b) { b.hidden = false; b.textContent = "UI error: " + e.message + " @ " + e.filename + ":" + e.lineno; }
});
window.addEventListener("unhandledrejection", (e) => {
  const b = document.querySelector("#banner");
  const r = e.reason || {};
  if (b) { b.hidden = false; b.textContent = "UI error: " + (r.message || r) + " | " + String(r.stack || "").slice(0, 400); }
});

const state = {
  trackers: [],
  trackerId: null,
  jobs: [],
  selected: -1,
  view: "tracker",          // 'tracker' | 'applied'
  windowOverride: null,     // session-only view override of the tracker's window
  query: "",
  dbOk: true,
};

const api = () => window.pywebview.api;

/* ---------- helpers ---------- */

function timeAgo(iso) {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 3600) return `${Math.max(1, Math.floor(s / 60))}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  if (s < 86400 * 30) return `${Math.floor(s / 86400)}d`;
  return `${Math.floor(s / 86400 / 30)}mo`;
}

function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

function srcBase(source) { return source.split(":")[0]; }

/* ---------- trackers sidebar ---------- */

async function refreshTrackers() {
  state.trackers = await api().list_trackers();
  const list = $("#tracker-list");
  list.innerHTML = "";
  for (const t of state.trackers) {
    const b = el("button", "tracker-item");
    b.dataset.id = t.id;
    if (state.view === "tracker" && t.id === state.trackerId) b.classList.add("active");
    b.append(el("span", "t-name", t.name));
    if (t.new_count > 0) b.append(el("span", "t-count", t.new_count > 99 ? "99+" : String(t.new_count)));
    b.addEventListener("click", () => openTracker(t.id));
    b.addEventListener("contextmenu", (e) => {
      e.preventDefault();
      showMenu(e, [
        { label: "Edit", fn: () => openModal(t) },
        { label: "Delete tracker", danger: true, fn: () => confirmDeleteTracker(t) },
      ]);
    });
    list.append(b);
  }
  const n = await api().applied_count();
  $("#applied-count").hidden = n === 0;
  $("#applied-count").textContent = String(n);
}

async function openTracker(id) {
  state.view = "tracker";
  state.trackerId = id;
  state.windowOverride = null;
  state.query = "";
  $("#search").value = "";
  showView();
  renderSkeleton();
  const res = await api().open_tracker(id, "", "");
  state.jobs = res.jobs;
  state.selected = state.jobs.length ? 0 : -1;
  renderChips(res.tracker ? res.tracker.date_window : "14d");
  renderResults();
  renderDetailForSelection();
  refreshTrackers();
}

const rerunSearch = debounce(async () => {
  if (state.view !== "tracker" || state.trackerId == null) return;
  const res = await api().search(state.trackerId, state.query, state.windowOverride || "");
  state.jobs = res.jobs;
  state.selected = state.jobs.length ? 0 : -1;
  renderResults();
  renderDetailForSelection();
}, 250);

/* ---------- window chips ---------- */

function renderChips(trackerWindow) {
  const active = state.windowOverride || trackerWindow;
  document.querySelectorAll("#window-chips .chip").forEach((c) => {
    c.classList.toggle("active", c.dataset.w === active);
  });
}

$("#window-chips").addEventListener("click", (e) => {
  const chip = e.target.closest(".chip");
  if (!chip) return;
  state.windowOverride = chip.dataset.w;
  renderChips();
  document.querySelectorAll("#window-chips .chip").forEach((c) =>
    c.classList.toggle("active", c === chip));
  rerunSearch();
});

/* ---------- results list ---------- */

function renderSkeleton() {
  const r = $("#results");
  r.innerHTML = "";
  for (let i = 0; i < 8; i++) {
    const s = el("div", "skel");
    s.append(el("div", "l1"), el("div", "l2"));
    r.append(s);
  }
}

function renderResults() {
  const r = $("#results");
  r.innerHTML = "";
  if (!state.jobs.length) {
    const t = state.trackers.find((x) => x.id === state.trackerId);
    const box = el("div", "empty-state");
    box.append(el("div", "big", "Nothing matches yet"));
    if (t) {
      const bits = [];
      if (t.include_terms?.length) bits.push(`include: ${t.include_terms.join(", ")}`);
      if (t.exclude_terms?.length) bits.push(`exclude: ${t.exclude_terms.join(", ")}`);
      bits.push(`window: ${state.windowOverride || t.date_window}`, `location: ${t.location_mode}`);
      box.append(el("div", null, bits.join("  ·  ")));
    }
    r.append(box);
    return;
  }
  state.jobs.forEach((j, i) => {
    const row = el("div", "row st-" + j.status);
    row.dataset.i = i;
    if (i === state.selected) row.classList.add("selected");

    const title = el("div", "row-title");
    if (j.is_new) title.append(el("span", "new-dot"));
    title.append(el("span", null, j.title));
    row.append(title);

    const meta = el("div", "row-meta");
    if (j.company) meta.append(el("span", "co", j.company));
    if (j.location_raw) meta.append(el("span", null, j.location_raw));
    meta.append(el("span", null, timeAgo(j.posted_at) + (j.posted_at_confident ? "" : "?")));
    if (j.sources?.length) meta.append(el("span", "badge b-src", srcBase(j.sources[0])));
    if (j.source_count > 1) meta.append(el("span", "badge b-src", "×" + j.source_count));
    if (j.remote_flag) meta.append(el("span", "badge b-remote", "remote"));
    for (const f of (j.geo_flags || []).slice(0, 3)) {
      meta.append(el("span", "badge b-geo", "⚠ " + f));
    }
    row.append(meta);

    row.addEventListener("click", () => selectRow(i));
    row.addEventListener("contextmenu", (e) => {
      e.preventDefault();
      selectRow(i);
      showMenu(e, [
        { label: "Interesting", fn: () => setStatus(j.id, "interesting") },
        { label: "Applied", fn: () => setStatus(j.id, "applied") },
        { label: "Dead", fn: () => setStatus(j.id, "dead") },
        { sep: true },
        { label: `Exclude ${j.company || "company"} from tracker`, fn: () => excludeCompany(j) },
        { label: "Copy link", fn: () => navigator.clipboard.writeText(j.apply_url) },
      ]);
    });
    r.append(row);
  });
}

function selectRow(i) {
  state.selected = i;
  document.querySelectorAll("#results .row").forEach((row) =>
    row.classList.toggle("selected", Number(row.dataset.i) === i));
  const row = document.querySelector(`#results .row[data-i="${i}"]`);
  if (row) row.scrollIntoView({ block: "nearest" });
  renderDetailForSelection();
}

/* ---------- detail pane ---------- */

async function renderDetailForSelection() {
  const d = $("#detail");
  const j = state.jobs[state.selected];
  if (!j) {
    d.innerHTML = "";
    d.append(el("div", "empty-pane", "Select a job"));
    return;
  }
  const full = await api().get_job(j.id);
  if (!full || state.jobs[state.selected]?.id !== full.id) return;
  d.innerHTML = "";

  d.append(el("div", "d-title", full.title));
  if (full.company) d.append(el("div", "d-co", full.company));
  const meta = [];
  if (full.location_raw) meta.push(full.location_raw);
  if (full.posted_at) meta.push("posted " + timeAgo(full.posted_at) + " ago" + (full.posted_at_confident ? "" : " (approx)"));
  if (full.salary_raw) meta.push(full.salary_raw);
  if (full.employment_type) meta.push(full.employment_type);
  if (full.sources?.length) meta.push("via " + full.sources.map(srcBase).join(", "));
  d.append(el("div", "d-meta", meta.join("  ·  ")));

  const badges = el("div", "d-badges");
  if (full.remote_flag) badges.append(el("span", "badge b-remote", "remote"));
  for (const f of full.geo_flags || []) badges.append(el("span", "badge b-geo", "⚠ " + f));
  if (full.source_count > 1) badges.append(el("span", "badge b-src", "on " + full.source_count + " boards"));
  if (badges.children.length) d.append(badges);

  const actions = el("div", "d-actions");
  const apply = el("button", "btn-primary", full.apply_clicked_at ? "Apply ↗ (clicked)" : "Apply ↗");
  apply.addEventListener("click", async () => {
    await api().click_apply(full.id);
    j.apply_clicked_at = new Date().toISOString();
    apply.textContent = "Apply ↗ (clicked)";
    refreshTrackers();
  });
  actions.append(apply);

  const seg = el("div", "seg");
  for (const s of ["new", "interesting", "applied", "dead"]) {
    const b = el("button", null, s);
    if (full.status === s) b.classList.add("active");
    b.addEventListener("click", () => setStatus(full.id, s));
    seg.append(b);
  }
  actions.append(seg);
  d.append(actions);

  const notes = el("textarea");
  notes.id = "d-notes";
  notes.placeholder = "notes… (autosaves)";
  notes.value = full.notes || "";
  notes.addEventListener("blur", () => api().save_note(full.id, notes.value));
  d.append(notes);

  const desc = el("div", "d-desc");
  if (full.description_html) {
    desc.innerHTML = full.description_html;   // sanitised in Python
  } else if (full.description) {
    for (const para of full.description.split(/\n{2,}/)) {
      desc.append(el("p", null, para));
    }
  } else {
    desc.append(el("p", "muted", "No description captured."));
  }
  d.append(desc);
}

async function setStatus(jobId, status) {
  await api().set_status(jobId, status);
  const j = state.jobs.find((x) => x.id === jobId);
  if (j) j.status = status;
  renderResults();
  renderDetailForSelection();
  if (status === "applied") refreshTrackers();
}

async function excludeCompany(j) {
  if (!j.company || state.trackerId == null) return;
  await api().exclude_company(state.trackerId, j.company);
  rerunSearch();
}

/* ---------- applied view ---------- */

async function openApplied() {
  state.view = "applied";
  showView();
  const data = await api().applied_page();
  const pend = $("#applied-pending");
  const done = $("#applied-done");
  pend.innerHTML = "";
  done.innerHTML = "";

  if (!data.to_confirm.length) {
    pend.append(el("div", "muted", "Nothing waiting — click Apply on a job and it lands here."));
  }
  for (const j of data.to_confirm) pend.append(appliedRow(j, true));
  if (!data.applied.length) done.append(el("div", "muted", "No confirmed applications yet."));
  for (const j of data.applied) done.append(appliedRow(j, false));
  refreshTrackers();
}

function appliedRow(j, pending) {
  const row = el("div", "applied-row");
  const main = el("div", "applied-main");
  const t = el("div", "row-title", j.title + (j.company ? " — " + j.company : ""));
  main.append(t);
  const when = pending
    ? "clicked " + timeAgo(j.apply_clicked_at) + " ago"
    : "applied " + timeAgo(j.applied_at || j.apply_clicked_at) + " ago";
  const sub = el("div", "applied-note", when + (j.notes ? "  ·  " + j.notes : ""));
  main.append(sub);
  main.addEventListener("click", () => api().open_url(j.apply_url));
  row.append(main);

  if (pending) {
    const yes = el("button", "btn-primary", "I applied");
    yes.addEventListener("click", async () => {
      await api().confirm_applied(j.id);
      openApplied();
    });
    const rm = el("button", "btn-quiet btn-danger", "Remove");
    rm.addEventListener("click", () => {
      const swap = el("span", "confirm-swap");
      swap.append(el("span", null, "Remove?"));
      const y = el("span", "yes", "yes");
      y.addEventListener("click", async () => {
        await api().remove_applied(j.id);
        openApplied();
      });
      const n = el("span", "no", "no");
      n.addEventListener("click", () => { swap.replaceWith(rm); });
      swap.append(y, n);
      rm.replaceWith(swap);
    });
    row.append(yes, rm);
  }
  return row;
}

function showView() {
  const applied = state.view === "applied";
  $("#content").hidden = applied;
  $("#topbar").style.display = applied ? "none" : "";
  $("#applied-view").hidden = !applied;
  document.querySelectorAll(".tracker-item").forEach((b) =>
    b.classList.toggle("active",
      !applied && Number(b.dataset.id) === state.trackerId));
  $("#nav-applied").classList.toggle("active", applied);
}

/* ---------- tracker modal ---------- */

const chipInputs = {};

function makeChipInput(id) {
  const wrap = $(id);
  const input = el("input");
  input.type = "text";
  wrap.append(input);
  const values = [];
  const render = () => {
    wrap.querySelectorAll(".tag").forEach((t) => t.remove());
    for (const [i, v] of values.entries()) {
      const tag = el("span", "tag");
      tag.append(el("span", null, v));
      const x = el("b", null, "×");
      x.addEventListener("click", () => { values.splice(i, 1); render(); });
      tag.append(x);
      wrap.insertBefore(tag, input);
    }
  };
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && input.value.trim()) {
      values.push(input.value.trim());
      input.value = "";
      render();
      e.preventDefault();
    } else if (e.key === "Backspace" && !input.value && values.length) {
      values.pop();
      render();
    }
  });
  wrap.addEventListener("click", () => input.focus());
  return {
    get: () => [...values],
    set: (v) => { values.length = 0; values.push(...(v || [])); render(); },
  };
}

let editingId = null;

function openModal(tracker) {
  editingId = tracker ? tracker.id : null;
  $("#modal-title").textContent = tracker ? "Edit tracker" : "New tracker";
  $("#f-name").value = tracker ? tracker.name : "";
  chipInputs.include.set(tracker?.include_terms);
  chipInputs.exclude.set(tracker?.exclude_terms);
  chipInputs.excludeCo.set(tracker?.exclude_companies);
  const win = tracker?.date_window || "14d";
  document.querySelectorAll("#f-window .chip").forEach((c) =>
    c.classList.toggle("active", c.dataset.w === win));
  $("#f-locmode").value = tracker?.location_mode || "any";
  $("#f-locvalue").value = tracker?.location_value || "";
  updateLocValue();
  $("#f-delete").hidden = !tracker;
  $("#modal-backdrop").hidden = false;
  $("#f-name").focus();
}

function updateLocValue() {
  const mode = $("#f-locmode").value;
  $("#f-locvalue-wrap").hidden = !(mode === "text" || mode === "region");
  $("#f-locvalue-label").textContent = mode === "region"
    ? "Region (georgia / caucasus / emea / global)" : "Text to match";
}

async function saveModal() {
  const win = document.querySelector("#f-window .chip.active")?.dataset.w || "14d";
  const res = await api().save_tracker({
    id: editingId,
    name: $("#f-name").value,
    include_terms: chipInputs.include.get(),
    exclude_terms: chipInputs.exclude.get(),
    exclude_companies: chipInputs.excludeCo.get(),
    date_window: win,
    location_mode: $("#f-locmode").value,
    location_value: $("#f-locvalue").value,
  });
  $("#modal-backdrop").hidden = true;
  await refreshTrackers();
  openTracker(res.id);
}

function confirmDeleteTracker(t) {
  showMenuAtCenter([
    { label: `Delete "${t.name}"? — yes`, danger: true, fn: async () => {
        await api().delete_tracker(t.id);
        if (state.trackerId === t.id) { state.trackerId = null; state.jobs = []; renderResults(); }
        refreshTrackers();
      } },
    { label: "Cancel", fn: () => {} },
  ]);
}

/* ---------- context menu ---------- */

function showMenu(e, items) { showMenuAt(e.clientX, e.clientY, items); }

function showMenuAtCenter(items) {
  showMenuAt(window.innerWidth / 2 - 90, window.innerHeight / 2 - 30, items);
}

function showMenuAt(x, y, items) {
  const m = $("#ctx-menu");
  m.innerHTML = "";
  for (const it of items) {
    if (it.sep) { m.append(el("div", "sep")); continue; }
    const mi = el("div", "mi" + (it.danger ? " danger" : ""), it.label);
    mi.addEventListener("click", () => { m.hidden = true; it.fn(); });
    m.append(mi);
  }
  m.hidden = false;
  const rect = { w: 200, h: items.length * 32 };
  m.style.left = Math.min(x, window.innerWidth - rect.w - 8) + "px";
  m.style.top = Math.min(y, window.innerHeight - rect.h - 8) + "px";
}

document.addEventListener("click", () => { $("#ctx-menu").hidden = true; });

/* ---------- keyboard ---------- */

document.addEventListener("keydown", (e) => {
  const inField = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
  if (e.key === "Escape") {
    if (!$("#modal-backdrop").hidden) { $("#modal-backdrop").hidden = true; return; }
    if (inField) { document.activeElement.blur(); }
    if (document.activeElement === $("#search") || !inField) {
      if (state.query) { $("#search").value = ""; state.query = ""; rerunSearch(); }
    }
    return;
  }
  if (inField || !$("#modal-backdrop").hidden || state.view !== "tracker") return;

  if (e.key === "/") { e.preventDefault(); $("#search").focus(); return; }
  if (e.key === "ArrowDown") { e.preventDefault(); if (state.selected < state.jobs.length - 1) selectRow(state.selected + 1); return; }
  if (e.key === "ArrowUp") { e.preventDefault(); if (state.selected > 0) selectRow(state.selected - 1); return; }

  const j = state.jobs[state.selected];
  if (!j) return;
  if (e.key === "Enter" || e.key === "o") {
    api().click_apply(j.id).then(() => { j.apply_clicked_at = new Date().toISOString(); refreshTrackers(); });
  } else if (e.key === "n") setStatus(j.id, "new");
  else if (e.key === "i") setStatus(j.id, "interesting");
  else if (e.key === "a") setStatus(j.id, "applied");
  else if (e.key === "d") setStatus(j.id, "dead");
});

/* ---------- db banner ---------- */

async function checkDb() {
  const res = await api().ping();
  const banner = $("#banner");
  if (res.ok) {
    state.dbOk = true;
    banner.hidden = true;
    return res.jobs;
  }
  state.dbOk = false;
  banner.hidden = false;
  banner.textContent = "Database unreachable — retrying every 30s. " + (res.error || "");
  return null;
}

/* ---------- boot ---------- */

async function boot() {
  const cfg = await api().get_config();
  document.documentElement.dataset.theme = cfg.theme || "dark";

  const jobs = await checkDb();
  setInterval(async () => { if (!state.dbOk) checkDb(); }, 30000);

  await refreshTrackers();

  if (jobs === 0) {
    $("#results").innerHTML = "";
    const box = el("div", "empty-state");
    box.append(el("div", "big", "The worker hasn't delivered anything yet"));
    box.append(el("div", null, "First cycle runs within the hour."));
    $("#results").append(box);
  }

  if (state.trackers.length) {
    openTracker(state.trackers[0].id);
  } else if (jobs !== 0) {
    const r = $("#results");
    r.innerHTML = "";
    const box = el("div", "empty-state");
    box.append(el("div", "big", "Create a tracker to start watching"));
    const btn = el("button", "btn-primary", "New tracker");
    btn.addEventListener("click", () => openModal(null));
    box.append(btn);
    r.append(box);
  }
}

window.addEventListener("pywebviewready", () => {
  chipInputs.include = makeChipInput("#f-include");
  chipInputs.exclude = makeChipInput("#f-exclude");
  chipInputs.excludeCo = makeChipInput("#f-exclude-co");

  $("#theme-toggle").addEventListener("click", async () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    api().set_theme(next);
  });
  $("#new-tracker").addEventListener("click", () => openModal(null));
  $("#nav-applied").addEventListener("click", openApplied);
  $("#f-cancel").addEventListener("click", () => { $("#modal-backdrop").hidden = true; });
  $("#f-save").addEventListener("click", saveModal);
  $("#f-locmode").addEventListener("change", updateLocValue);
  $("#f-window").addEventListener("click", (e) => {
    const chip = e.target.closest(".chip");
    if (!chip) return;
    document.querySelectorAll("#f-window .chip").forEach((c) =>
      c.classList.toggle("active", c === chip));
  });
  $("#f-delete").addEventListener("click", () => {
    const t = state.trackers.find((x) => x.id === editingId);
    $("#modal-backdrop").hidden = true;
    if (t) confirmDeleteTracker(t);
  });
  $("#search").addEventListener("input", (e) => {
    state.query = e.target.value;
    rerunSearch();
  });

  boot();
});
