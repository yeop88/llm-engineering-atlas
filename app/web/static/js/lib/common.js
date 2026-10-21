// 공용 유틸리티
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

// 자동 이스케이프 HTML 템플릿: html`<b>${name}</b>` 은 name 을 이스케이프하고, html`` 결과 · raw() · 그 배열은 그대로 넣는다.
// innerHTML 과 손으로 부르는 esc() 가 수백 곳이라 하나만 빠뜨려도 화면이 깨지거나 스크립트가 끼어들 수 있었다 — 새 코드는 이것으로.
class SafeHtml { constructor(s) { this.s = s; } toString() { return this.s; } }
const raw = s => new SafeHtml(String(s ?? ""));
function _htmlPart(v) {
  if (v == null || v === false) return "";
  if (v instanceof SafeHtml) return v.s;
  if (Array.isArray(v)) return v.map(_htmlPart).join("");
  return esc(v);
}
function html(strings, ...vals) {
  return new SafeHtml(strings.reduce((out, str, i) => out + str + (i < vals.length ? _htmlPart(vals[i]) : ""), ""));
}
// 목록 잇기: 항목은 html`` 이면 그대로 · 글자면 이스케이프, 구분자는 코드에 적은 HTML(예: "<br>")이라 그대로
html.join = (items, sep = "") => new SafeHtml([...items].map(_htmlPart).join(String(sep)));
// html`` 결과는 객체라 빈 목록이어도 || 에서 참이 된다 — 빈 결과면 대신 보일 것(예: '없음' 줄)
html.or = (a, b) => (String(a ?? "") ? a : b);

