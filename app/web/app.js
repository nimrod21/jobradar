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
  view: "tracker",          // 'tracker' | 'applied' | 'dashboard'
  windowOverride: null,     // session-only view override of the tracker's window
  query: "",
  sortByFit: false,
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
  state.selected = -1;   // nothing auto-opens; opening is what marks a job read
  renderChips(res.tracker ? res.tracker.date_window : "14d");
  renderResults();
  renderDetailForSelection();
  refreshTrackers();
  api().score_new(id).then((r) => { if (r.queued) startScorePolling(); });
}

const rerunSearch = debounce(async () => {
  if (state.view !== "tracker" || state.trackerId == null) return;
  const res = await api().search(state.trackerId, state.query, state.windowOverride || "");
  state.jobs = res.jobs;
  state.selected = -1;
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

/* ---------- fit scoring ---------- */

let scorePollTimer = null;

function startScorePolling() {
  if (scorePollTimer) return;
  const tick = async () => {
    const d = await api().score_poll();
    if (d.scored.length) applyScores(d.scored);
    if (d.active) scorePollTimer = setTimeout(tick, 2500);
    else scorePollTimer = null;
  };
  scorePollTimer = setTimeout(tick, 2000);
}

function applyScores(scored) {
  let touched = false;
  for (const s of scored) {
    const j = state.jobs.find((x) => x.id === s.job_id);
    if (j && !s.failed) {
      j.fit_score = s.score;
      j.fit_label = s.label;
      j.fit_one_liner = s.one_liner;
      touched = true;
    }
  }
  if (touched && state.view === "tracker") renderResults();
  const st = $("#p-status");
  if (state.view === "dashboard" && st) st.textContent = "Scoring… results are coming in.";
}

function fitPill(j) {
  if (j.fit_score == null) return null;
  const band = j.fit_score >= 70 ? "hi" : j.fit_score >= 40 ? "mid" : "lo";
  const pill = el("span", `badge b-fit b-fit-${band}`, String(j.fit_score));
  if (j.fit_one_liner) pill.title = j.fit_one_liner;
  return pill;
}

function renderResults() {
  const r = $("#results");
  const scroll = r.scrollTop;
  r.innerHTML = "";
  r.scrollTop = scroll;
  const newCount = state.jobs.filter((j) => j.is_new).length;
  $("#result-count").textContent = state.jobs.length
    ? `${state.jobs.length} jobs${newCount ? ` · ${newCount} new` : ""}` : "";
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
    if (j.is_new) row.classList.add("is-new");

    const title = el("div", "row-title");
    title.append(el("span", null, j.title));
    row.append(title);

    const meta = el("div", "row-meta");
    if (j.company) meta.append(el("span", "co m", j.company));
    if (j.location_raw) meta.append(el("span", "m", j.location_raw));
    meta.append(el("span", "m", timeAgo(j.posted_at) + (j.posted_at_confident ? "" : "?")));
    row.append(meta);

    const badges = el("div", "row-badges");   // always its own line, never inline
    const pill = fitPill(j);
    if (pill) badges.append(pill);
    if (j.sources?.length) badges.append(el("span", "badge b-src", srcBase(j.sources[0])));
    if (j.source_count > 1) badges.append(el("span", "badge b-src", "×" + j.source_count));
    if (j.remote_flag) badges.append(el("span", "badge b-remote", "remote"));
    for (const f of (j.geo_flags || []).slice(0, 2)) {
      badges.append(el("span", "badge b-geo", "⚠ " + f));
    }
    row.append(badges);

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

function markReadLocally(j) {
  if (!j.is_new) return;
  j.is_new = false;
  const row = document.querySelector(`#results .row[data-i="${state.jobs.indexOf(j)}"]`);
  if (row) row.classList.remove("is-new");
  const t = state.trackers.find((x) => x.id === state.trackerId);
  if (t && t.new_count > 0) {
    t.new_count -= 1;
    const badge = document.querySelector(`.tracker-item[data-id="${t.id}"] .t-count`);
    if (badge) {
      if (t.new_count === 0) badge.remove();
      else badge.textContent = t.new_count > 99 ? "99+" : String(t.new_count);
    }
  }
}

function emptyDetail(d) {
  d.innerHTML = "";
  const box = el("div", "empty-pane");
  const rings = el("div", "radar-rings");
  rings.append(el("i"), el("i"), el("i"), el("b"));
  box.append(rings);
  box.append(el("div", null, "Select a job"));
  const hints = el("div", "key-hints");
  hints.innerHTML = "<kbd>↑</kbd><kbd>↓</kbd> Move · <kbd>Enter</kbd> Apply · <kbd>n i a d</kbd> Status · <kbd>/</kbd> Search";
  box.append(hints);
  d.append(box);
}

async function renderDetailForSelection() {
  const d = $("#detail");
  const j = state.jobs[state.selected];
  if (!j) {
    emptyDetail(d);
    return;
  }
  const full = await api().get_job(j.id);   // server marks it read
  markReadLocally(j);
  if (!full || state.jobs[state.selected]?.id !== full.id) return;
  d.innerHTML = "";
  const w = el("div", "d-wrap");
  d.append(w);

  w.append(el("div", "d-title", full.title));
  if (full.company) w.append(el("div", "d-co", full.company));
  const meta = el("div", "d-meta");
  if (full.location_raw) meta.append(el("span", "m", full.location_raw));
  if (full.posted_at) meta.append(el("span", "m", "Posted " + timeAgo(full.posted_at) + " ago" + (full.posted_at_confident ? "" : " (approx)")));
  if (full.salary_raw) meta.append(el("span", "m", full.salary_raw));
  if (full.employment_type) meta.append(el("span", "m", full.employment_type));
  if (full.sources?.length) meta.append(el("span", "m", "via " + full.sources.map(srcBase).join(", ")));
  w.append(meta);

  const badges = el("div", "d-badges");
  if (full.remote_flag) badges.append(el("span", "badge b-remote", "remote"));
  for (const f of full.geo_flags || []) badges.append(el("span", "badge b-geo", "⚠ " + f));
  if (full.source_count > 1) badges.append(el("span", "badge b-src", "on " + full.source_count + " boards"));
  if (badges.children.length) w.append(badges);

  const v = full.fit_verdict;
  if (v && full.fit_score != null) {
    const fb = el("div", "fit-block");
    const head = el("div", "fit-head");
    head.append(el("span", "fit-score", String(full.fit_score)));
    head.append(el("span", "fit-label " + (v.label || ""), v.label || ""));
    if (v.one_liner) head.append(el("span", "fit-one", v.one_liner));
    fb.append(head);
    if (v.reasons_for?.length || v.reasons_against?.length) {
      const rr = el("div", "fit-reasons");
      const mk = (cls, items) => {
        const ul = el("ul", cls);
        for (const s of items || []) ul.append(el("li", null, s));
        return ul;
      };
      rr.append(mk("for", v.reasons_for), mk("against", v.reasons_against));
      fb.append(rr);
    }
    if (v.dealbreaker_hits?.length) {
      const hits = el("div", "fit-hits");
      for (const h of v.dealbreaker_hits) hits.append(el("span", "badge b-geo", "✕ " + h));
      fb.append(hits);
    }
    w.append(fb);
  }

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
    const b = el("button", null, s[0].toUpperCase() + s.slice(1));
    if (full.status === s) b.classList.add("active");
    b.addEventListener("click", () => setStatus(full.id, s));
    seg.append(b);
  }
  actions.append(seg);
  w.append(actions);

  const notes = el("textarea");
  notes.id = "d-notes";
  notes.placeholder = "Notes — autosaves";
  notes.value = full.notes || "";
  notes.addEventListener("blur", () => api().save_note(full.id, notes.value));
  w.append(notes);

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
  w.append(desc);

  api().job_emails(full.id).then((ems) => {
    if (!ems.length || state.jobs[state.selected]?.id !== full.id) return;
    const sec = el("div", "d-desc");
    sec.append(el("h3", null, "Replies"));
    for (const r of ems) sec.append(replyCard(r, false));
    w.append(sec);
  });
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
    ? "Clicked " + timeAgo(j.apply_clicked_at) + " ago"
    : "Applied " + timeAgo(j.applied_at || j.apply_clicked_at) + " ago";
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

/* ---------- dashboard ---------- */

const profileChips = {};

const _num = (sel) => Number($(sel).value.replace(/[^\d.]/g, "")) || null;

async function openProfile() {
  state.view = "profile";
  showView();
  const p = await api().get_profile();
  $("#p-key-status").textContent = p.scoring_enabled
    ? "Scoring: " + (p.model || "model set")
    : "Scoring off — set a key in Dashboard → AI Provider";
  $("#p-summary").value = p.summary || "";
  $("#p-years").value = p.years_exp ?? "";
  $("#p-title").value = p.current_title || "";
  $("#p-level").value = p.target_level || "any";
  for (const [id, key] of [["p-coding", "conf_coding"], ["p-design", "conf_design"],
                           ["p-english", "conf_english"], ["p-behavioral", "conf_behavioral"]]) {
    $("#" + id).value = p[key] || 5;
    $("#" + id + "-out").textContent = p[key] || 5;
  }
  $("#p-minsalary").value = p.min_salary ?? "";
  $("#p-salarytarget").value = p.salary_target ?? "";
  $("#p-currency").value = p.salary_currency || "USD";
  $("#p-period").value = p.salary_period || "month";
  $("#p-tz").value = p.tz_range || "";
  $("#p-notice").value = p.notice || "";
  $("#p-education").value = p.education || "";
  $("#p-citizenship").value = p.citizenship || "";
  $("#p-sponsorship").checked = !!p.needs_sponsorship;
  $("#p-contract").checked = p.contract_ok !== false;
  profileChips.targetRoles.set(p.target_roles);
  profileChips.languages.set(p.languages);
  profileChips.domAvoid.set(p.domains_avoid);
  profileChips.domLove.set(p.domains_love);
  profileChips.stackLove.set(p.stack_love);
  profileChips.stackAvoid.set(p.stack_avoid);
  $("#p-dealbreakers").value = p.dealbreakers || "";
}

async function saveProfile() {
  $("#p-status").textContent = "Saving…";
  await api().save_profile({
    summary: $("#p-summary").value,
    years_exp: _num("#p-years"),
    current_title: $("#p-title").value,
    target_level: $("#p-level").value,
    target_roles: profileChips.targetRoles.get(),
    conf_coding: Number($("#p-coding").value),
    conf_design: Number($("#p-design").value),
    conf_english: Number($("#p-english").value),
    conf_behavioral: Number($("#p-behavioral").value),
    min_salary: _num("#p-minsalary"),
    salary_target: _num("#p-salarytarget"),
    salary_currency: $("#p-currency").value,
    salary_period: $("#p-period").value,
    tz_range: $("#p-tz").value,
    notice: $("#p-notice").value,
    education: $("#p-education").value,
    citizenship: $("#p-citizenship").value,
    languages: profileChips.languages.get(),
    needs_sponsorship: $("#p-sponsorship").checked,
    contract_ok: $("#p-contract").checked,
    domains_avoid: profileChips.domAvoid.get(),
    domains_love: profileChips.domLove.get(),
    stack_love: profileChips.stackLove.get(),
    stack_avoid: profileChips.stackAvoid.get(),
    dealbreakers: $("#p-dealbreakers").value,
  });
  $("#p-status").textContent = "Saved ✓ — existing scores rescore as trackers open.";
}

async function openDashboard() {
  state.view = "dashboard";
  showView();
  renderStats(await api().dashboard_stats());
  const ai = await api().get_ai_settings();
  $("#ai-base").value = ai.api_base;
  $("#ai-model").value = ai.model;
  $("#ai-auto").checked = ai.auto;
  $("#ai-status").textContent = ai.has_key ? "key set" : "no key";
  renderEmailAccounts(await api().email_accounts());
  renderReplies(await api().replies_feed());
}

function renderEmailAccounts(accounts) {
  const box = $("#em-accounts");
  box.innerHTML = "";
  if (!accounts.length) {
    box.append(el("div", "stat-note", "No accounts attached yet."));
    return;
  }
  for (const a of accounts) {
    const row = el("div", "em-account");
    row.append(el("span", null, a.address));
    row.append(el("span", "host", a.imap_host));
    const rm = el("button", "btn-quiet btn-danger rm", "Remove");
    rm.addEventListener("click", async () => {
      await api().remove_email_account(a.address);
      renderEmailAccounts(await api().email_accounts());
    });
    row.append(rm);
    box.append(row);
  }
}

function renderReplies(feed) {
  const box = $("#em-feed");
  box.innerHTML = "";
  if (!feed.length) {
    box.append(el("div", "stat-note",
      "No matched replies yet — attach an account and press Check Now after you've applied somewhere."));
    return;
  }
  for (const r of feed) box.append(replyCard(r, true));
}

function replyCard(r, withJob) {
  const d = el("details", "em-reply");
  const s = el("summary");
  s.append(el("span", "from", r.from_addr || "?"));
  s.append(el("span", "subj", r.subject || "(no subject)"));
  if (withJob && r.title) s.append(el("span", "subj", "→ " + r.title + (r.company ? " @ " + r.company : "")));
  s.append(el("span", "when", timeAgo(r.received_at) + " ago"));
  d.append(s);
  const body = el("div", "body", r.body || r.snippet || "(empty)");
  if (r.attachments) body.append(el("div", "stat-note", `${r.attachments} attachment(s) not downloaded`));
  d.append(body);
  return d;
}

function statBlock(title, note) {
  const b = el("div", "stat-block");
  b.append(el("h3", null, title));
  if (note) b.append(el("div", "stat-note", note));
  return b;
}

function hbar(label, frac, numText) {
  const row = el("div", "hbar");
  row.append(el("div", "lbl", label));
  const track = el("div", "track");
  const fill = el("div", "fill");
  fill.style.width = Math.max(2, Math.round(frac * 100)) + "%";
  track.append(fill);
  row.append(track);
  row.append(el("div", "num", numText));
  return row;
}

function renderStats(s) {
  const cards = $("#dash-cards");
  cards.innerHTML = "";
  const t = s.totals;
  const rate = t.applied ? Math.round(100 * t.replied / t.applied) + "%" : "—";
  for (const [v, k] of [[t.total, "jobs tracked"], [t.new_week, "new this week"],
                        [t.applied, "applied"], [t.replied, "replied"],
                        [rate, "response rate"]]) {
    const c = el("div", "card");
    c.append(el("div", "v", String(v)));
    c.append(el("div", "k", k));
    cards.append(c);
  }

  const box = $("#dash-stats");
  box.innerHTML = "";

  const funnel = statBlock("Funnel");
  const steps = [["Clicked apply", t.clicked], ["Confirmed applied", t.applied],
                 ["Got a reply", t.replied], ["Rejected", t.rejected]];
  const max = Math.max(1, t.clicked);
  let prev = null;
  for (const [lbl, n] of steps) {
    const pct = prev ? ` (${Math.round(100 * n / Math.max(1, prev))}%)` : "";
    funnel.append(hbar(lbl, n / max, n + pct));
    prev = n;
  }
  box.append(funnel);

  if (s.by_source.length) {
    const bs = statBlock("Response Rate by Source", "sources with 3+ confirmed applications");
    for (const r of s.by_source) {
      bs.append(hbar(r.source, r.apps ? r.replies / r.apps : 0,
                     `${r.replies}/${r.apps}`));
    }
    box.append(bs);
  }

  const fr = statBlock("Freshness at Apply");
  fr.append(el("div", null, s.freshness_hours == null
    ? "No applications with confident dates yet."
    : `Median job age when you clicked Apply: ${s.freshness_hours < 48
        ? s.freshness_hours + " hours" : Math.round(s.freshness_hours / 24) + " days"}.`));
  box.append(fr);

  if (s.per_week.length) {
    const pw = statBlock("Applications per Week");
    const bars = el("div", "vbars");
    const labels = el("div", "vbars-x");
    const mx = Math.max(...s.per_week.map((w) => w.n), 1);
    for (const w of s.per_week) {
      const vb = el("div", "vb");
      vb.style.height = Math.round(100 * w.n / mx) + "%";
      vb.title = `${w.wk}: ${w.n}`;
      bars.append(vb);
      labels.append(el("span", null, w.wk));
    }
    pw.append(bars, labels);
    box.append(pw);
  }

  if (s.pulse.length) {
    const pu = statBlock("Market Pulse", "jobs per day matching each tracker, last 14 days");
    const today = Date.now();
    for (const p of s.pulse) {
      const row = el("div", "pulse-row");
      row.append(el("div", "lbl", p.name));
      const bars = el("div", "vbars");
      const counts = [];
      for (let i = 13; i >= 0; i--) {
        const d = new Date(today - i * 86400000).toISOString().slice(0, 10);
        counts.push(p.days[d] || 0);
      }
      const mx = Math.max(...counts, 1);
      for (const n of counts) {
        const vb = el("div", "vb");
        vb.style.height = Math.max(4, Math.round(100 * n / mx)) + "%";
        if (!n) vb.style.opacity = ".15";
        bars.append(vb);
      }
      row.append(bars);
      row.append(el("div", "num", String(p.total)));
      pu.append(row);
    }
    box.append(pu);
  }

  if (s.fit && s.fit.scored > 0) {
    const fc = statBlock("Fit Calibration");
    const a = s.fit.avg_applied, sk = s.fit.avg_skipped;
    fc.append(el("div", null,
      `Average fit of jobs you applied to: ${a ?? "—"} · everything else: ${sk ?? "—"}` +
      (a != null && sk != null && a < sk ? "  — you're applying below your best matches." : "")));
    box.append(fc);
  }
}

function showView() {
  const v = state.view;
  $("#content").hidden = v !== "tracker";
  $("#topbar").style.display = v === "tracker" ? "" : "none";
  $("#applied-view").hidden = v !== "applied";
  $("#dashboard-view").hidden = v !== "dashboard";
  $("#profile-view").hidden = v !== "profile";
  document.querySelectorAll("#tracker-list .tracker-item").forEach((b) =>
    b.classList.toggle("active",
      v === "tracker" && Number(b.dataset.id) === state.trackerId));
  $("#nav-applied").classList.toggle("active", v === "applied");
  $("#nav-dashboard").classList.toggle("active", v === "dashboard");
  $("#nav-profile").classList.toggle("active", v === "profile");
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
  const commit = () => {
    const parts = input.value.split(",").map((s) => s.trim()).filter(Boolean);
    if (parts.length) { values.push(...parts); render(); }
    input.value = "";
  };
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      commit();
      e.preventDefault();
    } else if (e.key === "Backspace" && !input.value && values.length) {
      values.pop();
      render();
    }
  });
  input.addEventListener("input", () => {           // typed or pasted commas split immediately
    if (input.value.includes(",")) commit();
  });
  input.addEventListener("blur", commit);           // stragglers aren't lost on Save
  wrap.addEventListener("click", () => input.focus());
  return {
    get: () => [...values],
    set: (v) => { values.length = 0; values.push(...(v || [])); render(); },
  };
}

