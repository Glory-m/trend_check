/* trend-watch 사이트 — 빌드 도구·외부 라이브러리 없음.
 * 보안: 수집된 외부 텍스트는 모두 textContent/setAttribute로만 넣는다(innerHTML 미사용). 링크는 http(s)만 허용.
 * 모션: CSS + Web Animations. prefers-reduced-motion이면 즉시 최종 상태로 그린다.
 */
"use strict";

// ======================= 상수 =======================
const CATS = [
  { key: "신기술", cls: "cat-1", v: "--cat-1" },
  { key: "스킬·플러그인·MCP", cls: "cat-2", v: "--cat-2" },
  { key: "사용법·워크플로", cls: "cat-3", v: "--cat-3" },
  { key: "보안", cls: "cat-4", v: "--cat-4" },
  { key: "기타", cls: "cat-0", v: "--cat-0" },
];
const CAT_BY_KEY = Object.fromEntries(CATS.map((c) => [c.key, c]));
const IMP_ORDER = { 높음: 0, 보통: 1, 낮음: 2 };
const SERIES_VARS = ["--cat-1", "--cat-2", "--cat-3", "--cat-4"]; // 비교 그래프 최대 4계열 (검증된 순서)
const OFFICIAL_TYPES = new Set(["official_release_note", "official_post", "official_repo", "hn_mention"]);
const DISCOVER_TYPES = new Set(["repo_surge", "candidate_new", "trending", "promote_suggest", "demote_suggest",
  "suspicious", "repo_release", "repo_renamed", "repo_archived", "npm_unlisted"]);
const KST = 9 * 3600e3;
const DAY = 864e5;
const SVG_NS = "http://www.w3.org/2000/svg";
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

const state = { days: 7, imp: "mid", cats: new Set(CATS.map((c) => c.key)), q: "", showAllHigh: false };
const cache = { index: null, health: null, metrics: null, series: null, days: new Map(), digest: undefined };

// ======================= DOM 도우미 =======================
function el(tag, attrs, ...children) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") n.className = v;
    else if (k === "text") n.textContent = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v === true ? "" : String(v));
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    n.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return n;
}
function svg(tag, attrs, ...children) {
  const n = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) if (v !== null && v !== undefined) n.setAttribute(k, String(v));
  for (const c of children.flat()) if (c) n.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return n;
}
const ICONS = {
  clock: ["circle:12,12,9", "M12 7v5l3 2"],
  alert: ["M10.3 3.9L1.8 18a2 2 0 001.7 3h17a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z", "M12 9v4", "M12 17h.01"],
  shield: ["M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"],
  spark: ["M12 3l1.9 5.6L19.5 10l-5.6 1.9L12 17.5l-1.9-5.6L4.5 10l5.6-1.4z"],
  layers: ["M12 2l9 5-9 5-9-5z", "M3 12l9 5 9-5", "M3 17l9 5 9-5"],
  code: ["M16 18l6-6-6-6", "M8 6l-6 6 6 6"],
  star: ["M12 2l3.1 6.3 6.9 1-5 4.9 1.2 6.8L12 17.8 5.8 21l1.2-6.8-5-4.9 6.9-1z"],
  sun: ["circle:12,12,4", "M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"],
  moon: ["M21 12.8A9 9 0 1111.2 3a7 7 0 009.8 9.8z"],
  monitor: ["M3 4h18v12H3z", "M8 20h8M12 16v4"],
  play: ["M7 4l13 8-13 8z"],
  pause: ["M7 5h3v14H7zM14 5h3v14h-3z"],
  doc: ["M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z", "M14 2v6h6", "M8 13h8", "M8 17h5"],
};
function icon(name, size = 16) {
  const s = svg("svg", { width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor",
    "stroke-width": 2, "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true" });
  for (const p of ICONS[name] || []) {
    if (p.startsWith("circle:")) { const [cx, cy, r] = p.slice(7).split(","); s.append(svg("circle", { cx, cy, r })); }
    else s.append(svg("path", { d: p }));
  }
  return s;
}
/** 중요도 = 신호 막대 모양 (색이 아닌 모양으로 구분) */
function impGlyph(level) {
  const n = level === "높음" ? 3 : level === "보통" ? 2 : 1;
  const s = svg("svg", { width: 16, height: 16, viewBox: "0 0 16 16", "aria-hidden": "true" });
  [[1.5, 10, 4.5], [6.5, 6, 8.5], [11.5, 2, 12.5]].forEach(([x, y, h], i) => {
    s.append(svg("rect", { x, y, width: 3, height: h, rx: 1.2, fill: i < n ? "currentColor" : "none",
      stroke: "currentColor", "stroke-width": i < n ? 0 : 1, opacity: i < n ? 1 : 0.35 }));
  });
  return s;
}
function safeUrl(u) {
  if (typeof u !== "string") return null;
  try { const url = new URL(u.trim()); return url.protocol === "https:" || url.protocol === "http:" ? url.href : null; }
  catch { return null; }
}
const extLink = (href, text, cls) => (href ? el("a", { href, rel: "noopener noreferrer", target: "_blank", class: cls, text }) : document.createTextNode(text));

// ======================= 시간·숫자 =======================
const parseIso = (s) => { const d = s ? new Date(s) : null; return d && !isNaN(d) ? d : null; };
const pad = (n) => String(n).padStart(2, "0");
function kp(d) { const k = new Date(d.getTime() + KST); return { y: k.getUTCFullYear(), m: k.getUTCMonth() + 1, d: k.getUTCDate(), w: k.getUTCDay(), hh: k.getUTCHours(), mm: k.getUTCMinutes() }; }
const kstDate = (d) => { const p = kp(d); return `${p.y}-${pad(p.m)}-${pad(p.d)}`; };
const fmtKst = (d) => { if (!d) return "—"; const p = kp(d); return `${p.y}-${pad(p.m)}-${pad(p.d)} ${pad(p.hh)}:${pad(p.mm)}`; };
const fmtHM = (d) => { const p = kp(d); return `${pad(p.hh)}:${pad(p.mm)}`; };
function relTime(d) {
  if (!d) return "";
  const m = Math.round((Date.now() - d.getTime()) / 60000);
  if (m < 1) return "방금";
  if (m < 60) return `${m}분 전`;
  const h = Math.round(m / 60);
  return h < 48 ? `${h}시간 전` : `${Math.round(h / 24)}일 전`;
}
function compact(n) {
  if (n === null || n === undefined) return "—";
  const a = Math.abs(n);
  if (a >= 1e6) return (n / 1e6).toFixed(a >= 1e7 ? 0 : 1).replace(/\.0$/, "") + "M";
  if (a >= 1e4) return (n / 1e3).toFixed(a >= 1e5 ? 0 : 1).replace(/\.0$/, "") + "K";
  return Math.round(n).toLocaleString("ko-KR");
}
const signed = (n) => (n === null || n === undefined ? "—" : (n > 0 ? "+" : "") + Math.round(n).toLocaleString("ko-KR"));
const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

