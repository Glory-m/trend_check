/* trend-watch — 흰색 브리핑 사이트 (빌드 도구·외부 라이브러리 없음)
 * 보안: 외부 텍스트는 textContent/setAttribute로만 넣는다(HTML 문자열 삽입 없음). 링크는 http(s)만 허용.
 * 한국어 우선: AI 번역(data/ko, classified_by: ai) → 규칙 머리말(headline_ko) → 원문 순서로 보여 준다.
 * 모션: CSS + requestAnimationFrame. prefers-reduced-motion이면 즉시 최종 상태, 브리핑 자동 넘김도 끈다.
 */
"use strict";

// ======================= 상수 =======================
const CATS = [
  { key: "신기술", cls: "cat-1" }, { key: "스킬·플러그인·MCP", cls: "cat-2" },
  { key: "사용법·워크플로", cls: "cat-3" }, { key: "보안", cls: "cat-4" }, { key: "기타", cls: "cat-0" },
];
const CAT = Object.fromEntries(CATS.map((c) => [c.key, c]));
const IMP = { 높음: 0, 보통: 1, 낮음: 2 };
const TYPE_RANK = { official_release_note: 0, official_repo: 1, claude_code_change: 2, repo_surge: 3, official_post: 4,
  hn_mention: 5, trending: 6, candidate_new: 7, repo_release: 8 };
const OFFICIAL = new Set(["official_release_note", "official_post", "official_repo", "hn_mention"]);
const ECO = new Set(["trending", "candidate_new", "repo_release", "repo_surge", "promote_suggest", "demote_suggest", "suspicious", "repo_archived", "repo_renamed"]);
const KST = 9 * 3600e3, DAY = 864e5, NS = "http://www.w3.org/2000/svg";
const reduce = matchMedia("(prefers-reduced-motion: reduce)");
const state = { days: 7, imp: "mid", cats: new Set(CATS.map((c) => c.key)), q: "", allLimit: 30 };
const cache = { index: null, health: null, metrics: null, series: null, days: new Map(), ko: new Map(), digest: undefined, items: [] };

// ======================= DOM =======================
function el(tag, attrs, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") n.className = v;
    else if (k === "text") n.textContent = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v === true ? "" : String(v));
  }
  for (const c of kids.flat()) if (c != null && c !== false) n.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return n;
}
function svg(tag, attrs, ...kids) {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) if (v != null) n.setAttribute(k, String(v));
  for (const c of kids.flat()) if (c) n.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return n;
}
const ICON = {
  play: [["path", { d: "M7 4.5v15l13-7.5z", fill: "currentColor", stroke: "none" }]],
  pause: [["path", { d: "M7 5h3.5v14H7zM13.5 5H17v14h-3.5z", fill: "currentColor", stroke: "none" }]],
  close: [["path", { d: "M6 6l12 12M18 6L6 18" }]],
  sun: [["circle", { cx: 12, cy: 12, r: 4 }], ["path", { d: "M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" }]],
  moon: [["path", { d: "M21 12.8A9 9 0 1111.2 3a7 7 0 009.8 9.8z" }]],
  doc: [["path", { d: "M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" }], ["path", { d: "M14 2v6h6M8 13h8M8 17h5" }]],
  inbox: [["path", { d: "M22 12h-6l-2 3h-4l-2-3H2" }], ["path", { d: "M5.5 5h13L22 12v6a2 2 0 01-2 2H4a2 2 0 01-2-2v-6z" }]],
  alert: [["path", { d: "M10.3 3.9L1.8 18a2 2 0 001.7 3h17a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z" }], ["path", { d: "M12 9v4M12 17h.01" }]],
  arrow: [["path", { d: "M7 17L17 7M9 7h8v8" }]],
  shield: [["path", { d: "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" }]],
  send: [["path", { d: "M12 19V5M5 12l7-7 7 7" }]],
  stop: [["rect", { x: 7, y: 7, width: 10, height: 10, rx: 2, fill: "currentColor", stroke: "none" }]],
  plus: [["path", { d: "M12 5v14M5 12h14" }]],
};
function icon(name, size = 18) {
  const s = svg("svg", { width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor",
    "stroke-width": 2, "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true" });
  for (const [t, a] of ICON[name] || []) s.append(svg(t, a));
  return s;
}
function safeUrl(u) {
  if (typeof u !== "string") return null;
  try { const x = new URL(u.trim()); return x.protocol === "https:" || x.protocol === "http:" ? x.href : null; } catch { return null; }
}
const link = (href, text, cls) => (href ? el("a", { href, rel: "noopener noreferrer", target: "_blank", class: cls, text })
  : el("span", { class: cls, text }));

// ======================= 시간·숫자 =======================
const parseIso = (s) => { const d = s ? new Date(s) : null; return d && !isNaN(d) ? d : null; };
const pad = (n) => String(n).padStart(2, "0");
function kp(d) { const k = new Date(d.getTime() + KST); return { y: k.getUTCFullYear(), m: k.getUTCMonth() + 1, d: k.getUTCDate(), w: k.getUTCDay(), hh: k.getUTCHours(), mm: k.getUTCMinutes() }; }
const kstDate = (d) => { const p = kp(d); return `${p.y}-${pad(p.m)}-${pad(p.d)}`; };
const mdKo = (d) => { const p = kp(d); return `${p.m}월 ${p.d}일`; };
const hm = (d) => { const p = kp(d); return `${pad(p.hh)}:${pad(p.mm)}`; };
const fmtKst = (d) => (d ? `${kstDate(d)} ${hm(d)}` : "—");
function rel(d) {
  if (!d) return "";
  const m = Math.round((Date.now() - d) / 6e4);
  if (m < 1) return "방금";
  if (m < 60) return `${m}분 전`;
  const h = Math.round(m / 60);
  return h < 48 ? `${h}시간 전` : `${Math.round(h / 24)}일 전`;
}
function compact(n) {
  if (n == null) return "—";
  const a = Math.abs(n);
  if (a >= 1e6) return `${(n / 1e6).toFixed(1).replace(/\.0$/, "")}M`;
  if (a >= 1e4) return `${(n / 1e3).toFixed(a >= 1e5 ? 0 : 1).replace(/\.0$/, "")}K`;
  return Math.round(n).toLocaleString("ko-KR");
}
const signed = (n) => (n == null ? "—" : `${n > 0 ? "+" : ""}${Math.round(n).toLocaleString("ko-KR")}`);
const cssVar = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

// ======================= 표시 문장 (한국어 우선) =======================
const koOf = (x) => cache.ko.get(x.id)?.ko || null;
const mainText = (x) => koOf(x) || x.headline_ko || x.title || "(제목 없음)";
const kicker = (x) => (x.headline_ko || "").split(" · ")[0].split(" — ")[0];
function origLine(x) {
  if (!x.title || mainText(x) === x.title) return null;
  return el("span", { class: "orig", title: x.title, text: x.title });
}
const catTag = (x) => { const c = CAT[x.category] || CAT["기타"]; return el("span", { class: "tag" }, el("i", { class: `dot ${c.cls}`, "aria-hidden": "true" }), x.category || "기타"); };
/** 규칙 판정 근거를 사람이 읽는 한국어로 (원래 근거는 title 속성에 남긴다) */
const ENV_KO = { windows: "Windows", vscode: "VS Code", "vs code": "VS Code", powershell: "PowerShell" };
const WHY = [
  [/^보안 이슈/, () => "보안과 직접 관련된 이슈예요"],
  [/^보안 관련 언급/, () => "보안과 관련된 소식이에요"],
  [/^스타 급등/, () => "별이 빠르게 늘고 있는 저장소예요"],
  [/^새 모델·제품 출시/, () => "새로운 모델이나 기능이 출시됐어요"],
  [/^기존 사용법을 바꾸는/, () => "지금 쓰는 방식이 바뀔 수 있어요 — 한 번 확인해 보세요"],
  [/^내 요금제\((.+?)\)/, (m) => `내 요금제(${m[1]})에 해당하는 소식이에요`],
  [/^설치된 도구 '([^']+)'/, (m) => `내가 설치한 ${m[1]}와 관련 있어요`],
  [/^관심 분야 '([^']+)' 키워드/, (m) => `관심 분야(${m[1]})와 관련 있어요`],
  [/^관심 분야 '([^']+)' 버그 수정/, (m) => `관심 분야(${m[1]})의 문제가 고쳐졌어요`],
  [/^관심 분야 '([^']+)' 소소한 개선/, (m) => `관심 분야(${m[1]})가 조금 나아졌어요`],
  [/^내 환경\(([^)]+)\) 버그 수정/, (m) => `내 환경(${ENV_KO[m[1]] || m[1]})의 문제가 고쳐졌어요`],
  [/^내 환경\(([^)]+)\) 관련 변경/, (m) => `내 환경(${ENV_KO[m[1]] || m[1]})에 해당하는 변경이에요`],
  [/^내 스택 '([^']+)'/, (m) => `내 스택(${m[1]})과 관련 있어요`],
  [/^신규 발견/, () => "새로 빠르게 뜨고 있는 저장소예요"],
  [/^벤치마크 1위 변경/, () => "AI 코딩 벤치마크 1위가 바뀌었어요"],
  [/^벤치마크 새 기록/, () => "AI 코딩 벤치마크에 새 기록이 올라왔어요"],
  [/^GitHub 트렌딩/, () => "GitHub 트렌딩에 올랐어요"],
  [/^watchlist 변경 제안/, () => "관심 저장소에 넣거나 뺄지 검토해 볼 만해요"],
  [/^스타 패턴 참고 경고/, () => "별 증가 패턴이 특이해요 (참고만 하세요)"],
  [/^인젝션 의심/, () => "의심 문구가 있어 격리했어요 — 원문은 직접 확인하세요"],
  [/^단순 버그 수정/, () => "일반적인 버그 수정이에요"],
  [/^내가 쓰지 않는 기능·환경 '([^']+)'/, (m) => `내가 쓰지 않는 ${m[1]} 관련이에요`],
  [/^관심 없는 분야/, () => "관심 밖 분야예요"],
  [/^개발 주제와 무관/, () => "개발과 직접 관련 없는 소식이에요"],
];
function friendlyWhy(r) {
  if (!r) return null;
  for (const [rx, fn] of WHY) { const m = r.match(rx); if (m) return fn(m); }
  return r;
}
const aiMark = (x) => {
  const k = cache.ko.get(x.id);
  if (!k) return null;
  return k.classified_by === "mt"
    ? el("span", { class: "ai-mark mt", title: "무료 기계 번역 (Azure) — /brief 실행 시 Claude 번역으로 다듬어져요" }, "기계 번역")
    : el("span", { class: "ai-mark", title: "Claude가 번역한 문장 (classified_by: ai)" }, "AI 번역");
};
const sortItems = (a, b) => (IMP[a.importance] ?? 3) - (IMP[b.importance] ?? 3)
  || (TYPE_RANK[a.type] ?? 9) - (TYPE_RANK[b.type] ?? 9)
  || String(b.published_at || b.collected_at).localeCompare(String(a.published_at || a.collected_at));

