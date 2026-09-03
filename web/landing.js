/* Landing page. Zero dependencies; renders under the same strict CSP.
 *
 * The replay runs the actual detection logic - a faithful port of
 * stats.py's rolling baseline, binomial test, BH correction and 2-of-3
 * confirmation - over locally simulated days. It is not a cartoon of
 * detection; it is detection, on a seeded fixture, so what the visitor
 * watches is what the record does.
 */

"use strict";

const NS = "http://www.w3.org/2000/svg";
const $ = (s, r = document) => r.querySelector(s);
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const sv = (tag, attrs = {}) => {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  return n;
};

/* ------------------------------------------------------------ theme */
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

/* --------------------------------------------- statistics (port of stats.py) */

const MIN_BASELINE_DAYS = 7, BASELINE_WINDOW = 28, FDR_Q = 0.05;

function lgamma(x) {
  // Lanczos approximation; ample for binomial tails at n=30.
  const g = 7, c = [0.99999999999980993, 676.5203681218851, -1259.1392167224028,
    771.32342877765313, -176.61502916214059, 12.507343278686905,
    -0.13857109526572012, 9.9843695780195716e-6, 1.5056327351493116e-7];
  if (x < 0.5) return Math.log(Math.PI / Math.sin(Math.PI * x)) - lgamma(1 - x);
  x -= 1;
  let a = c[0];
  const t = x + g + 0.5;
  for (let i = 1; i < g + 2; i++) a += c[i] / (x + i);
  return 0.5 * Math.log(2 * Math.PI) + (x + 0.5) * Math.log(t) - t + Math.log(a);
}
const logChoose = (n, k) => lgamma(n + 1) - lgamma(k + 1) - lgamma(n - k + 1);

function binomSf(k, n, p) {
  if (k <= 0) return 1;
  if (k > n) return 0;
  p = Math.min(Math.max(p, 1e-9), 1 - 1e-9);
  let t = 0;
  for (let i = k; i <= n; i++) t += Math.exp(logChoose(n, i) + i * Math.log(p) + (n - i) * Math.log(1 - p));
  return Math.min(1, t);
}
function binomTwoSided(k, n, p) {
  if (!n) return 1;
  const mean = n * p;
  const tail = k >= mean ? binomSf(k, n, p) : 1 - binomSf(k + 1, n, p);
  return Math.min(1, 2 * tail);
}
function bh(pvals, q = FDR_Q) {
  const m = pvals.length, order = pvals.map((p, i) => i).sort((a, b) => pvals[a] - pvals[b]);
  let cutoff = -1;
  order.forEach((idx, r) => { if (pvals[idx] <= q * (r + 1) / m) cutoff = r + 1; });
  const keep = new Array(m).fill(false);
  order.forEach((idx, r) => { if (r + 1 <= cutoff) keep[idx] = true; });
  return keep;
}

function baseline(history, fam, exclude) {
  const usable = history.filter((h) => !exclude.has(h.date)).slice(-BASELINE_WINDOW);
  let fails = 0, total = 0, days = 0;
  for (const h of usable) {
    const f = h.fam[fam];
    if (!f) continue;
    fails += f.fails; total += f.n; days++;
  }
  if (days < MIN_BASELINE_DAYS || !total) return [null, days];
  return [fails / total, days];
}

function evaluate(today, history, flagged, recent) {
  const fams = Object.keys(today.fam).sort();
  const res = [], pv = [], testable = [];
  for (const f of fams) {
    const { n, fails } = today.fam[f];
    const [base, days] = baseline(history, f, flagged);
    if (base === null) { res.push({ f, base: null, exc: false }); continue; }
    const p = binomTwoSided(fails, n, base);
    res.push({ f, base, p, exc: false, z: Math.abs(fails / n - base) / Math.max(Math.sqrt(base * (1 - base) / n), 1e-6) });
    pv.push(p); testable.push(res.length - 1);
  }
  if (!testable.length) return { status: "baselining", flagged: [], z: 0 };
  const keep = bh(pv);
  testable.forEach((slot, i) => { res[slot].exc = keep[i]; });
  const fl = res.filter((r) => r.exc).map((r) => r.f);
  const z = Math.max(0, ...res.filter((r) => r.z !== undefined).map((r) => r.z));
  const rec = recent.slice(-2);
  let status = "stable";
  if (fl.length) status = rec.some(Boolean) ? "changed" : "watch";
  return { status, flagged: fl, z };
}

/* ------------------------------------------------------ seeded fixture */