// ======================= 모션 도우미 =======================
const easeOutExpo = (t) => (t === 1 ? 1 : 1 - 2 ** (-10 * t));
/** 숫자를 이전 값에서 새 값으로 굴린다 */
function countTo(node, to, fmt = (v) => Math.round(v).toLocaleString("ko-KR"), dur = 900) {
  const from = Number(node.dataset.v || 0);
  node.dataset.v = String(to);
  if (reduceMotion.matches || from === to || !Number.isFinite(to)) { node.textContent = fmt(to); return; }
  const t0 = performance.now();
  const step = (now) => {
    const t = Math.min(1, (now - t0) / dur);
    node.textContent = fmt(from + (to - from) * easeOutExpo(t));
    if (t < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}
/** 화면에 들어올 때 순서대로 떠오르게 */
const revealer = "IntersectionObserver" in window ? new IntersectionObserver((entries) => {
  let i = 0;
  for (const e of entries) {
    if (!e.isIntersecting) continue;
    e.target.style.setProperty("--delay", `${Math.min(i++, 6) * 70}ms`);
    e.target.classList.add("is-revealed");
    e.target.querySelectorAll(".chart").forEach((c) => c.classList.add("is-drawn"));
    revealer.unobserve(e.target);
  }
}, { rootMargin: "0px 0px -8% 0px", threshold: 0.08 }) : null;
function revealNow(n, i = 0) {
  n.style.setProperty("--delay", `${Math.min(i, 8) * 80}ms`);
  n.classList.add("is-revealed");
  n.querySelectorAll(".chart").forEach((c) => c.classList.add("is-drawn"));
}
/** 첫 화면 안의 요소는 바로(순서대로) 등장, 아래쪽은 스크롤할 때 등장. 어떤 경우에도 내용이 숨은 채로 남지 않게 안전장치를 둔다. */
function observeReveal(root = document) {
  const nodes = [...root.querySelectorAll("[data-reveal]:not(.is-revealed)")];
  let i = 0;
  for (const n of nodes) {
    if (!revealer || reduceMotion.matches || n.getBoundingClientRect().top < innerHeight) revealNow(n, i++);
    else revealer.observe(n);
  }
  setTimeout(() => document.querySelectorAll("[data-reveal]:not(.is-revealed)").forEach((n) => revealNow(n)), 2500);
}

// ======================= 상태 화면 (로딩·빈·오류) =======================
function emptyState(msg, hint, ic = "layers") {
  return el("li", { class: "state-empty" }, el("span", { class: "state-icon" }, icon(ic, 18)),
    el("span", {}, msg, hint ? el("small", { text: hint }) : null));
}
function renderSkeleton() {
  document.getElementById("kpis").replaceChildren(...[0, 1, 2, 3].map(() => el("div", { class: "kpi", "aria-hidden": "true" },
    el("div", { class: "skeleton sk-line", style: null }), el("div", { class: "skeleton sk-value" }))));
  ["high-list", "official-list", "discover-list"].forEach((id) => document.getElementById(id).replaceChildren(
    ...[0, 1, 2].map(() => el("li", { class: "item", "aria-hidden": "true" }, el("span"), el("div", {},
      el("div", { class: "skeleton sk-line" }), el("div", { class: "skeleton sk-line" }))))));
}
function renderError(err) {
  const isFile = location.protocol === "file:";
  const status = Number((String(err?.message).match(/HTTP (\d+)/) || [])[1]);
  const cause = isFile
    ? ["이 페이지를 파일로 직접 열었어요.", ["폴더에서 ", el("code", { text: "python -m http.server" }), " 실행 후 http://localhost:8000 으로 여세요."]]
    : status === 404
      ? ["아직 수집된 데이터가 없어요.", ["첫 수집(매일 06:17 KST) 전이거나, GitHub Pages가 아직 배포 중일 수 있어요."]]
      : ["데이터 서버에 연결하지 못했어요.", ["인터넷 연결을 확인하거나 잠시 뒤 다시 시도하세요."]];
  const sig = svg("svg", { class: "signal", viewBox: "0 0 400 120", "aria-hidden": "true", preserveAspectRatio: "none" },
    svg("path", { class: "flat", d: "M8 70 H150 L165 40 L180 96 L195 70 H392", pathLength: 1 }),
    svg("path", { class: "blip", d: "M150 70 L165 40 L180 96 L195 70", pathLength: 1 }),
    svg("circle", { class: "dot-end", cx: 392, cy: 70, r: 5 }));
  const retry = el("button", { class: "btn btn-primary", type: "button" }, "다시 시도");
  retry.addEventListener("click", () => location.reload());
  const box = el("section", { class: "state-error", role: "alert", "aria-live": "assertive" },
    el("div", {},
      el("h2", {}, "신호가 잠시 끊겼어요.", el("br"), el("span", { class: "dim", text: cause[0] })),
      el("p", {}, ...cause[1]),
      el("ul", {},
        el("li", {}, "수집 상태는 GitHub Actions의 ", el("code", { text: "collect" }), " 실행 기록에서 볼 수 있어요."),
        el("li", { text: "PC에서는 이 폴더에서 git pull 후 /brief 로도 같은 데이터를 볼 수 있어요." })),
      el("div", { class: "state-actions" }, retry,
        el("a", { class: "btn btn-ghost", href: "https://github.com/Glory-m/trend_check/actions/workflows/collect.yml", rel: "noopener noreferrer", target: "_blank" }, "수집 상태 보기"))),
    sig);
  document.getElementById("filters").hidden = true;
  document.querySelector(".hero").hidden = true;
  document.querySelector(".bento").hidden = true;
  document.getElementById("digest").hidden = true;
  document.querySelector(".content").prepend(box);
  const f = document.querySelector("#fresh .fresh-text");
  f.textContent = "연결 끊김";
  document.getElementById("fresh").className = "fresh is-stale";
  document.documentElement.classList.remove("is-booting");
}
function staggerItems(ul) {
  if (reduceMotion.matches) return;
  [...ul.children].slice(0, 14).forEach((li, i) => { li.style.setProperty("--delay", `${i * 28}ms`); li.classList.add("enter"); });
}
function moveThumb(seg) {
  const on = seg.querySelector('button[aria-pressed="true"]');
  const thumb = seg.querySelector(".seg-thumb");
  if (!on || !thumb || !on.offsetWidth) return;
  thumb.style.width = `${on.offsetWidth}px`;
  thumb.style.transform = `translateX(${on.offsetLeft}px)`;
  seg.classList.add("has-thumb");
}

// ======================= 데이터 =======================
async function getJSON(path) {
  const r = await fetch(path, { cache: "no-cache" });
  if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
  return r.json();
}
async function getText(path) {
  try { const r = await fetch(path, { cache: "no-cache" }); return r.ok ? r.text() : null; } catch { return null; }
}
function windowRange(days = state.days) {
  const now = new Date();
  if (days === 1) { const p = kp(now); return { start: new Date(Date.UTC(p.y, p.m - 1, p.d) - KST), end: now, label: "오늘" }; }
  return { start: new Date(now.getTime() - days * DAY), end: now, label: `최근 ${days}일` };
}
function datesBetween(start, end) {
  const out = new Set();
  for (let t = start.getTime() - DAY; t <= end.getTime() + DAY; t += DAY) out.add(kstDate(new Date(t)));
  return [...out];
}
async function loadItems(range) {
  const known = cache.index.item_dates || {};
  const dates = datesBetween(range.start, range.end).filter((d) => d in known);
  await Promise.all(dates.filter((d) => !cache.days.has(d)).map(async (d) => {
    try { cache.days.set(d, (await getJSON(`data/items/${d}.json`)).items || []); } catch { cache.days.set(d, []); }
  }));
  const out = [];
  for (const d of dates) for (const x of cache.days.get(d) || []) {
    const c = parseIso(x.collected_at);
    if (c && c >= range.start && c < range.end) out.push(x);
  }
  return out;
}
async function loadDigest() {
  if (cache.digest !== undefined) return cache.digest;
  const now = Date.now();
  for (let i = 0; i < 7; i++) {
    const d = kstDate(new Date(now - i * DAY));
    const text = await getText(`data/digests/${d}.md`);
    if (text) return (cache.digest = { date: d, text });
  }
  return (cache.digest = null);
}

// ======================= 상태 <-> 주소(#) =======================
function readHash() {
  const p = new URLSearchParams(location.hash.slice(1));
  const days = Number(p.get("days"));
  state.days = [1, 3, 7, 30].includes(days) ? days : 7;
  state.imp = ["high", "mid", "all"].includes(p.get("imp")) ? p.get("imp") : "mid";
  const keys = (p.get("cat") || "").split(",").filter((k) => CAT_BY_KEY[k]);
  state.cats = new Set(keys.length ? keys : CATS.map((c) => c.key));
  state.q = p.get("q") || "";
}
function writeHash() {
  const p = new URLSearchParams();
  if (state.days !== 7) p.set("days", state.days);
  if (state.imp !== "mid") p.set("imp", state.imp);
  if (state.cats.size !== CATS.length) p.set("cat", [...state.cats].join(","));
  if (state.q) p.set("q", state.q);
  const h = p.toString();
  history.replaceState(null, "", h ? `#${h}` : location.pathname + location.search);
}

// ======================= 필터 =======================
const matchQ = (x) => !state.q || [x.title, x.body, x.repo, x.importance_reason, x.version]
  .some((v) => v && String(v).toLowerCase().includes(state.q.toLowerCase()));
const passImp = (x) => state.imp === "all" || x.importance === "높음" || (state.imp === "mid" && x.importance === "보통");
const passCat = (x) => state.cats.has(x.category || "기타");
const sortItems = (a, b) => (IMP_ORDER[a.importance] ?? 3) - (IMP_ORDER[b.importance] ?? 3)
  || String(b.published_at || b.collected_at).localeCompare(String(a.published_at || a.collected_at));
function toggleCat(key) {
  if (state.cats.size === CATS.length) state.cats = new Set([key]);               // 전체 상태에서 누르면 그것만
  else if (state.cats.has(key)) { state.cats.delete(key); if (!state.cats.size) state.cats = new Set(CATS.map((c) => c.key)); }
  else state.cats.add(key);
  update();
}

// ======================= 상단 신선도 =======================
function renderFresh(items) {
  const box = document.getElementById("fresh");
  const last = parseIso(cache.index?.last_collected_at);
  const stale = !last || Date.now() - last.getTime() >= 24 * 3600e3;
  const failed = Object.entries(cache.health?.steps || {}).filter(([, v]) => v.status === "fail").map(([k]) => k);
  box.className = `fresh ${stale || failed.length ? "is-stale" : "is-fresh"}`;
  const q = items.filter((x) => x.quarantined).length;
  const text = box.querySelector(".fresh-text");
  text.replaceChildren(
    stale ? "수집 오래됨 · " : "", el("strong", { text: last ? `${fmtHM(last)} 수집` : "수집 없음" }),
    last ? ` · ${relTime(last)}` : "", failed.length ? ` · 실패 ${failed.length}` : "", q ? ` · 격리 ${q}` : "");
  box.title = [`마지막 수집 ${fmtKst(last)} KST`, stale ? "24시간 넘게 갱신 안 됨 — git pull 또는 Actions 수동 실행" : "",
    failed.length ? `실패 단계: ${failed.join(", ")}` : "", `보안 검사: 격리 ${q}건`].filter(Boolean).join("\n");
}

// ======================= 히어로 =======================
function renderHero(items, range) {
  const now = new Date(), p = kp(now);
  document.getElementById("hero-date").textContent =
    `${p.y}. ${p.m}. ${p.d}. (${"일월화수목금토"[p.w]}) · ${range.label} · KST`;
  const high = items.filter((x) => x.importance === "높음");
  const ccVers = new Set(items.filter((x) => x.type === "claude_code_change").map((x) => x.version));
  const models = items.filter((x) => /새 모델|출시 신호/.test(x.importance_reason || "")).length;
  const title = document.getElementById("hero-title");
  const line2 = [ccVers.size ? `Claude Code ${ccVers.size}개 버전` : "", models ? `출시 소식 ${models}건` : "",
    `${items.length.toLocaleString("ko-KR")}건 수집`].filter(Boolean).join(" · ");
  if (!items.length) title.replaceChildren(el("span", { class: "hl", text: "조용한 하루." }), el("span", { class: "line2", text: "이 기간에 새로 수집된 소식이 없어요" }));
  else if (!high.length) title.replaceChildren("중요한 변화 없음.", el("span", { class: "line2", text: line2 }));
  else title.replaceChildren(el("span", { class: "hl", text: `주목할 변화 ${high.length}건.` }), el("span", { class: "line2", text: line2 }));
  document.getElementById("hero-sub").textContent =
    `${fmtKst(range.start)} – ${fmtKst(range.end)} KST · 내 프로필 기준으로 분류한 소식`;
  renderKpis(items, high, ccVers);
  renderCatbar(items);
  renderTicker(high);
}

function kpiSpark(values) {
  if (values.length < 2) return null;
  const W = 64, H = 22, max = Math.max(...values, 1);
  const d = values.map((v, i) => `${i ? "L" : "M"}${(i / (values.length - 1)) * W},${H - 2 - (v / max) * (H - 4)}`).join("");
  return svg("svg", { class: "kpi-spark", viewBox: `0 0 ${W} ${H}`, "aria-hidden": "true" }, svg("path", { d }));
}
function renderKpis(items, high, ccVers) {
  const box = document.getElementById("kpis");
  const dates = Object.entries(cache.index?.item_dates || {}).sort(([a], [b]) => a.localeCompare(b)).slice(-14);
  const latest = ((cache.health?.steps?.claude_code?.detail || "").match(/latest=([\d.]+)/) || [])[1] || "—";
  const m = cache.metrics || { repos: {} };
  const core = Object.values(m.repos || {}).filter((r) => r.tier === "core");
  const hasD1 = core.some((r) => r.d1 !== null && r.d1 !== undefined);
  const d1 = core.reduce((s, r) => s + (r.d1 || 0), 0);
  const surges = Object.values(m.repos || {}).filter((r) => (r.surge || []).length).length;
  const defs = [
    { id: "k-new", ic: "layers", label: "새 항목", value: items.length, foot: `높음 ${high.length} · 보통 ${items.filter((x) => x.importance === "보통").length}`, spark: dates.map(([, n]) => n) },
    { id: "k-high", ic: "spark", label: "중요도 높음", value: high.length, foot: high.length ? "아래 '핵심 변경'" : "높음 없음" },
    { id: "k-cc", ic: "code", label: "Claude Code 최신", text: latest, foot: ccVers.size ? `기간 내 ${ccVers.size}개 버전` : "기간 내 새 버전 없음" },
    { id: "k-star", ic: "star", label: "핵심 레포 별 · 1일", value: hasD1 ? d1 : null, signedV: true,
      foot: hasD1 ? `${core.length}개 합계${surges ? ` · 급등 ${surges}` : ""}` : `이력 ${m.history_days || 0}일 — 내일부터 계산` },
  ];
  if (!box.querySelector(".kpi[id]")) {
    box.replaceChildren(...defs.map((k) => el("div", { class: "kpi", id: k.id },
      el("div", { class: "kpi-label" }, icon(k.ic, 14), k.label),
      el("div", { class: "kpi-value" }, el("span", { class: "num", text: "0" })),
      el("div", { class: "kpi-foot" }))));
  }
  for (const k of defs) {
    const card = document.getElementById(k.id);
    const num = card.querySelector(".num");
    if (k.text !== undefined) num.textContent = k.text;
    else if (k.value === null) num.textContent = "—";
    else countTo(num, k.value, k.signedV ? signed : undefined);
    card.querySelector(".kpi-foot").textContent = k.foot;
    card.querySelector(".kpi-spark")?.remove();
    if (k.spark) { const s = kpiSpark(k.spark); if (s) card.append(s); }
  }
}

/** 펄스 차트 — 실제 데이터: 최근 14일 동안 '발표된' 항목 수 (published_at 기준, 없으면 수집 시각) */
function renderPulse(items14) {
  const fig = document.getElementById("pulse-chart");
  fig.querySelector("svg")?.remove();
  fig.querySelector(".tooltip")?.remove();
  const today = new Date();
  const days = [...Array(14)].map((_, i) => kstDate(new Date(today.getTime() - (13 - i) * DAY)));
  const counts = Object.fromEntries(days.map((d) => [d, 0]));
  for (const x of items14) {
    const d = kstDate(parseIso(x.published_at) || parseIso(x.collected_at));
    if (d in counts) counts[d]++;
  }
  const vals = days.map((d) => counts[d]);
  const peak = Math.max(...vals);
  document.getElementById("pulse-caption-note").textContent = peak
    ? `최대 ${peak}건 (${days[vals.indexOf(peak)].slice(5)}) · 발표일 기준` : "데이터 없음";
  const W = 700, H = 120, P = { l: 4, r: 14, t: 12, b: 18 };
  const x = (i) => P.l + (i / 13) * (W - P.l - P.r);
  const y = (v) => P.t + (1 - v / Math.max(peak, 1)) * (H - P.t - P.b);
  // 부드러운 곡선 (monotone 근사)
  let d = `M${x(0)},${y(vals[0])}`;
  for (let i = 1; i < 14; i++) {
    const cx = (x(i - 1) + x(i)) / 2;
    d += ` C${cx},${y(vals[i - 1])} ${cx},${y(vals[i])} ${x(i)},${y(vals[i])}`;
  }
  const area = `${d} L${x(13)},${H - P.b} L${x(0)},${H - P.b} Z`;
  const color = cssVar("--cat-1");
  const s = svg("svg", { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", role: "img", tabindex: 0,
    "aria-label": `최근 14일 발표량. ${days.map((dd, i) => `${dd.slice(5)} ${vals[i]}건`).join(", ")}` },
    svg("defs", {}, svg("linearGradient", { id: "pulse-grad", x1: 0, x2: 0, y1: 0, y2: 1 },
      svg("stop", { offset: "0%", "stop-color": color, "stop-opacity": 0.32 }),
      svg("stop", { offset: "100%", "stop-color": color, "stop-opacity": 0 }))),
    svg("line", { class: "pulse-base", x1: P.l, x2: W - P.r, y1: H - P.b, y2: H - P.b }),
    svg("path", { class: "pulse-area", d: area }),
    svg("path", { class: "pulse-line", d, pathLength: 1 }),
    svg("circle", { class: "pulse-dot-halo", cx: x(13), cy: y(vals[13]), r: 4 }),
    svg("circle", { class: "pulse-dot", cx: x(13), cy: y(vals[13]), r: 4 }),
    ...[0, 7, 13].map((i) => svg("text", { class: "pulse-tick", x: x(i), y: H - 3, "text-anchor": i === 0 ? "start" : i === 13 ? "end" : "middle" },
      i === 13 ? "오늘" : days[i].slice(5))));
  const cross = svg("line", { class: "pulse-cross", y1: P.t, y2: H - P.b, visibility: "hidden" });
  s.append(cross);
  s.append(svg("rect", { class: "pulse-hit", x: 0, y: 0, width: W, height: H }));
  const tip = el("div", { class: "tooltip", role: "status" });
  tip.hidden = true;
  let cur = 13;
  const show = (i) => {
    cur = Math.max(0, Math.min(13, i));
    cross.setAttribute("x1", x(cur)); cross.setAttribute("x2", x(cur)); cross.setAttribute("visibility", "visible");
    tip.replaceChildren(el("div", { class: "t-date", text: days[cur] }), el("div", { class: "t-row" }, el("strong", { text: `${vals[cur]}건` }), el("span", { text: "발표" })));
    tip.hidden = false;
    const b = s.getBoundingClientRect();
    tip.style.left = `${Math.min(Math.max((x(cur) / W) * b.width + 10, 0), b.width - 120)}px`;
    tip.style.top = "30px";
  };
  const hide = () => { cross.setAttribute("visibility", "hidden"); tip.hidden = true; };
  s.addEventListener("pointermove", (e) => { const b = s.getBoundingClientRect(); show(Math.round(((e.clientX - b.left) / b.width) * 13)); });
  s.addEventListener("pointerleave", hide);
  s.addEventListener("focus", () => show(13));
  s.addEventListener("blur", hide);
  s.addEventListener("keydown", (e) => { if (e.key === "ArrowLeft") show(cur - 1); if (e.key === "ArrowRight") show(cur + 1); });
  fig.append(s, tip);
}

function renderCatbar(items) {
  const bar = document.getElementById("catbar"), legend = document.getElementById("catbar-legend");
  const base = items.filter((x) => passImp(x) && matchQ(x));
  const counts = Object.fromEntries(CATS.map((c) => [c.key, 0]));
  base.forEach((x) => { counts[x.category || "기타"] = (counts[x.category || "기타"] || 0) + 1; });
  const total = Math.max(1, base.length);
  if (!bar.children.length) {
    for (const c of CATS) {
      const b = el("button", { type: "button", class: c.cls });
      b.addEventListener("click", () => toggleCat(c.key));
      bar.append(b);
    }
  }
  [...bar.children].forEach((b, i) => {
    const c = CATS[i], n = counts[c.key];
    b.style.width = n ? `calc(${(n / total) * 100}% - 2px)` : "0px";
    b.hidden = !n;
    b.classList.toggle("is-off", !state.cats.has(c.key));
    b.setAttribute("aria-label", `${c.key} ${n}건 (${Math.round((n / total) * 100)}%) — 누르면 필터`);
    b.setAttribute("aria-pressed", String(state.cats.has(c.key) && state.cats.size !== CATS.length));
  });
  legend.replaceChildren(...CATS.filter((c) => counts[c.key]).map((c) =>
    el("span", {}, el("i", { class: `dot ${c.cls}`, "aria-hidden": "true" }), c.key, el("b", { text: counts[c.key] }))));
}

function renderTicker(high) {
  const track = document.getElementById("ticker-track");
  const list = high.slice().sort(sortItems).slice(0, 14);
  const mk = (hidden) => list.map((x) => el("li", hidden ? { "aria-hidden": "true" } : {},
    el("i", { class: `dot ${(CAT_BY_KEY[x.category] || CAT_BY_KEY["기타"]).cls}`, "aria-hidden": "true" }),
    extLink(safeUrl(x.url), (x.title || "").slice(0, 90) + ((x.title || "").length > 90 ? "…" : ""))));
  if (!list.length) { track.replaceChildren(el("li", { text: "이 기간에 중요도 높음 항목이 없습니다." })); return; }
  track.replaceChildren(...mk(false), ...mk(true)); // 끊김 없는 반복을 위해 두 벌 (두 번째는 보조기기에서 숨김)
  track.querySelectorAll('[aria-hidden="true"] a').forEach((a) => a.setAttribute("tabindex", "-1"));
  requestAnimationFrame(() => {
    const w = track.scrollWidth / 2;
    track.style.setProperty("--ticker-dur", `${Math.max(30, w / 55)}s`);
  });
}

// ======================= digest =======================
function parseFrontmatter(text) {
  const meta = {};
  let body = text;
  const m = text.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?/);
  if (m) {
    body = text.slice(m[0].length);
    for (const line of m[1].split(/\r?\n/)) { const kv = line.match(/^([\w-]+):\s*(.*)$/); if (kv) meta[kv[1]] = kv[2].replace(/^["']|["']$/g, ""); }
  }
  return { meta, body };
}
/** 안전한 최소 마크다운 → DOM (제목·목록·문단·구분선·굵게·코드·http(s) 링크만) */
function renderMarkdown(src) {
  const root = el("div", { class: "digest-body" });
  let list = null;
  const inline = (text) => {
    const frag = document.createDocumentFragment();
    const rx = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\[([^\]]+)\]\((\S+?)\))|(https?:\/\/[^\s)<>]+)/g;
    let last = 0, mm;
    while ((mm = rx.exec(text))) {
      if (mm.index > last) frag.append(text.slice(last, mm.index));
      if (mm[1]) frag.append(el("code", { text: mm[1].slice(1, -1) }));
      else if (mm[2]) frag.append(el("strong", { text: mm[2].slice(2, -2) }));
      else if (mm[3]) frag.append(extLink(safeUrl(mm[5]), mm[4]));
      else frag.append(extLink(safeUrl(mm[6]), mm[6]));
      last = rx.lastIndex;
    }
    if (last < text.length) frag.append(text.slice(last));
    return frag;
  };
  for (const raw of src.split(/\r?\n/)) {
    const line = raw.trimEnd();
    const h = line.match(/^(#{1,3})\s+(.*)$/);
    const li = line.match(/^\s*(?:[-*]|\d+\.)\s+(.*)$/);
    if (!li) list = null;
    if (!line.trim()) continue;
    if (h) root.append(el(`h${h[1].length}`, {}, inline(h[2])));
    else if (/^-{3,}$/.test(line.trim())) root.append(el("hr"));
    else if (li) { if (!list) { list = el(/^\s*\d+\./.test(line) ? "ol" : "ul"); root.append(list); } list.append(el("li", {}, inline(li[1]))); }
    else root.append(el("p", {}, inline(line)));
  }
  return root;
}
function renderDigest() {
  const box = document.getElementById("digest");
  const dg = cache.digest;
  box.hidden = false;
  if (!dg) {
    box.replaceChildren(el("div", { class: "digest-empty" }, icon("doc", 20),
      el("div", {}, el("strong", { text: "AI 요약(digest)이 아직 없습니다." }), " 아래는 규칙 기반 결과입니다. PC에서 ",
        el("code", { text: "/brief" }), " 실행 후 저장하면 여기에 표시됩니다.")));
    return;
  }
  const { meta, body } = parseFrontmatter(dg.text);
  const gen = parseIso(meta.generated_at);
  box.classList.add("digest-collapsed");
  const btn = el("button", { class: "btn-text", type: "button", "aria-expanded": "false", text: "전체 보기" });
  btn.addEventListener("click", () => {
    const open = !box.classList.toggle("digest-collapsed");
    btn.setAttribute("aria-expanded", String(open));
    btn.textContent = open ? "접기" : "전체 보기";
  });
  box.replaceChildren(
    el("div", { class: "digest-meta" }, el("span", { class: "ai-badge" }, icon("spark", 12), "AI 요약"),
      el("span", { text: `${meta.kind || "brief"} · ${dg.date}` }),
      meta.window_kst ? el("span", { text: `구간 ${meta.window_kst}` }) : null,
      gen ? el("span", { text: `작성 ${fmtKst(gen)} KST` }) : null,
      meta.model ? el("span", { text: `모델 ${meta.model}` }) : null,
      el("span", { text: "classified_by: ai" })),
    renderMarkdown(body), btn);
}

// ======================= 항목 =======================
function itemNode(x, { inTimeline = false } = {}) {
  const cat = CAT_BY_KEY[x.category] || CAT_BY_KEY["기타"];
  const level = x.importance || "미분류";
  const pub = parseIso(x.published_at), col = parseIso(x.collected_at);
  return el("li", { class: `item ${level === "높음" ? "is-high" : level === "낮음" ? "is-low" : ""} ${x.quarantined ? "is-quarantined" : ""}` },
    el("span", { class: "imp", title: `중요도 ${level}` }, x.quarantined ? icon("shield", 16) : impGlyph(level),
      el("span", { class: "visually-hidden", text: `중요도 ${level}. ` })),
    el("div", { class: "item-title", title: x.title || "" }, extLink(safeUrl(x.url), x.title || "(제목 없음)")),
    el("div", { class: "item-meta" },
      el("span", { class: "cat" }, el("i", { class: `dot ${cat.cls}`, "aria-hidden": "true" }), x.category || "미분류"),
      x.version && !inTimeline ? el("span", { class: "mono", text: `v${x.version}` }) : null,
      x.repo && !(x.title || "").includes(x.repo) ? el("span", { text: x.repo }) : null,
      pub ? el("span", { text: `발표 ${kstDate(pub)}` }) : col ? el("span", { text: `수집 ${fmtKst(col)}` }) : null),
    x.importance_reason ? el("div", { class: "item-reason", text: x.importance_reason }) : null);
}
function renderList(id, items, empty, hint = "기간을 늘리거나 중요도·분류 필터를 넓혀 보세요.") {
  const ul = document.getElementById(id);
  ul.replaceChildren(...(items.length ? items.map((x) => itemNode(x)) : [emptyState(empty, hint)]));
  staggerItems(ul);
}
function renderHigh(items) {
  const high = items.filter((x) => x.importance === "높음" && passCat(x) && matchQ(x)).sort(sortItems);
  const limit = state.showAllHigh ? high.length : 10;
  renderList("high-list", high.slice(0, limit), "이 기간·필터에 '높음' 항목이 없습니다.");
  document.getElementById("high-sub").textContent = `중요도 높음 ${high.length}건`;
  const more = document.getElementById("high-more");
  more.replaceChildren(high.length > 10 ? el("button", { class: "btn-text", type: "button",
    text: state.showAllHigh ? "접기" : `나머지 ${high.length - 10}건 더 보기`,
    onclick: () => { state.showAllHigh = !state.showAllHigh; renderHigh(items); } }) : "");
}
function renderTimeline(items) {
  const box = document.getElementById("cc-timeline");
  const cc = items.filter((x) => x.type === "claude_code_change" && passCat(x) && matchQ(x));
  const byVer = new Map();
  cc.forEach((x) => { if (!byVer.has(x.version)) byVer.set(x.version, []); byVer.get(x.version).push(x); });
  const vkey = (v) => (v || "0").split(".").map((n) => n.padStart(5, "0")).join(".");
  const versions = [...byVer.keys()].sort((a, b) => vkey(b).localeCompare(vkey(a)));
  document.getElementById("cc-sub").textContent = `${versions.length}개 버전 · ${cc.length}건`;
  if (!versions.length) { box.replaceChildren(el("ul", { class: "items" }, emptyState("이 기간에 Claude Code 새 버전이 없어요.", "기간을 30일로 늘려 보세요.", "code"))); return; }
  box.replaceChildren(...versions.map((v) => {
    const list = byVer.get(v).sort(sortItems);
    const shown = list.filter(passImp);
    const hidden = list.length - shown.length;
    const pub = parseIso(list[0].published_at);
    const counts = ["높음", "보통", "낮음"].map((l) => [l, list.filter((x) => x.importance === l).length])
      .filter(([, n]) => n).map(([l, n]) => `${l} ${n}`).join(" · ");
    const ul = el("ul", { class: "items" }, shown.map((x) => itemNode(x, { inTimeline: true })));
    const node = el("div", { class: "version" }, el("span", { class: "version-marker", "aria-hidden": "true" }),
      el("div", { class: "version-head" }, el("span", { class: "ver", text: `v${v}` }),
        pub ? el("span", { class: "when", text: `${fmtKst(pub)} KST` }) : null, el("span", { class: "counts", text: counts })), ul);
    if (hidden) {
      const btn = el("button", { class: "btn-text", type: "button", text: `낮음 등 ${hidden}건 펼치기` });
      btn.addEventListener("click", () => { ul.replaceChildren(...list.map((x) => itemNode(x, { inTimeline: true }))); staggerItems(ul); btn.remove(); });
      node.append(btn);
    }
    return node;
  }));
}

// ======================= 스타 =======================
function niceTicks(max, count = 4) {
  if (max <= 0) return [0, 1];
  const raw = max / count, mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((s) => s * mag).find((s) => raw <= s);
  const t = [];
  for (let v = 0; v <= max + step * 0.5; v += step) t.push(Math.round(v));
  return t;
}
function lineChart(container, dates, series) {
  const W = 640, H = 240, M = { t: 12, r: 118, b: 26, l: 44 };
  const pw = W - M.l - M.r, ph = H - M.t - M.b;
  const ticks = niceTicks(Math.max(1, ...series.flatMap((s) => s.values.filter((v) => v !== null))));
  const top = ticks[ticks.length - 1];
  const x = (i) => M.l + (dates.length === 1 ? pw / 2 : (i / (dates.length - 1)) * pw);
  const y = (v) => M.t + ph - (v / top) * ph;
  const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", tabindex: 0,
    "aria-label": "별 증가량 추이 — 방향키로 날짜 이동, 값은 아래 표에도 있음" });
  ticks.forEach((t) => {
    root.append(svg("line", { class: t === 0 ? "baseline" : "gridline", x1: M.l, x2: M.l + pw, y1: y(t), y2: y(t) }));
    root.append(svg("text", { class: "tick", x: M.l - 6, y: y(t) + 4, "text-anchor": "end" }, compact(t)));
  });
  (dates.length <= 4 ? dates.map((_, i) => i) : [0, Math.floor((dates.length - 1) / 2), dates.length - 1])
    .forEach((i) => root.append(svg("text", { class: "tick", x: x(i), y: H - 6, "text-anchor": "middle" }, dates[i].slice(5))));
  const ends = [];
  series.forEach((s, si) => {
    const color = cssVar(SERIES_VARS[si]);
    let d = "";
    s.values.forEach((v, i) => { if (v !== null) d += `${d ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`; });
    root.append(svg("path", { class: "series", d, stroke: color, pathLength: 1, style: null }));
    const li = s.values.map((v, i) => (v !== null ? i : -1)).filter((i) => i >= 0).pop();
    if (li !== undefined) {
      root.append(svg("circle", { class: "end-dot", cx: x(li), cy: y(s.values[li]), r: 4, fill: color }));
      ends.push({ y: y(s.values[li]), label: `${s.name.split("/")[1] || s.name} ${signed(s.values[li])}` });
    }
  });
  ends.sort((a, b) => a.y - b.y);
  let prev = -Infinity;
  for (const e of ends) {   // 겹치는 끝 라벨은 연결선(leader)으로 잇는다
    const ly = Math.max(e.y, prev + 14);
    prev = ly;
    if (Math.abs(ly - e.y) > 2) root.append(svg("line", { class: "gridline", x1: M.l + pw + 6, y1: e.y, x2: M.l + pw + 12, y2: ly }));
    root.append(svg("text", { class: "end-label", x: M.l + pw + 14, y: ly + 4 }, e.label.length > 18 ? e.label.slice(0, 17) + "…" : e.label));
  }
  const cross = svg("line", { class: "crosshair", y1: M.t, y2: M.t + ph, visibility: "hidden" });
  root.append(cross, svg("rect", { x: M.l, y: M.t, width: pw, height: ph, fill: "transparent" }));
  const wrap = el("div", { class: "chart-wrap chart" }, root);
  const tip = el("div", { class: "tooltip", role: "status" });
  tip.hidden = true;
  wrap.append(tip);
  let cur = dates.length - 1;
  const keyOf = (si) => { const k = el("span", { class: "key" }); k.style.background = cssVar(SERIES_VARS[si]); return k; };
  const show = (i) => {
    cur = Math.max(0, Math.min(dates.length - 1, i));
    cross.setAttribute("x1", x(cur)); cross.setAttribute("x2", x(cur)); cross.setAttribute("visibility", "visible");
    tip.replaceChildren(el("div", { class: "t-date", text: dates[cur] }),
      ...series.map((s, si) => el("div", { class: "t-row" }, keyOf(si), el("strong", { text: signed(s.values[cur]) }), el("span", { text: s.name }))));
    tip.hidden = false;
    const b = root.getBoundingClientRect();
    tip.style.left = `${Math.min(Math.max((x(cur) / W) * b.width + 12, 0), b.width - 190)}px`;
    tip.style.top = "8px";
  };
  const hide = () => { cross.setAttribute("visibility", "hidden"); tip.hidden = true; };
  root.addEventListener("pointermove", (ev) => { const b = root.getBoundingClientRect(); show(Math.round((((ev.clientX - b.left) / b.width) * W - M.l) / pw * (dates.length - 1))); });
  root.addEventListener("pointerleave", hide);
  root.addEventListener("focus", () => show(dates.length - 1));
  root.addEventListener("blur", hide);
  root.addEventListener("keydown", (ev) => {
    if (ev.key === "ArrowLeft") { show(cur - 1); ev.preventDefault(); }
    if (ev.key === "ArrowRight") { show(cur + 1); ev.preventDefault(); }
    if (ev.key === "Escape") hide();
  });
  container.append(
    el("div", { class: "legend" }, series.map((s, si) => el("span", {}, keyOf(si), s.name))),
    wrap,
    el("details", { class: "table-view" }, el("summary", { text: "표로 보기" }),
      el("div", { class: "table-scroll" }, el("table", { class: "repo-table" },
        el("thead", {}, el("tr", {}, el("th", { text: "날짜" }), series.map((s) => el("th", { class: "num", text: s.name })))),
        el("tbody", {}, dates.map((d, i) => el("tr", {}, el("td", { text: d }), series.map((s) => el("td", { class: "num", text: signed(s.values[i]) })))))))));
}
function sparkline(values) {
  const pts = values.map((v, i) => [i, v]).filter(([, v]) => v !== null);
  if (pts.length < 2) return el("span", { class: "spark-empty", text: `이력 ${pts.length}일` });
  const W = 100, H = 28, P = 3, vs = pts.map(([, v]) => v);
  const min = Math.min(...vs), max = Math.max(...vs);
  const x = (i) => P + (i / (values.length - 1)) * (W - 2 * P);
  const y = (v) => (max === min ? H / 2 : P + (1 - (v - min) / (max - min)) * (H - 2 * P));
  const [li, lv] = pts[pts.length - 1];
  return svg("svg", { class: "spark", viewBox: `0 0 ${W} ${H}`, width: "100%", height: H, "aria-hidden": "true" },
    svg("path", { d: pts.map(([i, v], k) => `${k ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("") }),
    svg("circle", { cx: x(li), cy: y(lv), r: 3 }));
}
function renderStars() {
  const m = cache.metrics || { repos: {}, history_days: 0 };
  const s = cache.series || { dates: [], repos: {} };
  const hist = s.dates.length;
  document.getElementById("stars-sub").textContent = `이력 ${hist}일 · 오늘부터 쌓음`;
  const box = document.getElementById("movers");
  box.replaceChildren();
  const n = Math.min(hist, Math.max(state.days, 2) + 1);
  const dates = s.dates.slice(-n);
  if (dates.length < 4) {
    // 이력이 4일 미만이면 선 그래프 대신 진행 상태 + 별 상위 막대 (데이터가 적을 땐 숫자가 정답)
    const prog = el("span");
    const core = Object.entries(m.repos || {}).filter(([, r]) => r.tier === "core").sort(([, a], [, b]) => b.stars - a.stars).slice(0, 5);
    const max = Math.max(1, ...core.map(([, r]) => r.stars));
    const meters = core.map(([name, r]) => {
      const fill = el("span");
      requestAnimationFrame(() => requestAnimationFrame(() => { fill.style.width = `${(r.stars / max) * 100}%`; }));
      return el("li", {}, el("span", { class: "nm", text: name }), el("span", { class: "vl", text: `★${compact(r.stars)}` }), el("span", { class: "meter" }, fill));
    });
    box.append(el("div", { class: "wait-card" },
      el("p", {}, el("strong", { text: `추이 그래프까지 ${Math.max(0, 4 - hist)}일` }), ` — 매일 06:17 수집될 때마다 하루씩 쌓입니다 (${hist}/4일).`),
      el("div", { class: "bar" }, prog)),
      el("h3", { class: "mini-title", text: "별 상위 5 (핵심 watchlist)" }), el("ul", { class: "top-stars" }, meters));
    requestAnimationFrame(() => requestAnimationFrame(() => { prog.style.width = `${(hist / 4) * 100}%`; }));
  } else {
    const off = hist - dates.length;
    const gains = Object.entries(s.repos).map(([name, vals]) => {
      const w = vals.slice(off), base = w.find((v) => v !== null);
      if (base === undefined) return null;
      const g = w.map((v) => (v === null ? null : v - base));
      return { name, values: g, last: g.filter((v) => v !== null).pop() || 0 };
    }).filter(Boolean).sort((a, b) => b.last - a.last).slice(0, 4);
    box.append(el("p", { class: "footnote", text: "기간 시작 대비 누적 별 증가 상위 4 — 레포 크기가 달라도 한 축에서 비교되도록 증가량으로 맞춤" }));
    lineChart(box, dates, gains);
    if (box.closest(".is-revealed") || reduceMotion.matches) box.querySelector(".chart")?.classList.add("is-drawn");
  }
  renderRepos(m, s);
}
function renderRepos(m, s) {
  const box = document.getElementById("repos");
  const ord = ([, a], [, b]) => (b.d7 ?? b.d1 ?? 0) - (a.d7 ?? a.d1 ?? 0) || b.stars - a.stars;
  const core = Object.entries(m.repos || {}).filter(([, r]) => r.tier === "core").sort(ord);
  const cand = Object.entries(m.repos || {}).filter(([, r]) => r.tier === "candidate").sort(ord).slice(0, 10);
  document.getElementById("repos-sub").textContent = `${core.length}개 · 기준 ${m.date || "—"}`;
  const table = (list) => el("div", { class: "table-scroll" }, el("table", { class: "repo-table" },
    el("colgroup", {}, el("col", { class: "col-name" }), el("col", { class: "col-num" }), el("col", { class: "col-num" }),
      el("col", { class: "col-num hide-sm" }), el("col", { class: "col-spark" })),
    el("thead", {}, el("tr", {}, el("th", { text: "레포" }), el("th", { class: "num", text: "★" }), el("th", { class: "num", text: "1일" }),
      el("th", { class: "num hide-sm", text: "7일" }), el("th", { text: "추이" }))),
    el("tbody", {}, list.map(([name, r]) => {
      const [owner, repo] = name.split("/");
      return el("tr", {},
        el("td", { class: "name" }, el("a", { href: safeUrl(`https://github.com/${name}`), rel: "noopener noreferrer", target: "_blank" },
          el("span", { class: "owner", text: `${owner}/` }), repo),
          (r.warnings || []).length ? el("span", { class: "sub" }, el("span", { class: "warn-tag" }, icon("alert", 12), `참고 경고 · ${r.warnings[0]}`)) : null),
        el("td", { class: "num", text: compact(r.stars) }),
        el("td", { class: `num ${r.d1 > 0 ? "up" : ""}`, text: signed(r.d1) }),
        el("td", { class: `num hide-sm ${r.d7 > 0 ? "up" : ""}`, text: signed(r.d7) }),
        el("td", {}, sparkline((s.repos[name] || []).slice(-30))));
    }))));
  box.replaceChildren(table(core),
    el("details", { class: "table-view" }, el("summary", { text: `자동 추적 후보 상위 ${cand.length} 보기` }), table(cand)));
}