// ======================= 모션 도우미 =======================
const easeOut = (t) => (t === 1 ? 1 : 1 - 2 ** (-10 * t));
function countTo(node, to, fmt = (v) => Math.round(v).toLocaleString("ko-KR"), dur = 1100) {
  if (reduce.matches || !Number.isFinite(to)) { node.textContent = fmt(to); return; }
  const t0 = performance.now();
  const step = (now) => { const t = Math.min(1, (now - t0) / dur); node.textContent = fmt(to * easeOut(t)); if (t < 1) requestAnimationFrame(step); };
  requestAnimationFrame(step);
}
const io = "IntersectionObserver" in window ? new IntersectionObserver((es) => {
  let i = 0;
  for (const e of es) if (e.isIntersecting) { reveal(e.target, i++); io.unobserve(e.target); }
}, { rootMargin: "0px 0px -10% 0px", threshold: 0.06 }) : null;
function reveal(n, i = 0) {
  n.style.setProperty("--delay", `${Math.min(i, 6) * 90}ms`);
  n.classList.add("is-revealed", "is-drawn");
  n.querySelectorAll("[data-count]").forEach((c) => { if (!c.dataset.done) { c.dataset.done = 1; countTo(c, Number(c.dataset.count), c.dataset.signed ? signed : undefined); } });
}
function observe() {
  let i = 0;
  document.querySelectorAll("[data-reveal]:not(.is-revealed)").forEach((n) => {
    if (!io || reduce.matches || n.getBoundingClientRect().top < innerHeight * 0.92) reveal(n, i++);
    else io.observe(n);
  });
  setTimeout(() => document.querySelectorAll("[data-reveal]:not(.is-revealed)").forEach((n) => reveal(n)), 3000); // 안전장치
}
function moveThumb(seg) {
  const on = seg.querySelector('button[aria-pressed="true"]'), th = seg.querySelector(".seg-thumb");
  if (!on || !th || !on.offsetWidth) return;
  th.style.width = `${on.offsetWidth}px`;
  th.style.transform = `translateX(${on.offsetLeft - 2}px)`;
  seg.classList.add("has-thumb");
}

// ======================= 데이터 =======================
async function getJSON(p) { const r = await fetch(p, { cache: "no-cache" }); if (!r.ok) throw new Error(`${p}: HTTP ${r.status}`); return r.json(); }
async function getText(p) { try { const r = await fetch(p, { cache: "no-cache" }); return r.ok ? r.text() : null; } catch { return null; } }
function range(days = state.days) {
  const now = new Date();
  if (days === 1) { const p = kp(now); return { start: new Date(Date.UTC(p.y, p.m - 1, p.d) - KST), end: now, label: "오늘" }; }
  return { start: new Date(now - days * DAY), end: now, label: `최근 ${days}일` };
}
function datesIn(r) { const s = new Set(); for (let t = r.start - DAY; t <= +r.end + DAY; t += DAY) s.add(kstDate(new Date(t))); return [...s]; }
async function loadItems(r) {
  const known = cache.index.item_dates || {};
  const dates = datesIn(r).filter((d) => d in known);
  await Promise.all(dates.filter((d) => !cache.days.has(d)).map(async (d) => {
    const [items, ko] = await Promise.all([getJSON(`data/items/${d}.json`).then((j) => j.items || []).catch(() => []),
      getJSON(`data/ko/${d}.json`).then((j) => j.items || {}).catch(() => ({}))]);
    cache.days.set(d, items);
    for (const [id, v] of Object.entries(ko)) cache.ko.set(id, v);
  }));
  const out = [];
  for (const d of dates) for (const x of cache.days.get(d) || []) { const c = parseIso(x.collected_at); if (c && c >= r.start && c < r.end) out.push(x); }
  return out;
}
async function loadDigest() {   // 최근 7일 digest를 동시에 요청하고 가장 최근 것을 쓴다
  const dates = [...Array(7)].map((_, i) => kstDate(new Date(Date.now() - i * DAY)));
  const texts = await Promise.all(dates.map((d) => getText(`data/digests/${d}.md`)));
  const i = texts.findIndex(Boolean);
  return i < 0 ? null : { date: dates[i], text: texts[i] };
}

// ======================= 주소(#) 상태 =======================
function readHash() {
  const p = new URLSearchParams(location.hash.slice(1));
  const d = Number(p.get("days"));
  state.days = [1, 3, 7, 30].includes(d) ? d : 7;
  state.imp = ["high", "mid", "all"].includes(p.get("imp")) ? p.get("imp") : "mid";
  const ks = (p.get("cat") || "").split(",").filter((k) => CAT[k]);
  state.cats = new Set(ks.length ? ks : CATS.map((c) => c.key));
  state.q = p.get("q") || "";
}
function writeHash() {
  const p = new URLSearchParams();
  if (state.days !== 7) p.set("days", state.days);
  if (state.imp !== "mid") p.set("imp", state.imp);
  if (state.cats.size !== CATS.length) p.set("cat", [...state.cats].join(","));
  if (state.q) p.set("q", state.q);
  history.replaceState(null, "", p.toString() ? `#${p}` : location.pathname + location.search);
}
const passImp = (x) => state.imp === "all" || x.importance === "높음" || (state.imp === "mid" && x.importance === "보통");
const passCat = (x) => state.cats.has(x.category || "기타");
const passQ = (x) => !state.q || [mainText(x), x.title, x.body, x.repo, x.importance_reason, x.version]
  .some((v) => v && String(v).toLowerCase().includes(state.q.toLowerCase()));

// ======================= 상단 신선도 =======================
function renderFresh() {
  const box = document.getElementById("fresh");
  const last = parseIso(cache.index?.last_collected_at);
  const stale = !last || Date.now() - last >= 24 * 3600e3;
  const failed = Object.values(cache.health?.steps || {}).filter((v) => v.status === "fail").length;
  box.className = `fresh ${stale || failed ? "is-stale" : "is-fresh"}`;
  box.querySelector(".fresh-text").replaceChildren(stale ? "업데이트 지연 · " : "", el("strong", { text: last ? `${hm(last)} 업데이트` : "데이터 없음" }), last ? ` · ${rel(last)}` : "");
  box.title = `마지막 수집 ${fmtKst(last)} (한국시간)${stale ? "\n24시간 넘게 갱신되지 않았어요" : ""}${failed ? `\n수집 실패 단계 ${failed}개` : ""}`;
}

