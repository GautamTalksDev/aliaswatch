/* AliasWatch front end.
 *
 * Zero dependencies. Everything here is plain DOM, SVG and WebCrypto. That is
 * deliberate: this site's only asset is that people believe the numbers, and
 * every third-party script is code the reader has to trust and I cannot audit.
 * It also means the page ships under a strict CSP with no 'unsafe-inline'.
 *
 * All data comes from data.json, generated from the archived results. Nothing
 * on this page is computed from anything except that file.
 */

"use strict";

const FAMILIES = [
  "ground_truth", "format_compliance", "constraint_adherence",
  "refusal_rate", "tool_call", "verbosity",
];

const STATUS_TEXT = {
  stable: "no significant change",
  watch: "excursion, unconfirmed",
  changed: "changed",
  baselining: "collecting baseline",
};

const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

let DATA = null;
let familyFilter = null;   // null = all families

/* ---------------------------------------------------------------- utils */

const $ = (sel, root = document) => root.querySelector(sel);
const el = (tag, attrs = {}, ...kids) => {
  const n = document.createElementNS(
    attrs.__svg ? "http://www.w3.org/2000/svg" : "http://www.w3.org/1999/xhtml", tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "__svg" || v === null || v === undefined) continue;
    if (k === "text") n.textContent = v;
    else n.setAttribute(k, v);
  }
  for (const kid of kids) if (kid) n.appendChild(kid);
  return n;
};
const svg = (tag, attrs = {}, ...kids) => el(tag, { ...attrs, __svg: true }, ...kids);

function statusColour(status) {
  if (status === "changed") return "var(--changed)";
  if (status === "watch") return "var(--watch)";
  if (status === "baselining") return "var(--rule)";
  return "var(--trace)";
}

/* Deviation for a day, respecting the active family filter. Filtering by
 * family is not cosmetic: it re-derives the trace from that family's own
 * z-score, so a reader can see whether a change was concentrated. */
function dayZ(day) {
  if (!familyFilter) return day.z || 0;
  const f = (day.families || {})[familyFilter];
  return f ? Math.abs(f.z || 0) : 0;
}
function dayStatus(day) {
  if (!familyFilter) return day.status;
  if (day.status === "baselining") return "baselining";
  return (day.flagged || []).includes(familyFilter) ? day.status : "stable";
}

/* ------------------------------------------------------------- the trace */

function buildTrace(days, opts = {}) {
  const w = opts.w || 1000, h = opts.h || 46;
  const mid = h / 2;
  const node = svg("svg", {
    viewBox: `0 0 ${w} ${h}`, preserveAspectRatio: "none",
    height: h, role: "img",
    "aria-label": `Daily record, ${days.length} days. Use arrow keys to step through days.`,
    tabindex: "0", class: "trace",
  });

  node.appendChild(svg("line", {
    x1: 0, y1: mid, x2: w, y2: mid,
    stroke: "var(--rule)", "stroke-width": 1,
  }));

  const step = w / Math.max(days.length, 1);
  const ticks = [];

  days.forEach((d, i) => {
    const x = i * step + step / 2;
    const st = dayStatus(d);
    const z = Math.min(Math.abs(dayZ(d)), 4);
    const amp = Math.max((z / 4) * (mid - 4), 1.2);
    const strong = st === "changed" || st === "watch";

    const line = svg("line", {
      x1: x, y1: mid - amp, x2: x, y2: mid + amp,
      stroke: statusColour(st),
      "stroke-width": strong ? 2.6 : 1.5,
      "stroke-linecap": "round",
      opacity: st === "baselining" ? .35 : (strong ? 1 : .8),
    });
    line.dataset.i = String(i);
    node.appendChild(line);
    ticks.push(line);

    /* Invisible wide hit area: 1.5px lines are not a usable pointer target. */
    const hit = svg("rect", {
      x: i * step, y: 0, width: step, height: h,
      fill: "transparent",
    });
    hit.dataset.i = String(i);
    node.appendChild(hit);
  });

  /* Draw-in animation: the traces sweep left to right once on load. One
   * orchestrated moment, not an effect on every element. */
  if (!reduceMotion && opts.animate) {
    ticks.forEach((t, i) => {
      t.style.opacity = "0";
      t.style.transition = "opacity .28s ease";
      setTimeout(() => { t.style.opacity = ""; },
        Math.min(i * (420 / Math.max(ticks.length, 1)), 700));
    });
  }

  node.__days = days;
  return node;
}