// ======================= 필터 UI =======================
function buildChips(items) {
  const box = document.getElementById("f-cat");
  const counts = Object.fromEntries(CATS.map((c) => [c.key, 0]));
  items.filter((x) => passImp(x) && matchQ(x)).forEach((x) => { counts[x.category || "기타"]++; });
  if (!box.children.length) {
    for (const c of CATS) {
      const chip = el("button", { class: "chip", type: "button", "data-key": c.key },
        el("i", { class: `dot ${c.cls}`, "aria-hidden": "true" }), c.key, el("span", { class: "count" }));
      chip.addEventListener("click", () => toggleCat(c.key));
      box.append(chip);
    }
  }
  box.querySelectorAll(".chip").forEach((chip) => {
    const k = chip.dataset.key;
    chip.setAttribute("aria-pressed", String(state.cats.has(k)));
    chip.querySelector(".count").textContent = counts[k];
  });
}
function wireControls() {
  document.querySelectorAll("#f-range button").forEach((b) => b.addEventListener("click", () => { state.days = Number(b.dataset.days); state.showAllHigh = false; update(); }));
  document.querySelectorAll("#f-imp button").forEach((b) => b.addEventListener("click", () => { state.imp = b.dataset.imp; update(); }));
  const q = document.getElementById("f-q");
  q.value = state.q;
  let t;
  q.addEventListener("input", () => { clearTimeout(t); t = setTimeout(() => { state.q = q.value.trim(); update(); }, 180); });
  document.addEventListener("keydown", (e) => {
    if (e.key === "/" && !/^(INPUT|TEXTAREA)$/.test(document.activeElement?.tagName)) { e.preventDefault(); q.focus(); }
    if (e.key === "Escape" && document.activeElement === q && q.value) { q.value = ""; state.q = ""; update(); }
  });
  // 티커 일시정지 (자동으로 움직이는 콘텐츠는 멈출 수 있어야 한다)
  const ticker = document.getElementById("ticker"), tb = document.getElementById("ticker-btn");
  tb.addEventListener("click", () => {
    const paused = ticker.classList.toggle("is-paused");
    tb.setAttribute("aria-pressed", String(paused));
    tb.setAttribute("aria-label", paused ? "흐르는 소식 다시 재생" : "흐르는 소식 일시정지");
    tb.replaceChildren(icon(paused ? "play" : "pause", 16));
  });
  // 테마: 시스템 → 라이트 → 다크, 버튼 위치에서 원형으로 퍼지는 전환
  const themeBtn = document.getElementById("theme-toggle");
  const label = () => {
    const cur = document.documentElement.getAttribute("data-theme") || "system";
    themeBtn.setAttribute("aria-label", `테마 바꾸기 (현재: ${{ system: "시스템", light: "라이트", dark: "다크" }[cur]})`);
    themeBtn.replaceChildren(icon(cur === "dark" ? "moon" : cur === "light" ? "sun" : "monitor", 20));
  };
  themeBtn.addEventListener("click", () => {
    const order = ["system", "light", "dark"];
    const cur = document.documentElement.getAttribute("data-theme") || "system";
    const next = order[(order.indexOf(cur) + 1) % 3];
    const apply = () => {
      if (next === "system") document.documentElement.removeAttribute("data-theme");
      else document.documentElement.setAttribute("data-theme", next);
      try { next === "system" ? localStorage.removeItem("tw-theme") : localStorage.setItem("tw-theme", next); } catch { /* 저장소 차단 */ }
      label();
      renderStars(); renderPulse(cache.items14 || []); // 차트 색은 CSS 변수에서 다시 읽는다
    };
    if (document.startViewTransition && !reduceMotion.matches) {
      const r = themeBtn.getBoundingClientRect();
      const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
      const root = document.documentElement.style;
      root.setProperty("--vt-x", `${cx}px`); root.setProperty("--vt-y", `${cy}px`);
      root.setProperty("--vt-r", `${Math.hypot(Math.max(cx, innerWidth - cx), Math.max(cy, innerHeight - cy))}px`);
      document.startViewTransition(apply);
    } else apply();
  });
  label();
  // 스크롤 시 상단 바 경계선
  const topbar = document.getElementById("topbar");
  const onScroll = () => topbar.classList.toggle("is-scrolled", scrollY > 8);
  addEventListener("scroll", onScroll, { passive: true });
  onScroll();
  addEventListener("resize", () => document.querySelectorAll(".seg").forEach(moveThumb));
}
function syncPressed() {
  document.querySelectorAll("#f-range button").forEach((b) => b.setAttribute("aria-pressed", String(Number(b.dataset.days) === state.days)));
  document.querySelectorAll("#f-imp button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.imp === state.imp)));
  document.querySelectorAll(".seg").forEach(moveThumb);
}

// ======================= 갱신 =======================
let ticket = 0;
async function update() {
  const my = ++ticket;
  writeHash();
  syncPressed();
  const main = document.getElementById("main");
  main.classList.add("loading");   // 다시 불러오는 동안 이전 화면 유지 (깜빡임·레이아웃 이동 없음)
  const range = windowRange();
  const items = await loadItems(range);
  if (my !== ticket) return;
  main.classList.remove("loading");
  const scoped = items.filter((x) => passCat(x) && matchQ(x));
  renderFresh(items);
  renderHero(items, range);
  buildChips(items);
  renderHigh(items);
  renderTimeline(items);
  const official = scoped.filter((x) => OFFICIAL_TYPES.has(x.type) && passImp(x)).sort(sortItems);
  renderList("official-list", official.slice(0, 20), "이 기간·필터에 공식 소식이 없습니다.");
  document.getElementById("official-sub").textContent = `${official.length}건`;
  const disc = scoped.filter((x) => DISCOVER_TYPES.has(x.type) && passImp(x)).sort(sortItems);
  renderList("discover-list", disc, "이 기간·필터에 급등·신규 발견이 없습니다.");
  document.getElementById("discover-sub").textContent = `${disc.length}건`;
  renderStars();
  document.getElementById("live").textContent = `${range.label} 항목 ${scoped.filter(passImp).length}건 표시`;
}

async function init() {
  readHash();
  wireControls();
  syncPressed();
  renderSkeleton();
  try {
    [cache.index, cache.health, cache.metrics, cache.series] = await Promise.all([
      getJSON("data/index.json"), getJSON("data/health.json").catch(() => null),
      getJSON("data/metrics.json").catch(() => null), getJSON("data/series.json").catch(() => null)]);
  } catch (e) {
    renderError(e);
    observeReveal();
    return;
  }
  cache.items14 = await loadItems(windowRange(14));
  renderPulse(cache.items14);
  await loadDigest();
  renderDigest();
  await update();
  document.documentElement.classList.remove("is-booting");
  observeReveal();
}
addEventListener("hashchange", () => { readHash(); document.getElementById("f-q").value = state.q; update(); });
init();