// ======================= 히어로 =======================
function leadSentence(items) {
  const high = items.filter((x) => x.importance === "높음");
  const cc = new Set(items.filter((x) => x.type === "claude_code_change").map((x) => x.version));
  const launches = items.filter((x) => /새 모델·제품 출시/.test(x.headline_ko || ""));
  const names = [...new Set(launches.map((x) => (x.headline_ko.split(" · ")[1] || "").trim()).filter(Boolean))];
  const breaking = items.filter((x) => /호환성 주의|지원 중단|동작 변경|제거/.test(x.headline_ko || "") && x.importance === "높음").length;
  const parts = [];
  if (names.length) parts.push([el("b", { text: names.slice(0, 2).join(", ") }), " 출시 소식이 있고"]);
  if (cc.size) parts.push(["Claude Code가 ", el("b", { text: `${cc.size}개 버전` }), " 업데이트됐어요"]);
  const frag = document.createDocumentFragment();
  if (!items.length) { frag.append("이 기간에는 새로 수집된 소식이 없어요. 기간을 넓혀 보세요."); return frag; }
  parts.forEach((p, i) => { frag.append(...p, i < parts.length - 1 ? " " : ". "); });
  frag.append("내 관심사와 맞닿은 중요한 변화는 ", el("b", { text: `${high.length}건` }), breaking ? `, 그중 기존 사용법이 바뀌는 변경이 ${breaking}건이에요.` : "이에요.");
  return frag;
}
function renderHero(items, r) {
  const now = new Date(), p = kp(now);
  document.getElementById("hero-date").textContent = `${p.m}월 ${p.d}일 ${"일월화수목금토"[p.w]}요일 · ${r.label}`;
  document.getElementById("hero-title").textContent = state.days === 1 ? "오늘의 브리핑" : `${r.label} 브리핑`;
  document.getElementById("hero-lead").replaceChildren(leadSentence(items));
  const high = items.filter((x) => x.importance === "높음").length;
  const cc = new Set(items.filter((x) => x.type === "claude_code_change").map((x) => x.version)).size;
  const official = items.filter((x) => x.type === "official_release_note" || x.type === "official_post").length;
  const latest = ((cache.health?.steps?.claude_code?.detail || "").match(/latest=([\d.]+)/) || [])[1];
  const stats = [
    { n: high, label: "중요한 변화" },
    { n: cc, unit: "개", label: "Claude Code 버전", note: latest ? `최신 ${latest}` : null },
    { n: official, unit: "건", label: "공식 발표" },
    { n: items.length, unit: "건", label: "수집된 소식" },
  ];
  const box = document.getElementById("stats");
  box.classList.remove("is-revealed");
  box.replaceChildren(...stats.map((s) => el("div", { class: "stat" },
    el("dt", { text: s.label }), el("dd", {}, el("span", { "data-count": s.n, text: reduce.matches ? s.n : "0" }), s.unit ? el("small", { text: s.unit }) : null),
    s.note ? el("span", { class: "stat-note", text: s.note }) : null)));
  const play = document.getElementById("play-btn");
  play.disabled = !items.length;
  const top3 = pickTop(items, 3);
  document.getElementById("hero-side").replaceChildren(el("div", { class: "spot" },
    el("div", { class: "spot-head" }, el("b", { text: "지금 주목할 소식" }), el("span", { text: r.label })),
    top3.length ? el("ol", {}, top3.map((x) => el("li", {}, link(safeUrl(x.url), mainText(x), "t"),
      el("span", { class: "w", title: x.importance_reason || "", text: friendlyWhy(x.importance_reason) || kicker(x) }))))
      : el("p", { class: "muted", text: "이 기간에는 특별히 중요한 소식이 없어요." })));
}

// ======================= 한눈에 보기 =======================
function pickTop(items, n = 5) {
  const per = {}, out = [];
  for (const x of items.filter((y) => y.importance === "높음" && !y.quarantined).sort(sortItems)) {
    const t = x.type === "claude_code_change" ? "cc" : x.type;
    if ((per[t] = (per[t] || 0) + 1) > 2) continue;   // 한 종류가 독차지하지 않게 (종류당 최대 2)
    out.push(x);
    if (out.length === n) break;
  }
  return out;
}
function renderGlance(items) {
  const top = pickTop(items);
  const ol = document.getElementById("glance-list");
  document.getElementById("glance-sub").textContent = top.length ? "내 관심사 기준으로 가장 중요한 소식이에요" : "";
  if (!top.length) { ol.replaceChildren(stateRow("지금은 특별히 중요한 소식이 없어요.", "기간을 넓히거나 아래 전체 목록을 보세요.", "inbox")); return; }
  ol.replaceChildren(...top.map((x) => el("li", {},
    el("div", { class: "g-main" },
      link(safeUrl(x.url), mainText(x), "g-title"),
      x.importance_reason ? el("div", { class: "g-why", title: `판정 근거: ${x.importance_reason}`, text: `왜 중요? ${friendlyWhy(x.importance_reason)}` }) : null,
      el("div", { class: "g-meta" }, catTag(x), kicker(x) ? el("span", { text: kicker(x) }) : null,
        x.published_at ? el("span", { text: `${mdKo(parseIso(x.published_at))} 발표` }) : null, aiMark(x)),
      origLine(x)))));
}
function stateRow(msg, hint, ic = "inbox") {
  return el("li", { class: "state" }, el("span", { class: "state-icon" }, icon(ic, 20)), el("span", {}, msg, hint ? el("small", { text: hint }) : null));
}