let editingId = null;

function openModal(tracker) {
  editingId = tracker ? tracker.id : null;
  $("#modal-title").textContent = tracker ? "Edit Tracker" : "New Tracker";
  $("#f-name").value = tracker ? tracker.name : "";
  chipInputs.include.set(tracker?.include_terms);
  chipInputs.exclude.set(tracker?.exclude_terms);
  chipInputs.excludeCo.set(tracker?.exclude_companies);
  const win = tracker?.date_window || "14d";
  document.querySelectorAll("#f-window .chip").forEach((c) =>
    c.classList.toggle("active", c.dataset.w === win));
  $("#f-locmode").value = tracker?.location_mode || "any";
  const lv = tracker?.location_value || "";
  $("#f-locvalue").value = tracker?.location_mode === "region" ? "" : lv;
  const regionKeys = [...document.querySelectorAll("#f-locregion option")].map((o) => o.value);
  $("#f-locregion").value = regionKeys.includes(lv) ? lv : "emea";
  const wm = tracker?.work_modes || [];
  document.querySelectorAll("#f-workmodes .chip").forEach((c) =>
    c.classList.toggle("active", wm.includes(c.dataset.m)));
  const scope = tracker?.search_in || "both";
  document.querySelectorAll("#f-searchin .chip").forEach((c) =>
    c.classList.toggle("active", c.dataset.s === scope));
  updateLocValue();
  $("#f-delete").hidden = !tracker;
  $("#modal-backdrop").hidden = false;
  $("#f-name").focus();
}