/* ------------------------------------------------------------ tooltip */

const tip = el("div", { class: "tip", role: "status", "aria-live": "polite" });

function showTip(day, model, clientX, clientY) {
  tip.textContent = "";
  tip.appendChild(el("span", { class: "td", text: `${day.date} · ${model}` }));

  const st = dayStatus(day);
  tip.appendChild(el("div", {
    text: STATUS_TEXT[st] + (day.incomplete ? " (gap: incomplete run)" : ""),
  }));

  if (day.families) {
    const flagged = day.flagged || [];
    for (const f of FAMILIES) {
      const v = day.families[f];
      if (!v) continue;
      if (familyFilter && f !== familyFilter) continue;
      const isFlag = flagged.includes(f);
      const txt = f === "verbosity"
        ? `verbosity · median ${Math.round(v.value)} words`
        : `${f.replace(/_/g, " ")} · ${v.fails}/${v.n} failing`;
      tip.appendChild(el("div", { class: isFlag ? "tf" : "", text: txt }));
    }
  }

  tip.classList.add("show");
  const r = tip.getBoundingClientRect();
  const x = Math.min(clientX + 14, window.innerWidth - r.width - 10);
  const y = Math.max(clientY - r.height - 12, 8);
  tip.style.left = x + "px";
  tip.style.top = y + "px";
}
function hideTip() { tip.classList.remove("show"); }

function wireTrace(node, modelLabel) {
  const days = node.__days;
  let idx = -1;

  const at = (i, ev) => {
    if (i < 0 || i >= days.length) return;
    idx = i;
    const rect = node.getBoundingClientRect();
    const x = ev ? ev.clientX : rect.left + (rect.width * (i + .5)) / days.length;
    const y = ev ? ev.clientY : rect.top;
    showTip(days[i], modelLabel, x, y);
  };

  node.addEventListener("pointermove", (e) => {
    const t = e.target;
    if (t.dataset && t.dataset.i !== undefined) at(Number(t.dataset.i), e);
  });
  node.addEventListener("pointerleave", hideTip);
  node.addEventListener("blur", hideTip);
  node.addEventListener("focus", () => at(days.length - 1));
  node.addEventListener("keydown", (e) => {
    if (e.key === "ArrowRight") { e.preventDefault(); at(Math.min(idx + 1, days.length - 1)); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); at(Math.max(idx - 1, 0)); }
    else if (e.key === "Home") { e.preventDefault(); at(0); }
    else if (e.key === "End") { e.preventDefault(); at(days.length - 1); }
    else if (e.key === "Escape") { hideTip(); }
  });
}

/* --------------------------------------------------------- sparklines */