// ======================= digest =======================
function parseFront(t) {
  const meta = {}; let body = t;
  const m = t.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?/);
  if (m) { body = t.slice(m[0].length); for (const l of m[1].split(/\r?\n/)) { const kv = l.match(/^([\w-]+):\s*(.*)$/); if (kv) meta[kv[1]] = kv[2].replace(/^["']|["']$/g, ""); } }
  return { meta, body };
}
function markdown(src) {
  const root = el("div", { class: "digest-body" });
  let list = null;
  const inline = (s) => {
    const f = document.createDocumentFragment();
    const rx = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\[([^\]]+)\]\((\S+?)\))|(https?:\/\/[^\s)<>]+)/g;
    let last = 0, m;
    while ((m = rx.exec(s))) {
      if (m.index > last) f.append(s.slice(last, m.index));
      if (m[1]) f.append(el("code", { text: m[1].slice(1, -1) }));
      else if (m[2]) f.append(el("strong", { text: m[2].slice(2, -2) }));
      else if (m[3]) f.append(link(safeUrl(m[5]), m[4]));
      else f.append(link(safeUrl(m[6]), m[6]));
      last = rx.lastIndex;
    }
    if (last < s.length) f.append(s.slice(last));
    return f;
  };
  for (const raw of src.split(/\r?\n/)) {
    const line = raw.trimEnd(), h = line.match(/^(#{1,3})\s+(.*)$/), li = line.match(/^\s*(?:[-*]|\d+\.)\s+(.*)$/);
    if (!li) list = null;
    if (!line.trim()) continue;
    if (h) root.append(el(`h${h[1].length}`, {}, inline(h[2])));
    else if (/^-{3,}$/.test(line.trim())) root.append(el("hr"));
    else if (li) { if (!list) root.append(list = el(/^\s*\d+\./.test(line) ? "ol" : "ul")); list.append(el("li", {}, inline(li[1]))); }
    else root.append(el("p", {}, inline(line)));
  }
  return root;
}
function renderDigest() {
  const box = document.getElementById("digest"), dg = cache.digest;
  box.hidden = false;
  if (!dg) {
    box.replaceChildren(el("div", { class: "digest-empty" }, icon("doc", 20), el("div", {},
      el("strong", { text: "AI 요약은 아직 없어요." }), " PC에서 ", el("code", { text: "/brief" }),
      "를 실행해 저장하면 여기에 Claude가 쓴 요약이 나타나요. 그때 번역도 함께 갱신돼요.")));
    return;
  }
  const { meta, body } = parseFront(dg.text), gen = parseIso(meta.generated_at);
  const btn = el("button", { class: "btn-text", type: "button", "aria-expanded": "false", text: "전체 요약 보기" });
  btn.addEventListener("click", () => { const open = !box.classList.toggle("collapsed"); btn.setAttribute("aria-expanded", open); btn.textContent = open ? "접기" : "전체 요약 보기"; });
  box.classList.add("collapsed");
  box.replaceChildren(el("div", { class: "digest-meta" }, el("span", { class: "ai-mark", text: "AI 요약" }),
    el("span", { text: `${dg.date}${gen ? ` ${hm(gen)}` : ""} 작성` }), meta.model ? el("span", { text: meta.model }) : null), markdown(body), btn);
}

// ======================= 흐름 =======================
function renderPulse(items14) {
  const fig = document.getElementById("pulse-chart");
  fig.querySelectorAll("svg, .tooltip").forEach((n) => n.remove());
  const days = [...Array(14)].map((_, i) => kstDate(new Date(Date.now() - (13 - i) * DAY)));
  const cnt = Object.fromEntries(days.map((d) => [d, 0]));
  for (const x of items14) { const d = kstDate(parseIso(x.published_at) || parseIso(x.collected_at)); if (d in cnt) cnt[d]++; }
  const v = days.map((d) => cnt[d]), peak = Math.max(...v, 1);
  document.getElementById("pulse-note").textContent = Math.max(...v) ? `가장 많았던 날 ${days[v.indexOf(Math.max(...v))].slice(5).replace("-", "/")} · ${Math.max(...v)}건` : "아직 데이터가 적어요";
  const W = 720, H = 170, L = 6, R = 12, T = 14, B = 24;
  const x = (i) => L + (i / 13) * (W - L - R), y = (n) => T + (1 - n / peak) * (H - T - B);
  let d = `M${x(0)},${y(v[0])}`;
  for (let i = 1; i < 14; i++) { const cx = (x(i - 1) + x(i)) / 2; d += ` C${cx},${y(v[i - 1])} ${cx},${y(v[i])} ${x(i)},${y(v[i])}`; }
  const accent = cssVar("--accent");
  const s = svg("svg", { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", role: "img", tabindex: 0,
    "aria-label": `최근 14일 일별 발표량: ${days.map((dd, i) => `${dd.slice(5)} ${v[i]}건`).join(", ")}` },
    svg("defs", {}, svg("linearGradient", { id: "pulse-grad", x1: 0, x2: 0, y1: 0, y2: 1 },
      svg("stop", { offset: "0", "stop-color": accent, "stop-opacity": 0.18 }), svg("stop", { offset: "1", "stop-color": accent, "stop-opacity": 0 }))),
    ...[0.5, 1].map((f) => svg("line", { class: "grid-line", x1: L, x2: W - R, y1: T + (1 - f) * (H - T - B), y2: T + (1 - f) * (H - T - B) })),
    svg("line", { class: "grid-line", x1: L, x2: W - R, y1: H - B, y2: H - B }),
    svg("path", { class: "pulse-area", d: `${d} L${x(13)},${H - B} L${x(0)},${H - B} Z` }),
    svg("path", { class: "pulse-line", d, pathLength: 1 }),
    svg("circle", { class: "pulse-halo", cx: x(13), cy: y(v[13]), r: 5 }),
    svg("circle", { class: "pulse-dot", cx: x(13), cy: y(v[13]), r: 5 }),
    ...[0, 7, 13].map((i) => svg("text", { class: "axis-text", x: x(i), y: H - 5, "text-anchor": i ? (i === 13 ? "end" : "middle") : "start" }, i === 13 ? "오늘" : days[i].slice(5).replace("-", "/"))));
  const cross = svg("line", { class: "cross", y1: T, y2: H - B, visibility: "hidden" });
  s.append(cross, svg("rect", { class: "hit", x: 0, y: 0, width: W, height: H }));
  const tip = el("div", { class: "tooltip", role: "status" }); tip.hidden = true;
  let cur = 13;
  const show = (i) => {
    cur = Math.max(0, Math.min(13, i));
    cross.setAttribute("x1", x(cur)); cross.setAttribute("x2", x(cur)); cross.setAttribute("visibility", "visible");
    tip.replaceChildren(el("div", { class: "t-date", text: days[cur].slice(5).replace("-", "월 ") + "일" }), el("strong", { text: `${v[cur]}건` }));
    tip.hidden = false;
    const b = s.getBoundingClientRect();
    tip.style.left = `${Math.min(Math.max((x(cur) / W) * b.width + 12, 0), b.width - 120)}px`; tip.style.top = "40px";
  };
  const hide = () => { cross.setAttribute("visibility", "hidden"); tip.hidden = true; };
  s.addEventListener("pointermove", (e) => { const b = s.getBoundingClientRect(); show(Math.round(((e.clientX - b.left) / b.width) * 13)); });
  s.addEventListener("pointerleave", hide); s.addEventListener("focus", () => show(13)); s.addEventListener("blur", hide);
  s.addEventListener("keydown", (e) => { if (e.key === "ArrowLeft") show(cur - 1); if (e.key === "ArrowRight") show(cur + 1); });
  fig.append(s, tip);
}
function renderRank(items) {
  const ul = document.getElementById("cat-rank");
  const base = items.filter((x) => passImp(x) && passQ(x));
  const rows = CATS.map((c) => ({ ...c, n: base.filter((x) => (x.category || "기타") === c.key).length })).sort((a, b) => b.n - a.n);
  const max = Math.max(1, ...rows.map((r) => r.n));
  ul.replaceChildren(...rows.map((r) => {
    const li = el("li", { class: state.cats.size !== CATS.length && !state.cats.has(r.key) ? "is-off" : "" });
    const btn = el("button", { type: "button", "aria-label": `${r.key} ${r.n}건 — 누르면 전체 목록을 이 분류로 거르기`, "aria-pressed": String(state.cats.size !== CATS.length && state.cats.has(r.key)) },
      el("span", { class: "r-name" }, el("i", { class: `dot ${r.cls}`, "aria-hidden": "true" }), r.key), el("span", { class: "r-val", text: `${r.n}건` }));
    btn.addEventListener("click", () => { toggleCat(r.key); document.getElementById("h-all").scrollIntoView({ behavior: reduce.matches ? "auto" : "smooth" }); });
    const bar = el("span", { class: "r-bar" }, el("span"));
    bar.firstChild.style.setProperty("--w", `${(r.n / max) * 100}%`);
    li.append(btn, bar);
    return li;
  }));
}

// ======================= Claude Code 버전 카드 =======================
function verbOf(x) { const k = kicker(x); return k.replace(/\(.*\)/, "").trim() || "변경"; }
function renderVersions(items) {
  const box = document.getElementById("cc-versions");
  const cc = items.filter((x) => x.type === "claude_code_change");
  const by = new Map();
  cc.forEach((x) => { if (!by.has(x.version)) by.set(x.version, []); by.get(x.version).push(x); });
  const vkey = (v) => (v || "0").split(".").map((n) => n.padStart(5, "0")).join(".");
  const vers = [...by.keys()].sort((a, b) => vkey(b).localeCompare(vkey(a)));
  const latest = ((cache.health?.steps?.claude_code?.detail || "").match(/latest=([\d.]+)/) || [])[1];
  document.getElementById("cc-sub").textContent = vers.length ? `${vers.length}개 버전 · 변경 ${cc.length}건${latest ? ` · 최신 ${latest}` : ""}` : "이 기간에는 새 버전이 없어요";
  if (!vers.length) { box.replaceChildren(el("ul", { class: "list" }, stateRow("이 기간에 Claude Code 새 버전이 없어요.", "기간을 30일로 넓혀 보세요.", "inbox"))); return; }
  box.replaceChildren(...vers.map((v) => {
    const list = by.get(v).sort(sortItems);
    const pub = parseIso(list[0].published_at);
    const counts = {};
    list.forEach((x) => { const k = verbOf(x); counts[k] = (counts[k] || 0) + 1; });
    const order = ["새 기능", "동작 변경", "제거", "지원 중단 예고", "개선", "버그 수정"];
    const pills = Object.entries(counts).sort(([a], [b]) => (order.indexOf(a) + 99) % 99 - (order.indexOf(b) + 99) % 99);
    const top = list.filter((x) => x.importance !== "낮음").slice(0, 4);
    const ul = el("ul", { class: "v-list" }, (top.length ? top : list.slice(0, 3)).map((x) => vItem(x)));
    const card = el("article", { class: "version" },
      el("div", { class: "v-head" }, el("span", { class: "v-num", text: v }), el("span", { class: "v-date", text: pub ? `${mdKo(pub)} 배포` : "" })),
      el("div", { class: "v-counts" }, pills.map(([k, n]) => el("span", { class: `v-pill ${k === "새 기능" || k === "동작 변경" ? "hl" : ""}`, text: `${k} ${n}` }))),
      ul);
    if (list.length > ul.children.length) {
      const more = el("button", { class: "btn-text v-more", type: "button", text: `전체 ${list.length}건 보기` });
      more.addEventListener("click", () => { ul.replaceChildren(...list.map((x) => vItem(x))); more.remove(); });
      card.append(more);
    }
    return card;
  }));
}
function vItem(x) {
  return el("li", { class: x.importance === "높음" ? "is-high" : "" }, link(safeUrl(x.url), koOf(x) || x.title, "v-text"),
    koOf(x) ? null : el("span", { class: "orig", text: kicker(x) }));
}

// ======================= 공식 소식 · 생태계 =======================
function renderOfficial(items) {
  const list = items.filter((x) => OFFICIAL.has(x.type) && passImp(x)).sort(sortItems).slice(0, 12);
  const ul = document.getElementById("official-list");
  ul.replaceChildren(...(list.length ? list.map((x) => el("li", {},
    el("div", { class: "n-kicker" }, el("span", { text: kicker(x) || "공식 소식" }), x.published_at ? el("span", { text: mdKo(parseIso(x.published_at)) }) : null, aiMark(x)),
    link(safeUrl(x.url), mainText(x), "n-title"), origLine(x))) : [stateRow("이 기간에 공식 소식이 없어요.", "기간을 넓혀 보세요.")]));
}
function renderEco(items) {
  const m = cache.metrics?.repos || {};
  const list = items.filter((x) => ECO.has(x.type) && x.importance !== "낮음" && !x.quarantined).sort(sortItems).slice(0, 9);
  const grid = document.getElementById("eco-grid");
  grid.replaceChildren(...(list.length ? list.map((x) => {
    const [owner, name] = (x.repo || "/").split("/");
    const r = m[x.repo] || {};
    const desc = koOf(x) || (x.body && !x.body.startsWith("[격리됨") ? x.body : "");
    return el("article", { class: "eco" },
      el("span", { class: "eco-kicker", text: kicker(x) }),
      el("a", { class: "eco-name", href: safeUrl(`https://github.com/${x.repo}`), rel: "noopener noreferrer", target: "_blank" }, el("span", { class: "owner", text: `${owner}/` }), name),
      desc ? el("p", { class: "eco-desc", text: desc }) : null,
      el("div", { class: "eco-foot" }, r.stars ? el("span", { text: `★ ${compact(r.stars)}` }) : null,
        r.d1 ? el("span", { class: "up", text: `${signed(r.d1)} 오늘` }) : null, aiMark(x),
        (r.warnings || []).length ? el("span", { class: "warn" }, icon("alert", 13), "참고 경고") : null));
  }) : [el("ul", { class: "list" }, stateRow("이 기간에 눈에 띄는 저장소가 없어요.", "기간을 넓혀 보세요."))]));
}

// ======================= AI 코딩 벤치마크 =======================
/** 'claude-opus-5-5_max' → { name: 'Claude Opus 5.5', effort: 'max' } */
function prettyModel(raw) {
  const [base, effort] = String(raw).split("_");
  const words = base.replace(/-(\d{8})$/, "").split("-");
  const out = [];
  for (let i = 0; i < words.length; i++) {
    const w = words[i];
    if (/^\d+$/.test(w) && /^\d+$/.test(words[i + 1] || "") && words[i + 1].length <= 2) { out.push(`${w}.${words[++i]}`); continue; }
    out.push(/^(gpt|glm|ai)$/i.test(w) ? w.toUpperCase() : w.charAt(0).toUpperCase() + w.slice(1));
  }
  return { name: out.join(" ").replace(/^GPT /, "GPT-"), effort: effort || "" };
}
const isClaude = (s) => /claude|opus|sonnet|haiku|fable/i.test(s);
function benchCard(title, measures, rows, unit, foot) {
  const max = Math.max(...rows.map((r) => r.score));
  const min = unit === "점" ? Math.min(...rows.map((r) => r.score)) * 0.9 : 0;   // Elo 점수는 차이가 보이게 바닥을 올린다
  return el("article", { class: "bench" },
    el("div", { class: "bench-head" }, el("h3", { text: title }), el("p", { text: measures })),
    el("ol", { class: "bars" }, rows.map((r) => {
      const li = el("li", { class: isClaude(r.name) ? "is-claude" : "" },
        el("span", { class: "b-name", title: r.title || r.name }, r.name, r.sub ? el("small", { text: r.sub }) : null),
        el("span", { class: "b-val", text: `${r.score}${unit === "%" ? "%" : ""}` }),
        el("span", { class: "b-bar" }, el("span")));
      li.querySelector(".b-bar span").style.setProperty("--w", `${Math.max(2, ((r.score - min) / (max - min || 1)) * 100)}%`);
      return li;
    })),
    el("p", { class: "bench-foot", text: foot }));
}
async function renderBench() {
  const [tb, ep] = await Promise.all([getJSON("data/benchmarks/terminal_bench.json").catch(() => null),
    getJSON("data/benchmarks/epoch.json").catch(() => null)]);
  const grid = document.getElementById("bench-grid"), cards = [];
  if (tb?.rows?.length) {
    cards.push(benchCard("Terminal-Bench 2.1", `${tb.measures} — 모델 + 에이전트 조합`,
      tb.rows.slice(0, 8).map((r) => ({ name: r.model, sub: `${r.agent}${r.effort ? ` · ${r.effort}` : ""}`, score: r.accuracy,
        title: `${r.model} + ${r.agent} (${r.effort}) ${r.accuracy}% ±${r.stderr} · ${r.date} · 실행 비용 $${r.cost_usd}` })),
      "%", `가장 최근 측정 ${tb.rows.map((r) => r.date).sort().pop()} · 모델 ${tb.rows.length}개 · 모델별 최고 기록`));
  }
  for (const s of ep?.sets || []) {
    if (!s.top?.length) continue;
    const latest = s.top.map((x) => x.released).filter(Boolean).sort().pop();
    cards.push(benchCard(s.benchmark, s.measures, s.top.slice(0, 8).map((x) => {
      const p = prettyModel(x.model);
      return { name: p.name, sub: [p.effort, x.org].filter(Boolean).join(" · "), score: x.score, title: `${x.model} · ${x.org} · 출시 ${x.released} ${x.extra}` };
    }), s.unit, `목록 중 가장 최근 모델 출시 ${latest || "—"} · 모델 ${s.models}개 중 상위 8`));
  }
  grid.replaceChildren(...(cards.length ? cards : [el("ul", { class: "list" }, stateRow("벤치마크 데이터가 아직 없어요.", "다음 수집 때 채워져요."))]));
  const credits = [];
  if (tb) credits.push(`Terminal-Bench 2.1 (harbor-framework, Apache-2.0)`);
  if (ep) credits.push(`${ep.attribution || "Data: Epoch AI, CC BY 4.0"}`);
  document.getElementById("bench-credit").textContent = credits.length
    ? `출처: ${credits.join(" · ")} · 확인 ${fmtKst(parseIso(ep?.checked_at || tb?.checked_at))}. 같은 모델이라도 추론 강도·에이전트에 따라 점수가 다르며, 여기서는 모델별 최고 기록만 보여 줘요.` : "";
  const sec = grid.closest("[data-reveal]");
  if (sec?.classList.contains("is-drawn")) { sec.classList.remove("is-drawn"); requestAnimationFrame(() => requestAnimationFrame(() => sec.classList.add("is-drawn"))); }
}

// ======================= 관심 저장소 =======================
function spark(vals) {
  const pts = vals.map((v, i) => [i, v]).filter(([, v]) => v != null);
  if (pts.length < 2) return el("span", { class: "spark-empty", text: `이력 ${pts.length}일` });
  const W = 100, H = 26, P = 3, ys = pts.map(([, v]) => v), mn = Math.min(...ys), mx = Math.max(...ys);
  const x = (i) => P + (i / (vals.length - 1)) * (W - 2 * P), y = (v) => (mx === mn ? H / 2 : P + (1 - (v - mn) / (mx - mn)) * (H - 2 * P));
  const [li, lv] = pts[pts.length - 1];
  return svg("svg", { class: "spark", viewBox: `0 0 ${W} ${H}`, width: "100%", height: H, "aria-hidden": "true" },
    svg("path", { d: pts.map(([i, v], k) => `${k ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("") }), svg("circle", { cx: x(li), cy: y(lv), r: 2.6 }));
}
function renderWatch() {
  const m = cache.metrics || { repos: {} }, s = cache.series || { dates: [], repos: {} };
  const box = document.getElementById("watch");
  const core = Object.entries(m.repos || {}).filter(([, r]) => r.tier === "core").sort(([, a], [, b]) => (b.d7 ?? b.d1 ?? 0) - (a.d7 ?? a.d1 ?? 0) || b.stars - a.stars);
  const hist = s.dates.length;
  document.getElementById("watch-sub").textContent = `핵심 ${core.length}개 · 별 이력 ${hist}일째 (매일 하루씩 쌓여요)`;
  const parts = [];
  if (hist < 4) {
    const w = el("div", { class: "wait" }, el("p", {}, el("b", { text: `별 추이 그래프까지 ${4 - hist}일` }), ` 남았어요 (${hist}/4일).`), el("div", { class: "bar" }, el("span")));
    w.querySelector(".bar span").style.setProperty("--w", `${(hist / 4) * 100}%`);
    parts.push(w);
  }
  const table = (list) => el("div", { class: "table-scroll" }, el("table", { class: "tbl" },
    el("colgroup", {}, el("col"), el("col", { class: "col-num" }), el("col", { class: "col-num" }), el("col", { class: "col-num hide-sm" }), el("col", { class: "col-spark" })),
    el("thead", {}, el("tr", {}, el("th", { text: "저장소" }), el("th", { class: "num", text: "별" }), el("th", { class: "num", text: "1일" }), el("th", { class: "num hide-sm", text: "7일" }), el("th", { text: "추이" }))),
    el("tbody", {}, list.map(([n, r]) => { const [o, nm] = n.split("/");
      return el("tr", {}, el("td", { class: "name" }, el("a", { href: safeUrl(`https://github.com/${n}`), rel: "noopener noreferrer", target: "_blank" }, el("span", { class: "owner", text: `${o}/` }), nm)),
        el("td", { class: "num", text: compact(r.stars) }), el("td", { class: `num ${r.d1 > 0 ? "up" : ""}`, text: signed(r.d1) }),
        el("td", { class: `num hide-sm ${r.d7 > 0 ? "up" : ""}`, text: signed(r.d7) }), el("td", {}, spark((s.repos[n] || []).slice(-30)))); }))));
  parts.push(table(core));
  const cand = Object.entries(m.repos || {}).filter(([, r]) => r.tier === "candidate").sort(([, a], [, b]) => (b.d7 ?? b.d1 ?? 0) - (a.d7 ?? a.d1 ?? 0) || b.stars - a.stars).slice(0, 10);
  if (cand.length) parts.push(el("details", { class: "more" }, el("summary", { text: `자동 추적 중인 후보 상위 ${cand.length}개` }), table(cand)));
  box.replaceChildren(...parts);
  if (box.classList.contains("is-drawn")) { box.classList.remove("is-drawn"); requestAnimationFrame(() => requestAnimationFrame(() => box.classList.add("is-drawn"))); }
}