// 상태 표시: 불러오는 중 · 빈 화면 · 오류 · 작업 진행 · 확인 창 — 화면마다 모양이 달라 '멈춘 건지 도는 건지' 알기 어려웠다
const ui = {
  loading(el, msg = "불러오는 중…") { el.innerHTML = html`<div class="loading" role="status">${msg}</div>`; },
  empty(el, msg, action) {
    el.innerHTML = html`<div class="empty">${msg}${action ? html`<div class="empty-act"><a class="btn" href="${action.href}">${action.label}</a></div>` : ""}</div>`;
  },
  error(el, e) { el.innerHTML = html`<div class="errbox" role="alert">${e?.message ?? e}</div>`; },
  // 작업 진행 패널 HTML: 진행률 · 메시지 · 경과 시간 · 취소 (취소는 data-cancel-job 버튼 — 아래 문서 전체 클릭 처리)
  jobProgress(j) {
    const sec = Math.max(0, Math.round((Date.now() - new Date(j.created_at).getTime()) / 1000));
    const el = sec >= 60 ? `${Math.floor(sec / 60)}분 ${sec % 60}초` : `${sec}초`;
    const live = ["pending", "running"].includes(j.status);
    return html`<div class="job-panel" role="status">
      <div class="row between small"><span>${j.title || "작업"} · ${pct(j.progress)}%</span>
        <span class="muted">${el}${live ? html` <button type="button" class="btn sm" data-cancel-job="${j.id}">취소</button>` : ""}</span></div>
      <div class="progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct(j.progress)}"><div style="width:${pct(j.progress)}%"></div></div>
      <div class="small muted">${j.message || (j.status === "pending" ? "대기 중" : "")}</div></div>`;
  },
  // 브라우저 기본 confirm() 대신: 무엇이 함께 지워지는지 적을 자리가 있고, 위험한 동작은 버튼 색으로 구분.
  // choose: 선택지가 여럿일 때(예: 기록만 삭제 / 모델까지 삭제 / 취소). 고른 value, 취소 · Esc 면 null.
  choose(message, buttons, { title = "확인" } = {}) {
    const dlg = $("#confirm-dlg");
    if (!dlg?.showModal) return Promise.resolve(window.confirm(message) ? buttons.at(-1).value : null);
    $("#confirm-title").textContent = title;
    $("#confirm-body").textContent = message;
    const box = $("#confirm-btns");
    box.innerHTML = html`<button type="button" class="btn" data-v="">취소</button>${buttons.map((b, i) =>
      html`<button type="button" class="btn${i === buttons.length - 1 ? " primary" : ""}${b.danger ? " danger-fill" : ""}" data-v="${i + 1}">${b.label}</button>`)}`;
    return new Promise(resolve => {
      const done = v => { dlg.close(); dlg.oncancel = null; box.onclick = null; resolve(v); };
      box.onclick = e => { const btn = e.target.closest("button[data-v]"); if (btn) done(btn.dataset.v ? buttons[+btn.dataset.v - 1].value : null); };
      dlg.oncancel = e => { e.preventDefault(); done(null); };
      dlg.showModal();
      // 위험한 동작은 Enter 한 번으로 실행되지 않게 취소에 초점
      $(buttons.some(b => b.danger) ? "button[data-v='']" : "button.primary", box).focus();
    });
  },
  async confirm(message, { ok = "확인", danger = false, title = "확인" } = {}) {
    return (await this.choose(message, [{ label: ok, value: true, danger }], { title })) === true;
  },
  // AI 응답 고지 + 사람 검토 요청(규제 대응 RC6, 인공지능 기본법 제31조): 서비스 답변 화면마다 같은 자리 · 같은 모양으로.
  // 요청 버튼은 아래 문서 전체 클릭 처리가 받는다(화면마다 처리기를 따로 두면 한 화면만 빠져도 요청 길이 끊긴다).
  aiNotice(notice, traceId) {
    if (!notice && !traceId) return "";
    return html`<div class="row small muted mt-2" role="note">${notice ? html`<span class="badge">AI 응답</span> <span>${notice}</span>` : ""}
      ${traceId ? html`<span data-review-box><button type="button" class="btn sm" data-review-trace="${traceId}">사람 검토 요청</button></span>` : ""}</div>`;
  },
};
const REVIEW_REASONS = [{ label: "답이 틀렸어요", value: "wrong" }, { label: "근거가 맞지 않아요", value: "source" }, { label: "사람과 상담하고 싶어요", value: "human" }];
document.addEventListener("click", async e => {
  const b = e.target.closest("[data-review-trace]");
  if (!b) return;
  const reason = await ui.choose("이 답을 사람이 다시 판단하도록 요청합니다. 어떤 점이 문제인가요?", REVIEW_REASONS, { title: "사람 검토 요청" });
  if (!reason) return;
  try {
    const r = await api("/api/compliance/reviews", { method: "POST", body: { trace_id: +b.dataset.reviewTrace, reason } });
    b.closest("[data-review-box]").innerHTML = html`<span class="badge ok">검토 요청 #${r.id} 접수</span>`;
  } catch (err) { toast(err.message, "err"); }
});
document.addEventListener("click", async e => {
  const b = e.target.closest("[data-cancel-job]");
  if (!b) return;
  if (!(await ui.confirm("이 작업을 취소할까요? 지금까지 한 부분은 버려집니다.", { ok: "작업 취소", danger: true }))) return;
  await api(`/api/jobs/${b.dataset.cancelJob}/cancel`, { method: "POST" }).catch(err => toast(err.message, "err"));
});