function sparkline(series, flagged) {
  const w = 200, h = 26;
  const node = svg("svg", {
    viewBox: `0 0 ${w} ${h}`, preserveAspectRatio: "none",
    class: "spark", "aria-hidden": "true",
  });
  const vals = series.filter((v) => v !== null && v !== undefined);
  if (!vals.length) return node;
  const max = Math.max(...vals, 1), min = Math.min(...vals, 0);
  const span = Math.max(max - min, 1e-6);
  const pts = series.map((v, i) => {
    const x = (i / Math.max(series.length - 1, 1)) * w;
    const y = h - 2 - ((v - min) / span) * (h - 4);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  node.appendChild(svg("polyline", {
    points: pts, fill: "none",
    stroke: flagged ? "var(--changed)" : "var(--trace)",
    "stroke-width": 1.4, "stroke-linejoin": "round",
  }));
  return node;
}

/* ------------------------------------------------------- model rows */

function verdictNode(m) {
  const days = m.days;
  const last = days[days.length - 1] || {};
  const st = dayStatus(last);
  const box = el("div", { class: "verdict" });
  box.appendChild(el("span", { class: "dot s-" + st }));

  if (st === "stable") {
    let run = 0;
    for (let i = days.length - 1; i >= 0; i--) {
      if (dayStatus(days[i]) === "stable") run++; else break;
    }
    box.appendChild(el("span", { text: STATUS_TEXT.stable + " " }));
    box.appendChild(el("span", { class: "n", text: `(day ${run})` }));
  } else if (st === "changed") {
    box.appendChild(el("span", {
      class: "v-changed",
      text: "changed " + (last.date === DATA.last_run ? "today" : "on " + last.date),
    }));
  } else if (st === "watch") {
    box.appendChild(el("span", { class: "v-watch", text: STATUS_TEXT.watch }));
  } else {
    box.appendChild(el("span", { text: STATUS_TEXT.baselining }));
  }
  box.appendChild(el("span", { class: "chev", text: "›", "aria-hidden": "true" }));
  return box;
}

function detailPanel(m) {
  const inner = el("div", { class: "detailinner" });
  const last = m.days[m.days.length - 1] || {};
  const flagged = last.flagged || [];

  inner.appendChild(el("p", {
    class: "sub",
    text: last.note || "Per-family results for " + (last.date || "the latest run") +
      ". The trailing line is that family over the last 30 days.",
  }));

  const grid = el("div", { class: "famgrid" });
  for (const f of FAMILIES) {
    const v = (last.families || {})[f];
    if (!v) continue;
    const isFlag = flagged.includes(f);
    const cell = el("div", { class: "fam" + (isFlag ? " flagged" : "") });
    cell.appendChild(el("div", { class: "fname", text: f.replace(/_/g, " ") }));

    if (f === "verbosity") {
      cell.appendChild(el("span", { class: "fnum", text: Math.round(v.value) + "w" }));
      cell.appendChild(el("span", {
        class: "fbase",
        text: v.baseline ? `median words · baseline ${Math.round(v.baseline)}` : "median words",
      }));
    } else {
      cell.appendChild(el("span", { class: "fnum", text: `${v.fails}/${v.n}` }));
      cell.appendChild(el("span", {
        class: "fbase",
        text: v.baseline !== null && v.baseline !== undefined
          ? `failing · floor ${(v.baseline * 100).toFixed(1)}%`
          : "failing · baselining",
      }));
    }

    const series = m.days.slice(-30).map((d) => {
      const dv = (d.families || {})[f];
      if (!dv) return null;
      return f === "verbosity" ? dv.value : dv.fails;
    });
    cell.appendChild(sparkline(series, isFlag));
    grid.appendChild(cell);
  }
  inner.appendChild(grid);

  const link = el("p", {}, );
  const a = el("a", {
    href: `${DATA.repo}/tree/main/results/${last.date || ""}`,
    rel: "noopener noreferrer",
    text: "Raw responses and per-item grades for this day",
  });
  link.appendChild(a);
  link.appendChild(el("span", { text: " — re-running the published graders over them reproduces these numbers exactly." }));
  inner.appendChild(link);

  const panel = el("div", { class: "detail", hidden: "" });
  panel.appendChild(inner);
  return panel;
}

function modelRow(m, i) {
  const wrap = el("div", { class: "model" });
  const btn = el("button", {
    class: "modelhead", type: "button",
    "aria-expanded": "false", id: "mh-" + m.key,
    "aria-controls": "md-" + m.key,
  });

  const namecell = el("div");
  namecell.appendChild(el("span", { class: "name", text: m.label }));
  namecell.appendChild(el("span", { class: "alias", text: m.alias }));
  btn.appendChild(namecell);

  const tcell = el("div", { class: "tracecell" });
  const trace = buildTrace(m.days, { animate: true });
  tcell.appendChild(trace);
  btn.appendChild(tcell);

  btn.appendChild(verdictNode(m));
  wrap.appendChild(btn);

  const panel = detailPanel(m);
  panel.id = "md-" + m.key;
  panel.setAttribute("role", "region");
  panel.setAttribute("aria-labelledby", "mh-" + m.key);
  wrap.appendChild(panel);

  btn.addEventListener("click", () => {
    const open = btn.getAttribute("aria-expanded") === "true";
    btn.setAttribute("aria-expanded", String(!open));
    if (open) {
      panel.style.height = panel.scrollHeight + "px";
      requestAnimationFrame(() => { panel.style.height = "0px"; });
      setTimeout(() => { panel.hidden = true; }, reduceMotion ? 0 : 220);
    } else {
      panel.hidden = false;
      const target = panel.scrollHeight;
      panel.style.height = "0px";
      requestAnimationFrame(() => { panel.style.height = target + "px"; });
      setTimeout(() => { panel.style.height = "auto"; }, reduceMotion ? 0 : 240);
    }
  });

  /* The trace lives inside a button. Its arrow-key handling must not be
     swallowed by the button, but clicks must still reach the button — the
     trace is the widest part of the row and dead pointer area there reads as
     a broken control. */
  trace.addEventListener("keydown", (e) => {
    if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) e.stopPropagation();
  });
  wireTrace(trace, m.label);

  return wrap;
}

/* ------------------------------------------------------------ filters */

function buildControls() {
  const box = $("#controls");
  box.textContent = "";
  box.appendChild(el("span", { class: "lbl", text: "Show" }));

  const mk = (label, value) => {
    const b = el("button", {
      class: "chip", type: "button",
      "aria-pressed": String(familyFilter === value),
      text: label,
    });
    b.addEventListener("click", () => {
      familyFilter = familyFilter === value ? null : value;
      render();
    });
    return b;
  };

  box.appendChild(mk("all families", null));
  for (const f of FAMILIES) box.appendChild(mk(f.replace(/_/g, " "), f));
}

/* ------------------------------------- client-side chain verification */

async function sha256Hex(bytes) {
  const d = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/* Canonical JSON must match the Python side byte for byte, or every head
   recomputes wrong. Keys sorted, no spaces, no non-ASCII escaping. */
function canonical(obj) {
  if (obj === null || typeof obj !== "object") return JSON.stringify(obj);
  if (Array.isArray(obj)) return "[" + obj.map(canonical).join(",") + "]";
  const keys = Object.keys(obj).sort();
  return "{" + keys.map((k) => JSON.stringify(k) + ":" + canonical(obj[k])).join(",") + "}";
}

async function verifyChain(entries) {
  const problems = [];
  let prev = "0".repeat(64);
  const enc = new TextEncoder();

  for (let i = 0; i < entries.length; i++) {
    const e = entries[i];
    if (e.index !== i) problems.push(`${e.date}: index out of order`);
    if (e.prev_head !== prev) problems.push(`${e.date}: chain break`);
    const body = {
      date: e.date, files: e.files, day_digest: e.day_digest,
      prev_head: e.prev_head, index: e.index,
    };
    const head = await sha256Hex(enc.encode(canonical(body)));
    if (head !== e.head) problems.push(`${e.date}: head does not match its contents`);
    prev = e.head;
  }
  return problems;
}

function wireVerifier() {
  const btn = $("#vgo"), out = $("#vout"), input = $("#vhead");
  if (!btn) return;

  btn.addEventListener("click", async () => {
    out.className = "vout";
    out.textContent = "Recomputing the chain in your browser…";
    let entries;
    try {
      const r = await fetch("log.json", { cache: "no-store" });
      if (!r.ok) throw new Error("log.json " + r.status);
      entries = await r.json();
    } catch (err) {
      out.className = "vout bad";
      out.textContent = "Could not load log.json: " + err.message;
      return;
    }

    const problems = await verifyChain(entries);
    const claimed = (input.value || "").trim().toLowerCase();
    const lines = [];

    lines.push(`${entries.length} days in the log.`);
    if (problems.length === 0) {
      lines.push("Chain intact: every day's hash matches its contents and links to the day before.");
    } else {
      lines.push("PROBLEMS:");
      for (const p of problems) lines.push("  - " + p);
    }

    if (claimed) {
      const match = entries.find((e) => e.head.toLowerCase() === claimed);
      lines.push("");
      lines.push(match
        ? `Your head is day ${match.date} (index ${match.index}). It is in this chain.`
        : "Your head is NOT in this chain. If you saved it from this site earlier, the record has been rewritten.");
      if (!match) problems.push("unknown head");
    }

    lines.push("");
    lines.push("This check recomputes hashes only. Signature verification needs the");
    lines.push("published key — see the Verify page for the offline command.");

    out.className = "vout " + (problems.length ? "bad" : "ok");
    out.textContent = lines.join("\n");
  });
}

/* ---------------------------------------------------------- rendering */

function render() {
  const strip = $("#strip");
  strip.textContent = "";
  if (!DATA || !DATA.models || !DATA.models.length) return;
  DATA.models.forEach((m, i) => strip.appendChild(modelRow(m, i)));
  buildControls();

  const note = $("#striprange");
  if (note && DATA.models[0].days.length) {
    const d = DATA.models[0].days;
    note.textContent = `Each strip runs ${d[0].date} → ${d[d.length - 1].date}, one tick per day.`
      + (familyFilter ? ` Showing ${familyFilter.replace(/_/g, " ")} only.` : "");
  }
}

/* ------------------------------------------------------------- theme */

function wireTheme() {
  const btn = $("#theme");
  if (!btn) return;
  const stored = (() => { try { return localStorage.getItem("aw-theme"); } catch { return null; } })();
  if (stored) document.documentElement.dataset.theme = stored;
  const label = () => {
    const t = document.documentElement.dataset.theme;
    btn.textContent = t === "dark" ? "light" : t === "light" ? "auto" : "dark";
  };
  label();
  btn.addEventListener("click", () => {
    const t = document.documentElement.dataset.theme;
    const next = t === "dark" ? "light" : t === "light" ? "" : "dark";
    if (next) document.documentElement.dataset.theme = next;
    else delete document.documentElement.dataset.theme;
    try { next ? localStorage.setItem("aw-theme", next) : localStorage.removeItem("aw-theme"); } catch { /* ignore */ }
    label();
  });
}

/* -------------------------------------------------------------- boot */

async function boot() {
  document.body.appendChild(tip);
  wireTheme();
  wireVerifier();

  try {
    const r = await fetch("data.json", { cache: "no-store" });
    if (!r.ok) throw new Error("data.json " + r.status);
    DATA = await r.json();
  } catch (err) {
    $("#strip").appendChild(el("div", {
      class: "empty",
      text: "Could not load the record (" + err.message + "). Nothing on this page is estimated, so no numbers are shown.",
    }));
    return;
  }

  if (!DATA.models || !DATA.models.length) {
    $("#strip").appendChild(el("div", {
      class: "empty",
      text: "The record starts when the first run completes. No days are estimated or filled in.",
    }));
    return;
  }

  const lr = $("#lastrun");
  if (lr) lr.textContent = DATA.last_run || "—";
  const bs = $("#batteryseal");
  if (bs) bs.textContent = (DATA.battery_sha256 || "").slice(0, 16) + "…";

  render();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot);
} else {
  boot();
}