// ======================= 전체 목록 =======================
function renderAll(items) {
  const list = items.filter((x) => passImp(x) && passCat(x) && passQ(x)).sort(sortItems);
  document.getElementById("all-sub").textContent = `${list.length}건 · 중요도·분류·검색으로 거를 수 있어요`;
  const ul = document.getElementById("all-list");
  ul.replaceChildren(...(list.length ? list.slice(0, state.allLimit).map((x) => el("li", { class: `row ${x.importance === "낮음" ? "is-low" : ""} ${x.quarantined ? "is-quarantined" : ""}` },
    link(safeUrl(x.url), mainText(x), "row-title"),
    el("div", { class: "row-meta" }, x.importance === "높음" ? el("span", { class: "imp-high", text: "중요" }) : null, catTag(x),
      el("span", { text: kicker(x) }), x.published_at ? el("span", { text: mdKo(parseIso(x.published_at)) }) : null, aiMark(x)),
    origLine(x))) : [stateRow("조건에 맞는 소식이 없어요.", "검색어를 지우거나 필터를 넓혀 보세요.")]));
  const more = document.getElementById("all-more");
  more.replaceChildren(list.length > state.allLimit ? el("button", { class: "btn-text", type: "button", text: `${list.length - state.allLimit}건 더 보기`,
    onclick: () => { state.allLimit += 30; renderAll(items); } }) : "");
}
function buildChips(items) {
  const box = document.getElementById("f-cat");
  const base = items.filter((x) => passImp(x) && passQ(x));
  if (!box.children.length) CATS.forEach((c) => {
    const b = el("button", { class: "chip", type: "button", "data-key": c.key }, el("i", { class: `dot ${c.cls}`, "aria-hidden": "true" }), c.key, el("span", { class: "count" }));
    b.addEventListener("click", () => toggleCat(c.key));
    box.append(b);
  });
  box.querySelectorAll(".chip").forEach((b) => {
    b.setAttribute("aria-pressed", String(state.cats.size !== CATS.length && state.cats.has(b.dataset.key)));
    b.querySelector(".count").textContent = base.filter((x) => (x.category || "기타") === b.dataset.key).length;
  });
}
function toggleCat(k) {
  if (state.cats.size === CATS.length) state.cats = new Set([k]);
  else if (state.cats.has(k)) { state.cats.delete(k); if (!state.cats.size) state.cats = new Set(CATS.map((c) => c.key)); }
  else state.cats.add(k);
  state.allLimit = 30;
  render();
}