async function api(path, { method = "GET", body, form } = {}) {
  const opts = { method, headers: {} };
  if (form) opts.body = form;
  else if (body !== undefined) { opts.body = JSON.stringify(body); opts.headers["Content-Type"] = "application/json"; }
  const res = await fetch(path, opts);
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (res.status === 401 && !path.startsWith("/login")) {
    // 토큰 인증이 켜져 있고 로그인이 풀린 경우 — 로그인 화면으로 (돌아올 곳을 함께)
    location.href = `/login?next=${encodeURIComponent(location.pathname + location.search)}`;
    throw new Error("로그인이 필요합니다");
  }
  if (!res.ok) {
    let msg = data?.detail ?? data ?? res.statusText;
    if (Array.isArray(msg)) msg = msg.map(d => `${(d.loc || []).join(".")}: ${d.msg}`).join("\n");
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return data;
}

function toast(msg, kind = "") {
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.textContent = msg;
  $("#toasts").appendChild(el);
  setTimeout(() => el.remove(), kind === "err" ? 9000 : 4000);
}

async function busy(btn, fn) {
  const label = btn?.textContent;
  if (btn) { btn.disabled = true; btn.textContent = "처리 중…"; }
  try { return await fn(); }
  catch (e) { toast(e.message, "err"); throw e; }
  finally { if (btn) { btn.disabled = false; btn.textContent = label; } }
}

const fmtBytes = b => {
  if (!b) return "-";
  const u = ["B", "KB", "MB", "GB", "TB"]; let i = 0;
  while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
  return `${b.toFixed(i >= 3 ? 2 : 0)} ${u[i]}`;
};
const fmtNum = n => (n == null ? "-" : Number(n).toLocaleString("ko-KR"));
const fmtDate = s => (s ? new Date(s).toLocaleString("ko-KR", { dateStyle: "short", timeStyle: "short" }) : "-");
const pct = v => (v == null ? "-" : (v * 100).toFixed(1));

function heatColor(v) {
  // -1..1 → 투명..accent
  const a = Math.max(0, Math.min(1, (v + 1) / 2)) ** 2.2;
  return `color-mix(in srgb, var(--accent) ${Math.round(a * 85)}%, transparent)`;
}

// 공개일 기준으로 '최근 공개' 여부 판단 (고정 태그 대신 날짜로 계산해 시간이 지나도 맞게 유지)
const RECENT_DAYS = 180;
function isRecent(m, days = RECENT_DAYS) {
  if (!m.release_date) return false;
  return Date.now() - new Date(m.release_date).getTime() <= days * 86400000;
}

function modelBadges(m) {
  const b = [];
  if (m.kind === "reranker") b.push(html`<span class="badge" title="검색 결과 재정렬용 Cross-Encoder">리랭커</span>`);
  if (isRecent(m)) b.push(html`<span class="badge new" title="최근 ${RECENT_DAYS}일 이내 공개">최근</span>`);
  if (m.loaded_profiles?.length) b.push(html`<span class="badge ok">로드됨${m.loaded_profiles.includes("multimodal") ? "(MM)" : ""}</span>`);
  else if (m.cached) b.push(html`<span class="badge">다운로드됨</span>`);
  if (m.download_job) b.push(html`<span class="badge warn">다운로드 ${pct(m.download_job.progress)}%</span>`);
  if (m.gated) b.push(html`<span class="badge warn" title="HF 라이선스 동의 + HF_TOKEN 필요">gated</span>`);
  if (m.trust_remote_code) b.push(html`<span class="badge muted" title="trust_remote_code=True">remote code</span>`);
  if (m.last_error) b.push(html`<span class="badge err" title="${m.last_error}">오류</span>`);
  return html.join(b, " ");
}

let _modelsCache = null;
async function getModels(force = false) {
  if (!_modelsCache || force) _modelsCache = await api("/api/models");
  return _modelsCache;
}

// <select> 에 모델 목록 채우기. 로드/다운로드된 모델을 위로.
async function fillModelSelect(sel, { multimodal = false, preferred = [], kind = "embedding" } = {}) {
  const models = (await getModels()).filter(m => m.kind === kind && (!multimodal || m.modalities.some(x => x !== "text")));
  const score = m => (m.loaded_profiles.length ? 2 : 0) + (m.cached ? 1 : 0);
  models.sort((a, b) => score(b) - score(a) || (b.release_date || "").localeCompare(a.release_date || ""));
  const keep = new Set([...sel.selectedOptions].map(o => o.value));
  sel.innerHTML = html.join(models.map(m => {
    const state = m.loaded_profiles.length ? "● " : m.cached ? "○ " : "  ";
    return html`<option value="${m.id}" data-dims="${html.join((m.mrl_dims || []), ",")}">${state}${m.name} — ${m.hf_id}${m.params ? html` (${m.params})` : ""}</option>`;
  }), "");
  const want = keep.size ? keep : new Set(preferred.map(String));
  [...sel.options].forEach(o => { if (want.has(o.value)) o.selected = true; });
  if (!sel.multiple && !sel.value && sel.options.length) sel.options[0].selected = true;
  return models;
}

function selectedIds(sel) { return [...sel.selectedOptions].map(o => Number(o.value)); }

// 선택한 모델들의 Matryoshka 차원 후보로 <select> 채우기
function fillDimSelect(modelSel, dimSel) {
  const dims = new Set();
  [...modelSel.selectedOptions].forEach(o => (o.dataset.dims || "").split(",").filter(Boolean).forEach(d => dims.add(Number(d))));
  const cur = dimSel.value;
  dimSel.innerHTML = '<option value="">전체 차원 (기본)</option>' +
    [...dims].sort((a, b) => b - a).map(d => html`<option value="${d}">${d} (MRL)</option>`).join("");
  if ([...dimSel.options].some(o => o.value === cur)) dimSel.value = cur;
}

async function pollJob(id, onUpdate, interval = 1000) {
  for (;;) {
    const job = await api(`/api/jobs/${id}`);
    onUpdate?.(job);
    if (!["pending", "running"].includes(job.status)) return job;
    await new Promise(r => setTimeout(r, interval));
  }
}

function appliedInfo(a) {
  if (!a) return "";
  const parts = [];
  if (a.prompt_name) parts.push(html`prompt_name=<code>${a.prompt_name}</code>`);
  if (a.prefix) parts.push(html`prefix=<code>${a.prefix.trim()}</code>`);
  if (a.extra_kwargs) parts.push(html`kwargs=<code>${JSON.stringify(a.extra_kwargs)}</code>`);
  if (a.truncate_dim) parts.push(`truncate_dim=${a.truncate_dim}`);
  return html.or(html.join(parts, " · "), html`<span class="muted">프롬프트 없음</span>`);
}

function warningsHtml(ws) {
  return html.join((ws || []).map(w => html`<div class="warnbox">${w}</div>`), "");
}

// 탭
function initTabs(root = document) {
  $$(".tabs", root).forEach(tabs => {
    tabs.addEventListener("click", e => {
      const btn = e.target.closest("button[data-tab]");
      if (!btn) return;
      $$("button", tabs).forEach(b => b.classList.toggle("active", b === btn));
      $$(".tab-panel", tabs.parentElement).forEach(p => p.classList.toggle("active", p.id === btn.dataset.tab));
      history.replaceState(null, "", `#${btn.dataset.tab}`);
    });
    const initial = location.hash && $(`button[data-tab="${location.hash.slice(1)}"]`, tabs);
    (initial || $("button[data-tab]", tabs))?.click();
  });
}
// 같은 페이지 안에서 #탭 링크로 이동해도 탭이 바뀌도록
window.addEventListener("hashchange", () => {
  const btn = location.hash && $(`.tabs button[data-tab="${location.hash.slice(1)}"]`);
  if (btn && !btn.classList.contains("active")) btn.click();
});

// 브라우저 저장소 (사생활 보호 모드 등에서 막혀도 동작하도록)
function localGet(key) { try { return localStorage.getItem(key); } catch { return null; } }
function localSet(key, value) { try { localStorage.setItem(key, value); } catch { /* 저장 안 해도 동작에 지장 없음 */ } }

// 작업 맥락: 컬렉션(col) · 청크 세트(cs) · 인덱스(idx) · 평가 세트(set) · LLM(provider · model).
// 화면마다 같은 선택을 다시 해야 했다 → 한 번 고르면 모든 화면이 그 값으로 시작한다. 주소의 ?col= · ?idx= · ?set= 가 있으면 그것이 먼저
// (링크로 같은 실험 설정을 공유 · 새로 고침해도 유지). 브라우저에만 저장하므로 없거나 막혀도 화면은 기본값으로 동작한다.
const Ctx = (() => {
  const KEY = "atlas-ctx", URL_KEYS = ["col", "cs", "idx", "set"];
  let state = {};
  try { state = JSON.parse(localGet(KEY) || "{}") || {}; } catch { state = {}; }
  const q = new URLSearchParams(location.search);
  URL_KEYS.forEach(k => { if (q.get(k)) state[k] = q.get(k); });
  const subs = [];
  return {
    get: () => ({ ...state }),
    // patch: { col: "3", colLabel: "근로 · 임대차 법률" } — 컬렉션을 바꾸면 그 컬렉션에 딸린 값은 비운다
    // url: false — 주소에 쓰지 않는다(이미 주소가 대상을 가리키는 상세 화면: /rag/collections/3 에 ?col=3 이 붙지 않게)
    set(patch, { url = true } = {}) {
      if ("col" in patch && String(patch.col ?? "") !== String(state.col ?? "")) ["cs", "idx", "set", "csLabel", "idxLabel", "setLabel"].forEach(k => delete state[k]);
      Object.entries(patch).forEach(([k, v]) => { if (v === "" || v == null) delete state[k]; else state[k] = String(v); });
      localSet(KEY, JSON.stringify(state));
      if (url) {
        const u = new URL(location.href);
        URL_KEYS.forEach(k => { if (u.searchParams.has(k) || k in patch) { if (state[k]) u.searchParams.set(k, state[k]); else u.searchParams.delete(k); } });
        history.replaceState(history.state, "", u);
      }
      subs.forEach(f => f(this.get()));
    },
    clear() { state = {}; localSet(KEY, "{}"); subs.forEach(f => f({})); },
    on(f) { subs.push(f); },
    used: false,  // 이 화면이 맥락을 쓰는지 — 쓰는 화면에만 위쪽 맥락 줄을 보인다(lib/shell.js)
  };
})();

// <select data-ctx="col"> · <input data-ctx="model"> 처럼 표시한 입력란: 맥락 값으로 시작하고, 바꾸면 맥락에 저장.
// 옵션을 나중에 채우는 select 는 채운 뒤 applyCtx(el) 을 다시 부른다.
function applyCtx(el) {
  const k = el.dataset.ctx, c = Ctx.get(), v = c[k];
  if (v == null) return;
  if (el.tagName === "SELECT" && ![...el.options].some(o => o.value === v)) return;
  el.value = v;
  // 주소(?col=3)로만 들어와 이름을 모르면 맥락 줄에 '#3' 대신 이름이 보이게 채운다
  if (el.tagName === "SELECT" && !c[k + "Label"]) Ctx.set({ [k + "Label"]: el.selectedOptions[0]?.textContent.trim() });
}
function bindCtx(root = document) {
  $$("[data-ctx]", root).forEach(el => {
    if (el.dataset.ctxBound) return;
    el.dataset.ctxBound = "1";
    Ctx.used = true;
    applyCtx(el);
    el.addEventListener("change", () => {
      const k = el.dataset.ctx;
      const label = el.tagName === "SELECT" ? el.selectedOptions[0]?.textContent.trim() : el.value;
      Ctx.set({ [k]: el.value, [k + "Label"]: label });
    });
  });
}

// 컬렉션 → 인덱스 · 청크 세트 · 평가 세트 선택 묶음. 단계 화면마다 같은 선택이 반복돼 한 곳에 둔다.
// o = { col, idx?, cs?, set?, onDetail? } (select 요소들). 고른 값은 작업 맥락(Ctx)에 저장돼 다른 화면도 같은 값으로 시작한다.
async function setupCollectionPickers(o) {
  Ctx.used = true;
  const cols = await api("/api/collections");
  o.col.innerHTML = cols.length ? html`${cols.map(c => html`<option value="${c.id}">${c.name}</option>`)}` : html`<option value="">컬렉션 없음</option>`;
  const want = Ctx.get();
  const remember = (k, sel) => sel?.value && Ctx.set({ [k]: sel.value, [k + "Label"]: sel.selectedOptions[0]?.textContent.trim() });
  if (want.col && cols.some(c => String(c.id) === want.col)) { o.col.value = want.col; if (!want.colLabel) remember("col", o.col); }
  async function detail() {
    if (!o.col.value) return null;
    const d = await api(`/api/collections/${o.col.value}`);
    const c = Ctx.get();
    const fill = (sel, items, empty, key) => {
      if (!sel) return;
      sel.innerHTML = items.length ? html`${items}` : html`<option value="">${empty}</option>`;
      if (c[key] && [...sel.options].some(x => x.value === c[key])) sel.value = c[key];
    };
    fill(o.idx, d.indexes.filter(i => i.status === "ready").map(i => html`<option value="${i.id}">${i.model_hf_id.split(/[\/]/).pop()} · #${i.id}</option>`), "준비된 인덱스 없음", "idx");
    fill(o.cs, d.chunk_sets.filter(x => x.status === "ready").map(x => html`<option value="${x.id}">${x.name}</option>`), "청크 세트 없음", "cs");
    if (o.set) {
      const sets = (await api(`/api/collections/${d.id}/eval-sets`)).filter(s => s.status === "ready");
      fill(o.set, sets.map(s => html`<option value="${s.id}">#${s.id} ${s.name} (${s.n_items}문항)</option>`), "평가 세트 없음", "set");
    }
    o.onDetail?.(d);
    return d;
  }
  if (!o.col.dataset.ctxBound) {
    o.col.dataset.ctxBound = "1";
    o.col.addEventListener("change", () => { remember("col", o.col); detail(); });
    [["idx", o.idx], ["cs", o.cs], ["set", o.set]].forEach(([k, sel]) => sel?.addEventListener("change", () => remember(k, sel)));
  }
  if (o.col.value && !Ctx.get().col) remember("col", o.col);
  return detail();
}

// 작업 실행 → 진행 패널(진행률 · 경과 · 취소) → 끝나면 render(result). 여러 단계 화면이 같은 모양으로 쓴다.
async function runJobInto(btn, path, body, box, render) {
  const job = await busy(btn, () => api(path, { method: "POST", body }));
  box.hidden = false; btn.disabled = true;
  try {
    const done = await pollJob(job.id, j => { box.innerHTML = ui.jobProgress(j); }, 1500);
    if (done.status !== "done") { ui.error(box, done.status === "cancelled" ? "취소했습니다." : (done.error || done.status)); return; }
    box.hidden = true; render(done.result);
  } finally { btn.disabled = false; }
}

// 상세 화면이 위치 표시 끝에 대상 이름을 덧붙인다(예: 2 RAG › 컬렉션 › 근로 · 임대차 법률). 지금 화면 이름은 목록으로 가는 링크가 된다.
function setCrumb(name, parentHref = location.pathname.replace(/\/[^/]+\/?$/, "")) {
  let cur = $(".crumbs .here.detail");
  if (!cur) {
    const here = $("#crumb-here");
    if (!here) return;
    const a = document.createElement("a");
    a.href = parentHref; a.textContent = here.textContent;
    const sep = document.createElement("span");
    sep.className = "sep"; sep.textContent = "›"; sep.setAttribute("aria-hidden", "true");
    cur = document.createElement("span");
    cur.className = "here detail"; cur.setAttribute("aria-current", "page");
    here.replaceWith(a, sep, cur);
    document.body.dataset.baseTitle = document.title;
  }
  cur.textContent = name;
  document.title = `${name} · ${document.body.dataset.baseTitle}`;
}

// 답변의 조문 · 판례 번호 검사 결과 (rag/legal.py) — 번호가 없으면 아무것도 그리지 않는다
const CITE_ST = { in_sources: ["근거에 있음", "ok"], in_collection: ["근거 밖 · 자료에 있음", "warn"], not_found: ["자료에 없음 (지어낸 번호?)", "err"], unchecked: ["확인 안 함", ""] };
const citeBox = c => (c && c.n ? html`<div class="small">조문 · 판례 번호: ${html.join(c.refs.map(r => html`<span class="badge ${CITE_ST[r.status][1]}" title="${CITE_ST[r.status][0]}">${r.ref}${r.source ? html` [${r.source}]` : ""} · ${CITE_ST[r.status][0]}</span>`), " ")}</div>` : "");
const vsBadge = d => (d ? html`${d.diff >= 0 ? "+" : ""}${(d.diff * 100).toFixed(1)}%p ${d.significant ? html`<span class="badge err">유의</span>` : html`<span class="badge">불확실</span>`}` : "기준");
