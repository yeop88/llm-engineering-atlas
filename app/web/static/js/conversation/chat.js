// conversation/chat.html 화면 스크립트 — 여러 턴 대화(C1 재작성 · C2 되묻기 · C3 메모리 · C4 프로필 · C5 압축 · C6 인계)
// 대화 기록은 이 화면이 들고 있다가 매 턴 서버에 보낸다(서버에 대화 표가 없음). 새로 고침해도 이어지게 브라우저에 컬렉션별로 남긴다.
let history = [];
let asked = [];
const sessionId = `chat-${Math.random().toString(36).slice(2, 10)}`;
const KEY = () => `conversation-history-${$("#v-col").value}`;
const METHOD = { none: "그대로", history: "앞 질문 이어 붙임", rule: "규칙", llm: "LLM" };

function save() { localSet(KEY(), JSON.stringify({ history, asked })); }
function restore() {
  try { const s = JSON.parse(localGet(KEY()) || "null"); history = s?.history || []; asked = s?.asked || []; } catch { history = []; asked = []; }
}

async function loadCols() {
  const cols = await api("/api/collections");
  $("#v-col").innerHTML = html.or(html.join(cols.map(c => html`<option value="${c.id}">${c.name}</option>`), ""), html`<option value="">컬렉션 없음</option>`);
  applyCtx($("#v-col"));
  try { const m = await api("/api/llm/models"); $("#v-model-list").innerHTML = html`${m.models.map(x => html`<option value="${x}">`)}`; } catch { /* 로컬 서버가 꺼져 있으면 목록 없음 */ }
  await onCol();
}

async function onCol() {
  restore();
  renderThread();
  const cid = $("#v-col").value;
  if (!cid) return;
  try {
    const v = await api(`/api/conversation/collections/${cid}/vocab`);
    $("#v-vocab").innerHTML = v.models.length
      ? html`알아보는 제품: ${html.join(v.models, ", ")}<br>오류 코드 ${v.codes.length}개 — 코드가 한 모델에만 있으면 그 모델로 봅니다.`
      : "이 컬렉션에는 제품 메타가 없어 제품 · 코드 없이 대화 주제만 기억합니다(되묻기는 '모호한 질문'만).";
  } catch (e) { $("#v-vocab").textContent = e.message; }
}

function memoryBox(m) {
  if (!m) return "";
  const row = (k, v) => (v && (!Array.isArray(v) || v.length) ? html`<div><b>${k}</b> ${Array.isArray(v) ? html.join(v, " · ") : v}</div>` : "");
  return html`${row("제품", m.product_model ? html`${m.product_model}${m.model_from_code ? html` <span class="badge">코드로 추정</span>` : ""}` : "")}${row("오류 코드", m.codes)}
    ${row("증상", m.symptoms)}${row("안내한 조치", m.tried)}${row("대화 주제", m.topic)}<div class="muted">고객 말 ${m.turns}번</div>`;
}