// ======================= 1분 브리핑 (영상처럼) =======================
const story = { slides: [], i: 0, timer: 0, t0: 0, paused: false, dur: 6500, raf: 0, last: null };
/** 오른쪽 시각 패널용 정보 카드 (넓은 화면에서만 보임) */
function sideCard(rows, extra) {
  return el("div", { class: "s-card" }, extra || null,
    el("dl", { class: "s-rows" }, rows.filter(([, v]) => v).map(([k, v]) => el("div", {}, el("dt", { text: k }), el("dd", {}, v)))));
}
function buildSlides(items) {
  const r = range(), p = kp(new Date());
  const high = items.filter((x) => x.importance === "높음");
  const cc = items.filter((x) => x.type === "claude_code_change");
  const vers = [...new Set(cc.map((x) => x.version))].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
  const top = pickTop(items, 6);
  const slides = [];
  slides.push({ tint: "rgba(41,151,255,.34)",
    main: () => [
      el("span", { class: "s-kicker", text: `${p.m}월 ${p.d}일 ${"일월화수목금토"[p.w]}요일 · ${r.label}` }),
      el("h2", { class: "s-title huge", text: state.days === 1 ? "오늘의 브리핑" : `${r.label} 브리핑` }),
      el("p", { class: "s-body" }, leadSentence(items)),
      el("div", { class: "s-stats" }, [[high.length, "중요한 변화"], [vers.length, "Claude Code 버전"], [items.length, "수집된 소식"]]
        .map(([n, l]) => el("div", {}, el("b", { "data-count": n, text: "0" }), el("span", { text: l })))),
      el("span", { class: "s-hint", text: "화면을 누르면 다음으로 · 누르고 있으면 멈춤 · ← → 키" })],
    side: () => el("div", { class: "s-card" }, el("p", { class: "s-card-title", text: "오늘 다룰 내용" }),
      el("ol", { class: "s-agenda" }, top.slice(0, 5).map((x) => el("li", {}, el("i", { class: `dot ${(CAT[x.category] || CAT["기타"]).cls}`, "aria-hidden": "true" }), el("span", { text: mainText(x) }))))) });
  top.forEach((x, k) => {
    const c = CAT[x.category] || CAT["기타"];
    const why = friendlyWhy(x.importance_reason);
    slides.push({ tint: `color-mix(in srgb, ${cssVar(`--${c.cls}`)} 40%, transparent)`, solid: cssVar(`--${c.cls}`),
      main: () => [
        el("span", { class: "s-kicker" }, el("i", { class: `dot ${c.cls}`, "aria-hidden": "true" }), `중요 ${k + 1} · ${kicker(x) || x.category}`),
        el("h2", { class: "s-title", text: mainText(x) }),
        why ? el("p", { class: "s-body s-why", title: x.importance_reason || "" }, el("b", { text: "왜 중요? " }), why) : null,
        x.title && mainText(x) !== x.title ? el("p", { class: "s-orig", text: `원문 · ${x.title.slice(0, 200)}${x.title.length > 200 ? "…" : ""}` }) : null,
        safeUrl(x.url) ? el("a", { class: "s-link", href: safeUrl(x.url), rel: "noopener noreferrer", target: "_blank" }, "원문 보기", icon("arrow", 16)) : null].filter(Boolean),
      side: () => sideCard([
        ["분류", el("span", { class: "s-cat" }, el("i", { class: `dot ${c.cls}`, "aria-hidden": "true" }), x.category || "기타")],
        ["중요도", x.importance], ["종류", kicker(x)],
        ["발표", x.published_at ? `${mdKo(parseIso(x.published_at))}` : null],
        ["버전", x.version && x.type === "claude_code_change" ? `Claude Code ${x.version}` : null],
        ["저장소", x.repo && x.type !== "claude_code_change" ? x.repo : null],
        ["문장", cache.ko.get(x.id)?.classified_by === "mt" ? "기계 번역" : koOf(x) ? "AI 번역" : "규칙 요약 (원문은 영어)"]], el("span", { class: "s-num", "aria-hidden": "true", text: String(k + 1).padStart(2, "0") })) });
  });
  if (vers.length) {
    const tops = cc.filter((x) => x.importance === "높음").sort(sortItems).slice(0, 4);
    const byVer = vers.slice().reverse().slice(0, 6).map((v) => {
      const list = cc.filter((x) => x.version === v);
      return { v, n: list.length, hi: list.filter((x) => x.importance === "높음").length, pub: parseIso(list[0]?.published_at) };
    });
    slides.push({ tint: "rgba(42,120,214,.32)",
      main: () => [
        el("span", { class: "s-kicker", text: "Claude Code 업데이트" }),
        el("h2", { class: "s-title", text: vers.length > 1 ? `${vers[0]} → ${vers[vers.length - 1]}` : vers[0] }),
        el("p", { class: "s-body", text: `${vers.length}개 버전, 변경 ${cc.length}건. 그중 내게 중요한 것:` }),
        el("ul", { class: "s-list" }, (tops.length ? tops : cc.slice(0, 3)).map((x) => el("li", { text: koOf(x) || x.headline_ko || x.title })))],
      side: () => el("div", { class: "s-card" }, el("p", { class: "s-card-title", text: "버전별 변경" }),
        el("ol", { class: "s-timeline" }, byVer.map((b) => el("li", {},
          el("b", { text: b.v }), el("span", { text: `${b.pub ? mdKo(b.pub) : ""} · ${b.n}건${b.hi ? ` · 중요 ${b.hi}` : ""}` }))))) });
  }
  const off = items.filter((x) => x.type === "official_release_note" && x.importance === "높음").sort(sortItems).slice(0, 4);
  if (off.length) slides.push({ tint: "rgba(27,175,122,.30)",
    main: () => [el("span", { class: "s-kicker", text: "새 모델 · 공식 발표" }), el("h2", { class: "s-title", text: "Anthropic이 발표한 것" }),
      el("ul", { class: "s-list" }, off.map((x) => el("li", { text: mainText(x) })))],
    side: () => sideCard([["출처", "Claude 플랫폼·앱 릴리스 노트"], ["기간", r.label]],
      el("div", { class: "s-big" }, el("b", { "data-count": items.filter((x) => x.type === "official_release_note").length, text: "0" }), el("span", { text: "건의 공식 발표" }))) });
  const eco = items.filter((x) => (x.type === "trending" || x.type === "candidate_new") && x.importance !== "낮음").sort(sortItems).slice(0, 4);
  const mr = cache.metrics?.repos || {};
  if (eco.length) slides.push({ tint: "rgba(235,104,52,.28)",
    main: () => [el("span", { class: "s-kicker", text: "생태계 트렌드" }), el("h2", { class: "s-title", text: "지금 GitHub에서 뜨는 것" }),
      el("ul", { class: "s-list" }, eco.map((x) => el("li", { text: koOf(x) || x.headline_ko || x.title })))],
    side: () => el("div", { class: "s-card" }, el("p", { class: "s-card-title", text: "저장소" }),
      el("ol", { class: "s-timeline" }, eco.map((x) => el("li", {}, el("b", { text: x.repo || "" }),
        el("span", { text: mr[x.repo]?.stars ? `★ ${compact(mr[x.repo].stars)}` : kicker(x) }))))) });
  slides.push({ tint: "rgba(255,255,255,.12)",
    main: () => [el("span", { class: "s-kicker", text: "끝" }), el("h2", { class: "s-title huge", text: "여기까지예요." }),
      el("p", { class: "s-body", text: "자세한 내용과 전체 목록은 페이지에서 볼 수 있어요." }),
      el("button", { class: "s-link", type: "button", onclick: closeStory }, "페이지로 돌아가기")] });
  return slides;
}
function openStory() {
  story.slides = buildSlides(cache.items);
  story.i = 0; story.paused = reduce.matches; story.last = document.activeElement;
  const box = document.getElementById("story");
  document.getElementById("story-bars").replaceChildren(...story.slides.map(() => el("span", {}, el("i"))));
  box.hidden = false;
  document.body.classList.add("story-open");
  setPauseIcon();
  showSlide(0);
  document.getElementById("story-close").focus();
}
function closeStory() {
  cancelAnimationFrame(story.raf);
  document.getElementById("story").hidden = true;
  document.body.classList.remove("story-open");
  story.last?.focus?.();
}
function showSlide(i) {
  if (i < 0) i = 0;
  if (i >= story.slides.length) { closeStory(); return; }
  story.i = i;
  const s = story.slides[i], box = document.getElementById("story");
  box.style.setProperty("--tint", s.tint);
  if (s.solid) box.style.setProperty("--tint-solid", s.solid); else box.style.removeProperty("--tint-solid");
  box.style.setProperty("--bx", `${20 + ((i * 37) % 60)}%`); box.style.setProperty("--by", `${15 + ((i * 23) % 50)}%`);
  const side = s.side ? s.side() : null;
  const slide = el("div", { class: `slide${side ? " has-side" : ""}` }, el("div", { class: "s-main" }, s.main()), side ? el("div", { class: "s-side" }, side) : null);
  document.getElementById("story-stage").replaceChildren(slide);
  slide.querySelectorAll("[data-count]").forEach((c) => countTo(c, Number(c.dataset.count)));
  document.querySelectorAll("#story-bars span").forEach((b, k) => { b.classList.toggle("done", k < i); b.firstChild.style.width = k < i ? "100%" : "0"; });
  story.t0 = performance.now(); story.elapsed = 0;
  tick();
}
function tick() {
  cancelAnimationFrame(story.raf);
  const bar = document.querySelectorAll("#story-bars i")[story.i];
  const loop = (now) => {
    if (document.getElementById("story").hidden) return;
    if (!story.paused) {
      const e = story.elapsed + (now - story.t0);
      bar.style.width = `${Math.min(100, (e / story.dur) * 100)}%`;
      if (e >= story.dur) { showSlide(story.i + 1); return; }
    }
    story.raf = requestAnimationFrame(loop);
  };
  story.raf = requestAnimationFrame(loop);
}
function setPaused(p) {
  if (p === story.paused) return;
  if (p) story.elapsed += performance.now() - story.t0; else story.t0 = performance.now();
  story.paused = p;
  setPauseIcon();
}
function setPauseIcon() {
  const b = document.getElementById("story-pause");
  b.replaceChildren(icon(story.paused ? "play" : "pause", 16));
  b.setAttribute("aria-label", story.paused ? "재생" : "일시정지");
}
function wireStory() {
  document.getElementById("play-btn").addEventListener("click", openStory);
  document.getElementById("story-close").replaceChildren(icon("close", 18));
  document.getElementById("story-close").addEventListener("click", closeStory);
  document.getElementById("story-pause").addEventListener("click", () => setPaused(!story.paused));
  document.getElementById("story-prev").addEventListener("click", () => showSlide(story.i - 1));
  document.getElementById("story-next").addEventListener("click", () => showSlide(story.i + 1));
  const stage = document.getElementById("story");
  let hold = 0, sx = 0;
  stage.addEventListener("pointerdown", (e) => { sx = e.clientX; hold = setTimeout(() => setPaused(true), 220); });
  stage.addEventListener("pointerup", (e) => {
    clearTimeout(hold);
    if (Math.abs(e.clientX - sx) > 60) showSlide(story.i + (e.clientX < sx ? 1 : -1));   // 스와이프
  });
  document.addEventListener("keydown", (e) => {
    if (stage.hidden) return;
    if (e.key === "Escape") closeStory();
    else if (e.key === "ArrowRight") showSlide(story.i + 1);
    else if (e.key === "ArrowLeft") showSlide(story.i - 1);
    else if (e.key === " ") { e.preventDefault(); setPaused(!story.paused); }
    else if (e.key === "Tab") {   // 대화상자 안에서만 포커스 이동
      const f = [...stage.querySelectorAll("button, a[href]")].filter((n) => n.offsetParent !== null);
      if (!f.length) return;
      if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
      else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
    }
  });
  document.addEventListener("visibilitychange", () => { if (document.hidden && !stage.hidden) setPaused(true); });
}