function updateLocValue() {
  const mode = $("#f-locmode").value;
  $("#f-locvalue-wrap").hidden = mode === "any";
  $("#f-locregion").hidden = mode !== "region";
  $("#f-locvalue").hidden = !(mode === "country" || mode === "place");
  $("#f-locvalue-hint").hidden = mode !== "place";
  if (mode === "region") $("#f-locvalue-label").textContent = "Region";
  if (mode === "country") {
    $("#f-locvalue-label").textContent = "Country";
    $("#f-locvalue").placeholder = "e.g. Georgia, Germany, Japan";
  }
  if (mode === "place") {
    $("#f-locvalue-label").textContent = "City or Keyword";
    $("#f-locvalue").placeholder = "e.g. Tbilisi, Berlin, CET";
  }
}

function workModes() {
  return [...document.querySelectorAll("#f-workmodes .chip.active")].map((c) => c.dataset.m);
}

async function saveModal() {
  const win = document.querySelector("#f-window .chip.active")?.dataset.w || "14d";
  const mode = $("#f-locmode").value;
  const res = await api().save_tracker({
    id: editingId,
    name: $("#f-name").value,
    include_terms: chipInputs.include.get(),
    exclude_terms: chipInputs.exclude.get(),
    exclude_companies: chipInputs.excludeCo.get(),
    date_window: win,
    search_in: document.querySelector("#f-searchin .chip.active")?.dataset.s || "both",
    work_modes: workModes(),
    location_mode: mode,
    location_value: mode === "region" ? $("#f-locregion").value : $("#f-locvalue").value,
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
  $("#nav-dashboard").addEventListener("click", openDashboard);
  $("#nav-profile").addEventListener("click", openProfile);

  document.querySelectorAll(".tabs .tab").forEach((t) =>
    t.addEventListener("click", () => {
      document.querySelectorAll(".tabs .tab").forEach((x) =>
        x.classList.toggle("active", x === t));
      $("#tab-stats").hidden = t.dataset.tab !== "stats";
      $("#tab-email").hidden = t.dataset.tab !== "email";
    }));

  profileChips.targetRoles = makeChipInput("#p-target-roles");
  profileChips.languages = makeChipInput("#p-languages");
  profileChips.domAvoid = makeChipInput("#p-domains-avoid");
  profileChips.domLove = makeChipInput("#p-domains-love");
  profileChips.stackLove = makeChipInput("#p-stack-love");
  profileChips.stackAvoid = makeChipInput("#p-stack-avoid");
  for (const id of ["p-coding", "p-design", "p-english", "p-behavioral"]) {
    $("#" + id).addEventListener("input", (e) => {
      $("#" + id + "-out").textContent = e.target.value;
    });
  }
  $("#p-save").addEventListener("click", saveProfile);

  $("#ai-save").addEventListener("click", async () => {
    const r = await api().save_ai_settings({
      api_base: $("#ai-base").value,
      api_key: $("#ai-key").value,
      model: $("#ai-model").value,
      auto: $("#ai-auto").checked,
    });
    $("#ai-key").value = "";
    $("#ai-status").textContent = "Saved ✓ " + (r.has_key ? "· key set" : "· no key");
  });
  $("#ai-test").addEventListener("click", async () => {
    $("#ai-status").textContent = "Testing…";
    const r = await api().test_ai();
    $("#ai-status").textContent = r.ok ? `✓ ${r.model} responds` : "✕ " + r.error;
  });

  $("#em-host").addEventListener("change", () => {
    $("#em-customhost-wrap").hidden = $("#em-host").value !== "custom";
  });
  $("#em-add").addEventListener("click", async () => {
    $("#em-status").textContent = "Verifying login…";
    const host = $("#em-host").value === "custom"
      ? $("#em-customhost").value : $("#em-host").value;
    const r = await api().add_email_account(
      $("#em-address").value, $("#em-password").value, host);
    $("#em-status").textContent = r.ok ? "Attached ✓" : "✕ " + r.error;
    if (r.ok) {
      $("#em-address").value = "";
      $("#em-password").value = "";
      renderEmailAccounts(await api().email_accounts());
    }
  });
  $("#em-check").addEventListener("click", async () => {
    $("#em-status").textContent = "Checking inbox(es)…";
    const r = await api().check_email_now();
    $("#em-status").textContent = r.ok
      ? `Found ${r.found} new repl${r.found === 1 ? "y" : "ies"}` +
        (r.errors?.length ? ` · errors: ${r.errors.join("; ")}` : "")
      : "✕ " + r.error;
    renderReplies(await api().replies_feed());
    refreshTrackers();
  });
  $("#p-score-all").addEventListener("click", async () => {
    const r = await api().score_all_unscored();
    $("#p-status").textContent = r.queued
      ? `Queued ${r.queued} jobs for scoring…`
      : "Nothing unscored (or no key configured).";
    if (r.queued) startScorePolling();
  });

  $("#fit-sort").addEventListener("click", () => {
    state.sortByFit = !state.sortByFit;
    $("#fit-sort").classList.toggle("active", state.sortByFit);
    if (state.sortByFit) {
      state.jobs.sort((a, b) => (b.fit_score ?? -1) - (a.fit_score ?? -1));
      state.selected = -1;
      renderResults();
      renderDetailForSelection();
    } else {
      rerunSearch();
    }
  });
  $("#f-cancel").addEventListener("click", () => { $("#modal-backdrop").hidden = true; });
  $("#f-save").addEventListener("click", saveModal);
  $("#f-locmode").addEventListener("change", updateLocValue);
  $("#f-window").addEventListener("click", (e) => {
    const chip = e.target.closest(".chip");
    if (!chip) return;
    document.querySelectorAll("#f-window .chip").forEach((c) =>
      c.classList.toggle("active", c === chip));
  });
  $("#f-workmodes").addEventListener("click", (e) => {
    const chip = e.target.closest(".chip");
    if (chip) chip.classList.toggle("active");   // multi-select toggles
  });
  $("#f-searchin").addEventListener("click", (e) => {
    const chip = e.target.closest(".chip");
    if (!chip) return;
    document.querySelectorAll("#f-searchin .chip").forEach((c) =>
      c.classList.toggle("active", c === chip));   // single-select
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
