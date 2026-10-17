// 공용 유틸리티
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

async function api(path, { method = "GET", body, form } = {}) {
  const opts = { method, headers: {} };
  if (form) opts.body = form;
  else if (body !== undefined) { opts.body = JSON.stringify(body); opts.headers["Content-Type"] = "application/json"; }
  const res = await fetch(path, opts);
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
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
  if (m.kind === "reranker") b.push('<span class="badge" title="검색 결과 재정렬용 Cross-Encoder">리랭커</span>');
  if (isRecent(m)) b.push(`<span class="badge new" title="최근 ${RECENT_DAYS}일 이내 공개">최근</span>`);
  if (m.loaded_profiles?.length) b.push(`<span class="badge ok">로드됨${m.loaded_profiles.includes("multimodal") ? "(MM)" : ""}</span>`);
  else if (m.cached) b.push('<span class="badge">다운로드됨</span>');
  if (m.download_job) b.push(`<span class="badge warn">다운로드 ${pct(m.download_job.progress)}%</span>`);
  if (m.gated) b.push('<span class="badge warn" title="HF 라이선스 동의 + HF_TOKEN 필요">gated</span>');
  if (m.trust_remote_code) b.push('<span class="badge muted" title="trust_remote_code=True">remote code</span>');
  if (m.last_error) b.push(`<span class="badge err" title="${esc(m.last_error)}">오류</span>`);
  return b.join(" ");
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
  sel.innerHTML = models.map(m => {
    const state = m.loaded_profiles.length ? "● " : m.cached ? "○ " : "  ";
    return `<option value="${m.id}" data-dims="${(m.mrl_dims || []).join(",")}">${state}${esc(m.name)} — ${esc(m.hf_id)}${m.params ? ` (${esc(m.params)})` : ""}</option>`;
  }).join("");
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
    [...dims].sort((a, b) => b - a).map(d => `<option value="${d}">${d} (MRL)</option>`).join("");
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
  if (a.prompt_name) parts.push(`prompt_name=<code>${esc(a.prompt_name)}</code>`);
  if (a.prefix) parts.push(`prefix=<code>${esc(a.prefix.trim())}</code>`);
  if (a.extra_kwargs) parts.push(`kwargs=<code>${esc(JSON.stringify(a.extra_kwargs))}</code>`);
  if (a.truncate_dim) parts.push(`truncate_dim=${a.truncate_dim}`);
  return parts.join(" · ") || '<span class="muted">프롬프트 없음</span>';
}

function warningsHtml(ws) {
  return (ws || []).map(w => `<div class="warnbox">${esc(w)}</div>`).join("");
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