// ======================= 컨트롤 =======================
function wire() {
  document.querySelectorAll("#f-range button").forEach((b) => b.addEventListener("click", () => { state.days = +b.dataset.days; state.allLimit = 30; update(); }));
  document.querySelectorAll("#f-imp button").forEach((b) => b.addEventListener("click", () => { state.imp = b.dataset.imp; state.allLimit = 30; render(); }));
  const q = document.getElementById("f-q");
  q.value = state.q;
  let t;
  q.addEventListener("input", () => { clearTimeout(t); t = setTimeout(() => { state.q = q.value.trim(); state.allLimit = 30; render(); }, 180); });
  document.addEventListener("keydown", (e) => {
    if (e.key === "/" && document.getElementById("story").hidden && !/^(INPUT|TEXTAREA)$/.test(document.activeElement?.tagName)) { e.preventDefault(); q.focus(); }
  });
  const tb = document.getElementById("theme-toggle");
  const label = () => {
    const dark = document.documentElement.getAttribute("data-theme") === "dark";
    tb.replaceChildren(icon(dark ? "sun" : "moon", 18));
    tb.setAttribute("aria-label", dark ? "밝은 화면으로" : "어두운 화면으로");
  };
  tb.addEventListener("click", () => {
    const toDark = document.documentElement.getAttribute("data-theme") !== "dark";
    const apply = () => {
      if (toDark) document.documentElement.setAttribute("data-theme", "dark"); else document.documentElement.removeAttribute("data-theme");
      try { toDark ? localStorage.setItem("tw-theme", "dark") : localStorage.removeItem("tw-theme"); } catch { /* 저장소 차단 */ }
      label(); renderPulse(cache.items14 || []); document.getElementById("pulse-chart").classList.add("is-drawn");
    };
    if (document.startViewTransition && !reduce.matches) {
      const b = tb.getBoundingClientRect(), cx = b.left + b.width / 2, cy = b.top + b.height / 2, st = document.documentElement.style;
      st.setProperty("--vt-x", `${cx}px`); st.setProperty("--vt-y", `${cy}px`);
      st.setProperty("--vt-r", `${Math.hypot(Math.max(cx, innerWidth - cx), Math.max(cy, innerHeight - cy))}px`);
      document.startViewTransition(apply);
    } else apply();
  });
  label();
  const top = document.getElementById("topbar");
  const onScroll = () => top.classList.toggle("is-scrolled", scrollY > 4);
  addEventListener("scroll", onScroll, { passive: true }); onScroll();
  addEventListener("resize", () => document.querySelectorAll(".range, .seg").forEach(moveThumb));
  wireStory();
}
function syncPressed() {
  document.querySelectorAll("#f-range button").forEach((b) => b.setAttribute("aria-pressed", String(+b.dataset.days === state.days)));
  document.querySelectorAll("#f-imp button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.imp === state.imp)));
  document.querySelectorAll(".range, .seg").forEach(moveThumb);
}

// ======================= 렌더 =======================
function render() {
  writeHash(); syncPressed();
  const items = cache.items;
  buildChips(items); renderRank(items); renderAll(items);
  document.getElementById("live").textContent = `전체 목록 ${items.filter((x) => passImp(x) && passCat(x) && passQ(x)).length}건`;
}
let ticket = 0;
async function update() {
  const my = ++ticket;
  writeHash(); syncPressed();
  const r = range();
  const items = await loadItems(r);
  if (my !== ticket) return;
  cache.items = items;
  renderFresh(); renderHero(items, r); renderGlance(items); renderVersions(items);
  renderOfficial(items); renderEco(items); renderWatch(); render();
  document.querySelectorAll("#stats [data-count]").forEach((c) => { c.dataset.done = ""; });
  reveal(document.getElementById("stats"));
}
function renderError(err) {
  const file = location.protocol === "file:", st = +((String(err?.message).match(/HTTP (\d+)/) || [])[1]);
  const why = file ? ["파일로 직접 열었어요.", "폴더에서 python -m http.server 실행 후 http://localhost:8000 으로 열어 주세요."]
    : st === 404 ? ["아직 수집된 데이터가 없어요.", "첫 수집(매일 오전 6시 17분) 전이거나 GitHub Pages가 배포 중일 수 있어요."]
      : ["데이터에 연결하지 못했어요.", "인터넷 연결을 확인하고 잠시 후 다시 시도해 주세요."];
  const retry = el("button", { class: "btn btn-primary", type: "button", text: "다시 시도" });
  retry.addEventListener("click", () => location.reload());
  document.getElementById("main").replaceChildren(el("section", { class: "error-view", role: "alert" }, el("div", { class: "wrap" },
    el("p", { class: "eyebrow", text: "trend-watch" }),
    el("h1", {}, "신호가 잠시 끊겼어요.", el("br"), el("span", { class: "dim", text: why[0] })),
    el("p", { text: why[1] }),
    svg("svg", { class: "signal", viewBox: "0 0 520 90", preserveAspectRatio: "none", "aria-hidden": "true" },
      svg("path", { class: "flat", d: "M10 45 H200 L215 20 L232 72 L248 45 H500" }),
      svg("path", { class: "beat", d: "M10 45 H200 L215 20 L232 72 L248 45 H500", pathLength: 1 }),
      svg("circle", { class: "end", cx: 505, cy: 45, r: 5 })),
    el("div", { class: "hero-cta" }, retry, el("a", { class: "btn btn-ghost", href: "https://github.com/Glory-m/trend_check/actions/workflows/collect.yml", rel: "noopener noreferrer", target: "_blank", text: "수집 상태 보기" })),
    el("ul", {}, el("li", {}, el("b", { text: "매일 자동 수집" }), " — GitHub Actions가 매일 오전 6시 17분에 모아요."),
      el("li", {}, el("b", { text: "PC에서도 볼 수 있어요" }), " — 폴더에서 git pull 후 /brief 를 실행하세요.")))));
  const f = document.getElementById("fresh"); f.className = "fresh is-stale"; f.querySelector(".fresh-text").textContent = "연결 끊김";
}

// ======================= AI 비서 (로컬 서버에서만) =======================
// scripts/serve.py 가 /api/status 에 답할 때만 나타난다. GitHub Pages에서는 404라서 보이지 않는다.
const assist = { token: null, sid: null, model: "sonnet", ctrl: null, busy: false, opened: false };
const QUICK = [
  ["마지막 확인 이후 뭐 바뀌었어?", "/brief", "sonnet"],
  ["이번 주 정리해 줘", "/weekly", "sonnet"],
  ["나한테 맞는 추천", "/recommend", "opus"],
  ["브라우저 테스트 관련 모아 줘", "/explore 브라우저 테스트", "sonnet"],
  ["내 세팅 점검해 줘", "/design-my-setup", "opus"],
  ["한국어 번역 갱신", "scripts/ko.py로 최근 7일 번역이 없는 핵심 항목을 번역해서 저장해 줘", "sonnet"],
];
const TOOL_KO = { Bash: "스크립트 실행", PowerShell: "스크립트 실행", Read: "파일 읽기", Write: "저장", Edit: "저장", Grep: "검색", Glob: "파일 찾기", Skill: "스킬 실행" };
async function initAssist() {
  let st;
  try { const r = await fetch("api/status", { cache: "no-store" }); if (!r.ok) return; st = await r.json(); } catch { return; }
  if (!st || st.local !== true || typeof st.token !== "string") return;
  assist.token = st.token;
  try { assist.sid = sessionStorage.getItem("tw-sid"); } catch { /* 저장소 차단 */ }
  const fab = document.getElementById("assist-fab"), panel = document.getElementById("assist");
  fab.hidden = false;
  document.getElementById("assist-sub").textContent = st.claude ? `내 PC의 Claude Code ${st.claude} · 로컬 전용` : "claude CLI를 찾지 못했어요";
  document.getElementById("assist-close").replaceChildren(icon("close", 18));
  document.getElementById("assist-new").replaceChildren(icon("plus", 18));
  setSendIcon();
  const open = (v) => {
    panel.hidden = !v; fab.hidden = v; fab.setAttribute("aria-expanded", String(v));
    if (v) { if (!assist.opened) hello(); assist.opened = true; moveThumb(document.getElementById("assist-model")); document.getElementById("assist-input").focus(); }
    else fab.focus();
  };
  fab.addEventListener("click", () => open(true));
  document.getElementById("assist-close").addEventListener("click", () => open(false));
  document.getElementById("assist-new").addEventListener("click", () => {
    if (assist.busy) assist.ctrl?.abort();
    assist.sid = null; try { sessionStorage.removeItem("tw-sid"); } catch { /* 무시 */ }
    document.getElementById("assist-log").replaceChildren(); hello();
  });
  panel.addEventListener("keydown", (e) => { if (e.key === "Escape") open(false); });
  document.querySelectorAll("#assist-model button").forEach((b) => b.addEventListener("click", () => {
    assist.model = b.dataset.model;
    document.querySelectorAll("#assist-model button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    moveThumb(document.getElementById("assist-model"));
  }));
  document.getElementById("assist-quick").replaceChildren(...QUICK.map(([label, prompt, model]) =>
    el("button", { type: "button", onclick: () => ask(prompt, model, label) }, label)));
  const input = document.getElementById("assist-input");
  const grow = () => { input.style.height = "auto"; input.style.height = `${Math.min(input.scrollHeight, 140)}px`; };
  input.addEventListener("input", grow);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); document.getElementById("assist-form").requestSubmit(); } });
  document.getElementById("assist-form").addEventListener("submit", (e) => {
    e.preventDefault();
    if (assist.busy) { assist.ctrl?.abort(); return; }
    const q = input.value.trim();
    if (!q) return;
    input.value = ""; grow();
    ask(q, assist.model);
  });
}
function hello() {
  document.getElementById("assist-log").append(el("div", { class: "assist-hello" },
    el("b", { text: "무엇을 도와드릴까요?" }),
    el("span", { text: "수집된 트렌드 데이터를 근거로 답해요. 아래 버튼으로 바로 시작하거나 자유롭게 물어보세요." })));
}
function setSendIcon() {
  const b = document.getElementById("assist-send");
  b.replaceChildren(icon(assist.busy ? "stop" : "send", 18));
  b.classList.toggle("is-stop", assist.busy);
  b.setAttribute("aria-label", assist.busy ? "답변 중지" : "보내기");
}
const scrollLog = () => { const l = document.getElementById("assist-log"); l.scrollTop = l.scrollHeight; };
async function ask(prompt, model, label) {
  if (assist.busy || !assist.token) return;
  const log = document.getElementById("assist-log");
  log.querySelector(".assist-hello")?.remove();
  log.append(el("div", { class: "msg user", text: label || prompt }));
  const live = el("span", { class: "streaming" }), caret = el("span", { class: "caret", "aria-hidden": "true" });
  const ai = el("div", { class: "msg ai" }, live, caret);
  const tools = el("div", { class: "tools" });
  log.append(tools, ai);
  scrollLog();
  assist.busy = true; assist.ctrl = new AbortController(); setSendIcon();
  let text = "", done = null, toolLine = null;
  const fail = (m) => { ai.replaceWith(el("div", { class: "msg err", role: "alert", text: m })); };
  try {
    const r = await fetch("api/ask", { method: "POST", signal: assist.ctrl.signal,
      headers: { "Content-Type": "application/json", "X-TW-Token": assist.token },
      body: JSON.stringify({ message: prompt, model: model || assist.model, session_id: assist.sid }) });
    if (!r.ok) { const j = await r.json().catch(() => ({})); fail(j.error || `요청 실패 (${r.status})`); return; }
    const reader = r.body.getReader(), dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done: end } = await reader.read();
      if (end) break;
      buf += dec.decode(value, { stream: true });
      let k;
      while ((k = buf.indexOf("\n\n")) >= 0) {
        const chunk = buf.slice(0, k); buf = buf.slice(k + 2);
        const name = (chunk.match(/^event: (.*)$/m) || [])[1], data = (chunk.match(/^data: (.*)$/m) || [])[1];
        if (!name || !data) continue;
        let d; try { d = JSON.parse(data); } catch { continue; }
        if (name === "delta") { text += d.t; live.textContent = text; toolLine?.remove(); toolLine = null; scrollLog(); }
        else if (name === "tool" || name === "tool_input") {
          const label2 = `${TOOL_KO[d.name] || d.name}${d.detail ? ` · ${d.detail}` : ""}`;
          if (!toolLine) { toolLine = el("div", { class: "tool-line" }, el("i", { class: "spin", "aria-hidden": "true" }), el("span")); tools.append(toolLine); }
          toolLine.lastChild.textContent = label2; scrollLog();
        } else if (name === "done") done = d;
        else if (name === "error") fail(d.message || "오류가 났어요.");
      }
    }
  } catch (e) {
    if (e.name === "AbortError") { caret.remove(); ai.append(el("span", { class: "muted", text: text ? " (중지됨)" : "중지했어요." })); }
    else fail("로컬 서버에 연결하지 못했어요. 터미널에서 python scripts/serve.py 가 실행 중인지 확인하세요.");
  } finally {
    assist.busy = false; setSendIcon(); toolLine?.querySelector(".spin")?.remove();
    if (done) {
      if (done.session_id && /^[0-9a-f-]{36}$/.test(done.session_id)) { assist.sid = done.session_id; try { sessionStorage.setItem("tw-sid", assist.sid); } catch { /* 무시 */ } }
      ai.replaceChildren(text ? markdown(text) : el("span", { class: "muted", text: "(빈 답변)" }));
      if (done.denied) ai.append(el("p", { class: "muted", text: `허용되지 않은 작업 ${done.denied}건은 실행하지 않았어요 (로컬 비서 안전 설정).` }));
      tools.replaceChildren();
      refreshData();
    } else caret.remove();
    scrollLog();
  }
}
async function refreshData() {   // 비서가 번역·요약을 저장했을 수 있으니 데이터를 다시 읽는다
  cache.days.clear(); cache.ko.clear();
  cache.digest = await loadDigest(); renderDigest();
  await update();
}

async function init() {
  readHash(); wire(); syncPressed();
  initAssist();
  try {
    [cache.index, cache.health, cache.metrics, cache.series] = await Promise.all([getJSON("data/index.json"),
      getJSON("data/health.json").catch(() => null), getJSON("data/metrics.json").catch(() => null), getJSON("data/series.json").catch(() => null)]);
  } catch (e) { renderError(e); return; }
  // 본문을 먼저 그리고, 그래프·AI 요약은 준비되는 대로 채운다
  const pulse = loadItems(range(14)).then((xs) => { cache.items14 = xs; renderPulse(xs); });
  const digest = loadDigest().then((d) => { cache.digest = d; renderDigest(); });
  const bench = renderBench().catch(() => {});
  await update();
  observe();
  await Promise.all([pulse, digest, bench]);
  observe();
}
addEventListener("hashchange", () => { readHash(); document.getElementById("f-q").value = state.q; update(); });
init();