function turnMeta(r) {
  const rw = r.rewrite;
  const parts = [];
  if (rw?.changed) parts.push(html`<div class="small"><span class="badge">풀어 씀 · ${METHOD[rw.method] || rw.method}</span> <span class="mono">${rw.query}</span> <span class="muted">(${rw.reason})</span></div>`);
  else if (rw) parts.push(html`<div class="small muted">질문 그대로 검색 — ${rw.reason}</div>`);
  if (r.clarify?.ask) parts.push(html`<div class="small"><span class="badge warn">되묻기</span> ${r.clarify.reason === "product_model" ? "제품을 모르는 고장 문의" : "검색이 헷갈리는 짧은 질문"}</div>`);
  if (r.history_prompt?.dropped) parts.push(html`<div class="small muted">앞 대화 ${r.history_prompt.dropped}개 메시지는 기억한 사실로 줄여 넣음(C5)</div>`);
  if (r.sources?.length) parts.push(html`<details class="small"><summary>근거 ${r.sources.length}개</summary>${html.join(r.sources.map((s, i) => html`<div>[${i + 1}] ${s.filename}</div>`), "")}</details>`);
  if (r.verify && r.answered) parts.push(html`<div class="small muted">근거 일치 ${r.verify.supported_ratio == null ? "-" : `${Math.round(r.verify.supported_ratio * 100)}%`}${r.trace_id ? html` · <a href="/evalops/traces?trace=${r.trace_id}">요청 기록 #${r.trace_id}</a>` : ""}</div>`);
  return html.join(parts, "");
}

function renderThread(last) {
  const box = $("#v-thread");
  if (!history.length) { box.innerHTML = html`<div class="card"><div class="empty">질문을 입력해 대화를 시작하세요. 예: 'WM-200 세탁기에 E4 가 떠요' → '필터는 어디 있어요?'</div></div>`; return; }
  box.innerHTML = html.join(history.map((m, i) => html`<div class="card stack">
    <div class="small muted">${m.role === "user" ? "고객" : "상담"}</div><div class="pre">${m.text}</div>
    ${m.meta ? turnMeta(m.meta) : ""}</div>`), "");
  if (last) box.lastElementChild?.scrollIntoView({ behavior: "smooth", block: "end" });
}

async function send() {
  const q = $("#v-text").value.trim();
  const cid = +$("#v-col").value;
  if (!q) return toast("질문을 입력하세요", "err");
  if (!cid) return toast("컬렉션을 고르세요", "err");
  const body = {
    collection_id: cid, question: q, history: history.map(({ role, text }) => ({ role, text })), method: $("#v-method").value,
    clarify: $("#v-clarify").checked, asked, profile_key: $("#v-profile").value.trim(), session_id: sessionId,
    guard_mode: $("#v-guard").value || null, provider: $("#v-provider").value || null, model: $("#v-model").value.trim() || null,
  };
  $("#v-status").textContent = "답변 중…";
  const r = await busy($("#v-send"), () => api("/api/conversation/turn", { method: "POST", body })).finally(() => { $("#v-status").textContent = ""; });
  history.push({ role: "user", text: q }, { role: "assistant", text: r.reply, meta: r });
  if (r.clarify?.ask) asked.push(r.clarify.reason);
  $("#v-text").value = "";
  $("#v-memory").innerHTML = memoryBox(r.memory);
  if (r.profile) renderProfile(r.profile);
  save();
  renderThread(true);
}

function renderProfile(p) {
  $("#v-profile-out").innerHTML = html`<div><b>보유 제품</b> ${html.or(html.join(p.products, " · "), "없음")}</div>
    ${p.issues.length ? html`<div class="stack">${html.join(p.issues.slice(-5).reverse().map(i => html`<div>${fmtDate(i.at)} · ${i.product || "제품 모름"}${i.codes.length ? ` · ${i.codes.join(", ")}` : ""} — ${i.summary}</div>`), "")}</div>` : ""}`;
}

async function loadProfile() {
  const key = $("#v-profile").value.trim();
  if (!key) return;
  try { renderProfile(await api(`/api/conversation/profiles/${encodeURIComponent(key)}`)); }
  catch { $("#v-profile-out").textContent = "아직 프로필이 없습니다 — 대화를 남기면 생깁니다."; }
}

$("#v-send").onclick = () => send().catch(() => {});
$("#v-text").addEventListener("keydown", e => { if (e.key === "Enter" && e.ctrlKey) send().catch(() => {}); });
$("#v-col").addEventListener("change", onCol);
$("#v-profile").addEventListener("change", loadProfile);
$("#v-new").onclick = () => { history = []; asked = []; save(); renderThread(); $("#v-memory").innerHTML = html`<span class="muted">새 대화입니다.</span>`; $("#v-handoff-out").innerHTML = ""; };
$("#v-handoff").onclick = async e => {
  if (!history.length) return toast("대화가 없습니다", "err");
  const s = await busy(e.target, () => api("/api/conversation/handoff", { method: "POST", body: { collection_id: +$("#v-col").value || null, history: history.map(({ role, text }) => ({ role, text })) } }));
  $("#v-handoff-out").innerHTML = html`<div class="pre">${s.text || "기억한 사실이 없습니다."}</div><div class="muted">처음 질문: ${s.first_question}<br>마지막 질문: ${s.last_question} · 고객 말 ${s.turns}번</div>`;
};
$("#v-remember").onclick = async e => {
  const key = $("#v-profile").value.trim();
  if (!key) return toast("고객 키를 넣으세요", "err");
  if (!history.length) return toast("대화가 없습니다", "err");
  const p = await busy(e.target, () => api(`/api/conversation/profiles/${encodeURIComponent(key)}/remember`, { method: "POST", body: { collection_id: +$("#v-col").value || null, history: history.map(({ role, text }) => ({ role, text })) } }));
  renderProfile(p);
  toast("프로필에 남겼습니다 (개인정보는 가려서)");
};
$("#v-forget").onclick = async () => {
  const key = $("#v-profile").value.trim();
  if (!key) return toast("고객 키를 넣으세요", "err");
  if (!(await ui.confirm(`'${key}' 프로필(보유 제품 · 지난 문의)을 지울까요?`))) return;
  await api(`/api/conversation/profiles/${encodeURIComponent(key)}`, { method: "DELETE" }).catch(e => toast(e.message, "err"));
  $("#v-profile-out").textContent = "지웠습니다.";
};

loadCols().catch(e => ui.error($("#v-thread"), e));