function mulberry32(a) {
  return () => {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const FAMS = { ground_truth: [30, .03], format_compliance: [30, .12],
  constraint_adherence: [30, .38], refusal_rate: [30, .06], tool_call: [30, .10] };

function simulateDays(seed, days, injectOn, injectFam, injectRate) {
  const rng = mulberry32(seed);
  const out = [];
  for (let d = 0; d < days; d++) {
    const fam = {};
    for (const [f, [n, p]] of Object.entries(FAMS)) {
      const eff = (injectOn >= 0 && d >= injectOn && f === injectFam) ? injectRate : p;
      let fails = 0;
      for (let i = 0; i < n; i++) if (rng() < eff) fails++;
      fam[f] = { n, fails };
    }
    out.push({ date: `day ${d + 1}`, fam });
  }
  return out;
}

/* ------------------------------------------------------- drawing traces */

function colour(st) {
  return st === "changed" ? "var(--changed)" : st === "watch" ? "var(--watch)"
    : st === "baselining" ? "var(--rule)" : "var(--trace)";
}

function drawTrace(svg, days, w, h) {
  svg.textContent = "";
  const mid = h / 2;
  svg.appendChild(sv("line", { x1: 0, y1: mid, x2: w, y2: mid, stroke: "var(--rule)", "stroke-width": 1 }));
  const step = w / Math.max(days.length, 1);
  days.forEach((d, i) => {
    const x = i * step + step / 2;
    const z = Math.min(Math.abs(d.z || 0), 4);
    const amp = Math.max((z / 4) * (mid - 6), 1.5);
    const strong = d.status === "changed" || d.status === "watch";
    svg.appendChild(sv("line", {
      x1: x, y1: mid - amp, x2: x, y2: mid + amp, stroke: colour(d.status),
      "stroke-width": strong ? 3 : 1.6, "stroke-linecap": "round",
      opacity: d.status === "baselining" ? .35 : strong ? 1 : .8,
    }));
  });
}

/* ---------------------------------------------------------------- hero */

async function hero() {
  const svg = $("#hero-svg"), cap = $("#hero-cap");
  let data = null;
  try {
    const r = await fetch("data.json", { cache: "no-store" });
    if (r.ok) data = await r.json();
  } catch { /* no record yet */ }

  const real = data && data.models && data.models.length && data.models[0].days.length;
  let days;
  if (real) {
    // Overlay every model's series into one strip: the hero is the record.
    const all = data.models.flatMap((m) => m.days);
    days = all.map((d) => ({ status: d.status, z: d.z }));
    const total = all.length;
    const changes = all.filter((d) => d.status === "changed").length;
    cap.textContent = `${data.models.length} model${data.models.length === 1 ? "" : "s"} · ${total} model-days on record · ${changes} confirmed change${changes === 1 ? "" : "s"} · last run ${data.last_run}`
      + (data.demo ? " · demo or local data" : "");
    const sd = $("#stat-days");
    if (sd) sd.dataset.count = String(total);
  } else {
    // No record yet. Draw a labelled illustration so the page is not blank - 
    // and say plainly that it is an illustration.
    const sim = simulateDays(11, 120, 80, "refusal_rate", .3);
    days = runDetector(sim);
    cap.textContent = "Illustration - the record starts when the first run completes. Nothing here is estimated.";
  }
  drawTrace(svg, days, 1400, 160);

  if (!reduceMotion) {
    const ticks = [...svg.querySelectorAll("line")].slice(1);
    ticks.forEach((t, i) => {
      t.style.opacity = "0";
      t.style.transition = "opacity .3s ease";
      setTimeout(() => { t.style.opacity = ""; }, Math.min(i * (900 / ticks.length), 1100));
    });
  }
}

function runDetector(sim) {
  const history = [], flagged = new Set(), recent = [], out = [];
  for (const day of sim) {
    const v = evaluate(day, history, flagged, recent);
    const exc = v.flagged.length > 0;
    recent.push(exc);
    if (exc) flagged.add(day.date);
    out.push({ ...day, status: v.status, flagged: v.flagged, z: v.z });
    history.push(day);
  }
  return out;
}

/* --------------------------------------------------------------- replay */

function replay() {
  const svg = $("#rp-svg"), play = $("#rp-play"), reset = $("#rp-reset");
  const speed = $("#rp-speed"), dayEl = $("#rp-day"), famEl = $("#rp-fam");
  const verdict = $("#rp-verdict"), log = $("#rp-log");
  if (!svg) return;

  const DAYS = 40, INJECT = 24;
  let sim = [], shown = [], i = 0, timer = null;
  let history = [], flagged = new Set(), recent = [], lastStatus = "";

  const init = () => {
    clearInterval(timer); timer = null;
    sim = simulateDays(7, DAYS, INJECT, "refusal_rate", .30);
    shown = []; i = 0; history = []; flagged = new Set(); recent = []; lastStatus = "";
    log.textContent = "";
    dayEl.textContent = `day 0 of ${DAYS}`;
    famEl.textContent = "";
    setVerdict("baselining", []);
    drawTrace(svg, [], 1000, 120);
    play.textContent = "Play";
  };

  const setVerdict = (st, fl) => {
    verdict.className = "rp-verdict" + (st === "changed" ? " v-changed" : st === "watch" ? " v-watch" : "");
    verdict.textContent = "";
    const dot = document.createElement("span"); dot.className = "dot s-" + st;
    verdict.appendChild(dot);
    verdict.appendChild(document.createTextNode(
      st === "stable" ? "no significant change" : st === "watch" ? "excursion, unconfirmed"
        : st === "changed" ? "changed" : "collecting baseline"));
    famEl.textContent = fl.length ? "beyond floor: " + fl.map((f) => f.replace(/_/g, " ")).join(", ") : "";
  };

  const addLog = (text, cls) => {
    const li = document.createElement("li");
    li.textContent = text;
    if (cls) li.className = cls;
    log.appendChild(li);
    log.scrollTop = log.scrollHeight;
  };

  const step = () => {
    if (i >= sim.length) { clearInterval(timer); timer = null; play.textContent = "Done"; return; }
    const day = sim[i];
    const v = evaluate(day, history, flagged, recent);
    const exc = v.flagged.length > 0;
    recent.push(exc);
    if (exc) flagged.add(day.date);
    shown.push({ ...day, status: v.status, flagged: v.flagged, z: v.z });
    history.push(day);
    drawTrace(svg, shown, 1000, 120);
    dayEl.textContent = `day ${i + 1} of ${DAYS}`;
    setVerdict(v.status, v.flagged);

    const rf = day.fam.refusal_rate.fails;
    if (i === 0) addLog("day 1: collecting baseline - nothing can be flagged for 7 days");
    if (i === 6) addLog("day 7: baseline established, detection is live");
    if (i === INJECT) addLog(`day ${i + 1}: refusal rate quietly moves to ~30% on one family. Nobody announces it. The detector hasn't seen it yet.`, "warm");
    // Announce transitions only; a log that shouts every day buries the signal.
    if (v.status !== lastStatus) {
      if (v.status === "watch") addLog(`day ${i + 1}: excursion - refusal_rate ${rf}/30, beyond the floor. Published as 'watch', not yet a change.`, "warm");
      else if (v.status === "changed") addLog(`day ${i + 1}: CHANGED - second excursion within three days. refusal_rate ${rf}/30. Card goes out.`, "hot");
      else if (v.status === "stable" && lastStatus === "watch") addLog(`day ${i + 1}: back within floor - the excursion was not confirmed`);
    }
    lastStatus = v.status;
    i++;
  };

  play.addEventListener("click", () => {
    if (timer) { clearInterval(timer); timer = null; play.textContent = "Play"; return; }
    if (i >= sim.length) init();
    play.textContent = "Pause";
    const ms = [0, 700, 450, 260, 140, 60][Number(speed.value)];
    timer = setInterval(step, reduceMotion ? 0 : ms);
    if (reduceMotion) { while (i < sim.length) step(); }
  });
  reset.addEventListener("click", init);
  speed.addEventListener("input", () => {
    if (timer) { clearInterval(timer); const ms = [0, 700, 450, 260, 140, 60][Number(speed.value)]; timer = setInterval(step, ms); }
  });

  init();
  $("#replay-jump")?.addEventListener("click", () => {
    $("#replay").scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth" });
    setTimeout(() => { if (!timer && i === 0) play.click(); }, reduceMotion ? 0 : 600);
  });
}

/* ------------------------------------------------------------ counters */

function counters() {
  const els = [...document.querySelectorAll(".stat .big")];
  const run = (el) => {
    const target = parseFloat(el.dataset.count || "0");
    const dec = parseInt(el.dataset.dec || "0", 10);
    const suffix = el.dataset.suffix || "";
    if (reduceMotion || target === 0) { el.textContent = target.toFixed(dec) + suffix; return; }
    const start = performance.now(), dur = 900;
    const tick = (now) => {
      const t = Math.min((now - start) / dur, 1);
      const eased = 1 - Math.pow(1 - t, 3);
      el.textContent = (target * eased).toFixed(dec) + suffix;
      if (t < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  };
  const io = new IntersectionObserver((entries) => {
    entries.forEach((e) => { if (e.isIntersecting) { run(e.target); io.unobserve(e.target); } });
  }, { threshold: .4 });
  els.forEach((el) => io.observe(el));
}

/* -------------------------------------------------------------- reveal */

function reveal() {
  const targets = document.querySelectorAll(".band .wrap > *, .step, .stat");
  targets.forEach((t) => t.classList.add("reveal"));
  const io = new IntersectionObserver((entries) => {
    entries.forEach((e) => { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } });
  }, { threshold: .12 });
  targets.forEach((t) => io.observe(t));
}

/* ---------------------------------------------------------------- boot */

function boot() {
  wireTheme();
  hero();
  replay();
  counters();
  reveal();
}
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
else boot();
