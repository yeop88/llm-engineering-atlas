// as/console.html 화면 스크립트 — 고객 AS 상담 한 건(AS1 접수 → AS2 분류 → AS3·AS4 답변 · 사진 → AS5 안내 → AS6 검증 → AS7 이관 · AS8 피드백)
const URG = { safety: ["err", "안전"], high: ["warn", "높음"], normal: ["", "보통"] };
const ST = { open: ["", "진행 중"], resolved: ["ok", "해결"], handoff: ["warn", "상담원 이관"], closed: ["muted", "종료"] };
const CH = { chat: "채팅", photo: "사진", voice: "음성" };
const SID_KEY = "as-console-sid";  // 새로 고침해도 보던 상담으로 돌아오게(브라우저에만 저장 — 막혀도 동작에 지장 없음)
let cur = null;

const badge = (map, k) => (k && map[k] ? html`<span class="badge ${map[k][0]}">${map[k][1]}</span>` : "");
const ratio = v => (v == null ? "-" : `${Math.round(v * 100)}%`);

// ── 예시 자료 ──────────────────────────────────────────────────────────────
async function loadSetup() {
  const box = $("#c-setup");
  try {
    const s = await api("/api/as/setup");
    if (!s.ready) {
      box.innerHTML = html`<div class="small muted">가상의 WM-200 · WM-100 · DR-300 매뉴얼과 FAQ 로 상담용 컬렉션을 만듭니다.</div>
        <label class="row small m-0"><input type="checkbox" id="c-setup-index" checked> 의미 검색 인덱스도 만들기 (혼합 검색 · 의미 캐시, 벡터 DB 필요)</label>
        <button class="btn primary" id="c-setup-run">예시 자료 준비</button>`;
      $("#c-setup-run").onclick = e => runJobInto(e.target, "/api/as/setup", { index: $("#c-setup-index").checked }, $("#c-setup-progress"), () => { toast("예시 자료를 준비했습니다", "ok"); loadSetup(); });
      return;
    }
    const idx = s.index;
    box.innerHTML = html`<div class="small">컬렉션 <a href="/rag/collections/${s.collection_id}">#${s.collection_id}</a> · 청크 세트 #${s.chunk_set_id}</div>
      <div class="small">${idx ? html`의미 검색 인덱스 <span class="badge ${idx.status === "ready" ? "ok" : "warn"}">${idx.status}</span> <span class="muted mono">${(idx.model || "").split("/").pop()}</span> — 혼합 검색`
        : html`<span class="badge muted">인덱스 없음</span> BM25 검색만 (의미 캐시 꺼짐)`}</div>`;
    const sel = $("#c-product"), keep = sel.value;
    sel.innerHTML = html`<option value="">모름 (모델을 가리지 않음)</option>${s.products.map(p => html`<option value="${p}">${p}</option>`)}`;
    sel.value = keep;
  } catch (e) { ui.error(box, e); }
}

async function loadLlm() {
  try {
    const s = await api("/api/llm/status");
    $("#c-llm").innerHTML = s.default.error ? html`<span class="badge warn">LLM 미설정</span> <a href="/settings/llm">LLM 연결</a>에서 확인하세요.` : html`기본: <span class="mono">${s.default.model}</span>`;
  } catch (e) { $("#c-llm").textContent = e.message; }
  try { const m = await api("/api/llm/models"); $("#c-model-list").innerHTML = html`${m.models.map(x => html`<option value="${x}">`)}`; } catch { /* 로컬 서버가 꺼져 있으면 목록 없음 */ }
}

// ── 최근 상담 ──────────────────────────────────────────────────────────────
async function loadRecent() {
  const box = $("#c-recent");
  try {
    const rows = await api("/api/as/sessions?limit=20");
    if (!rows.length) return ui.empty(box, "아직 상담이 없습니다.");
    box.innerHTML = html`${rows.map(s => html`<button type="button" class="btn sm" data-sid="${s.id}">
      ${s.customer || "(이름 없음)"} · ${s.product_model || "모델 모름"} ${badge(ST, s.status)}${s.urgency === "safety" ? html` ${badge(URG, "safety")}` : ""}
      <span class="muted">${s.intent || ""} · ${fmtDate(s.created_at)}</span></button>`)}`;
  } catch (e) { ui.error(box, e); }
}
$("#c-recent").addEventListener("click", e => { const b = e.target.closest("[data-sid]"); if (b) openSession(b.dataset.sid); });
$("#c-reload").onclick = loadRecent;

// ── 상담 열기 · 그리기 ─────────────────────────────────────────────────────
function renderHead(s) {
  const t = s.ticket;
  $("#c-head").innerHTML = html`<div class="row between">
      <div><b>${s.customer || "(이름 없음)"}</b> · ${s.product_model || "모델 모름"} · ${CH[s.channel] || s.channel}
        ${s.intent ? html` · 의도 <b>${s.intent}</b>` : ""} ${s.urgency ? html`· 긴급도 ${badge(URG, s.urgency)}` : ""} ${badge(ST, s.status)}
        ${s.satisfaction ? html` · 만족도 ${s.satisfaction}/5` : ""}</div>
      <span class="small muted mono">${s.id}</span></div>
    ${t ? html`<div class="warnbox mt-2">상담원 이관 티켓 <b>${t.id}</b> · ${t.reason} · 상태 ${t.status} — <a href="/as/tickets">티켓 · 지표</a>에서 처리합니다.</div>` : ""}`;
  $("#c-input").hidden = false;
  $("#c-fb").hidden = !(s.status === "open" && (s.messages || []).some(m => m.role === "assistant"));
}

function userBubble(m) {
  return html`<div class="q-bubble">${m.feedback ? html`<span class="badge">피드백</span> ` : ""}<span class="pre">${m.text}</span>${m.images ? html` <span class="badge muted">사진 ${m.images}장</span>` : ""}</div>`;
}

// 다시 연 상담은 저장된 메시지(글 · 코드 · 캐시 · 모델 불일치 표시)만, 방금 받은 답은 단계 · 근거 · 검증까지 그린다
function botCard(m, r) {
  const flags = [m.cached || r?.cached ? html`<span class="badge">의미 캐시</span>` : "", m.mismatch ? html`<span class="badge warn">다른 모델 근거</span>` : "",
    ...(m.codes || []).map(c => html`<span class="badge muted">코드 ${c}</span>`), m.stage === "handoff" ? html`<span class="badge err">안전 · 상담원 연결</span>` : ""];
  return html`<div class="card stack">
    <div class="answer pre">${m.text}</div>
    <div class="row small gap-2">${flags}</div>
    ${r ? detail(r) : ""}</div>`;
}

function detail(r) {
  const v = r.verify || {}, g = r.guard || {}, codes = Object.entries(v.codes || {});
  const steps = html`<div class="trace">${r.steps.map(s => html`<div class="trace-step run"><b>${s.stage}</b> ${s.name}<div class="muted">${s.detail}</div></div>`)}</div>`;
  const tri = r.triage || {};
  const triBox = html`<div class="small">분류: ${html.join((tri.top || []).map(t => html`${t.label} ${ratio(t.p)}`), " · ")} · 긴급도 ${badge(URG, tri.urgency)}</div>`;
  const ph = r.photo ? html`<div class="small">사진 진단: ${r.photo.code ? html`코드 <b>${r.photo.code}</b>` : "코드를 읽지 못함"}${r.photo.snapped ? html` <span class="badge warn" title="비전 모델이 읽은 글자 ${r.photo.raw_code}">비슷한 글자 고침 (${r.photo.raw_code} → ${r.photo.code})</span>` : ""}${r.photo.display ? html` · 표시창 "${r.photo.display}"` : ""}</div>` : "";
  const ver = "supported_ratio" in v || codes.length ? html`<div class="row small gap-2">검증:
      <span class="badge ${v.supported_ratio >= 0.8 ? "ok" : v.supported_ratio == null ? "muted" : "warn"}" title="답변 문장이 인용한 근거에 있는 비율">근거 일치 ${ratio(v.supported_ratio)}</span>
      ${v.relevant_ratio != null ? html`<span class="badge muted" title="질문과 관련 있는 문장 비율">질문 관련성 ${ratio(v.relevant_ratio)}</span>` : ""}
      ${codes.map(([c, ok]) => html`<span class="badge ${ok ? "ok" : "err"}" title="${ok ? "근거 글에 이 코드가 있음" : "고객 제품 자료에 이 코드가 없음 — 다른 모델 코드거나 잘못 읽음"}">코드 ${c} ${ok ? "✓" : "✗"}</span>`)}
      ${g.action ? html`<span class="badge ${g.action === "pass" ? "ok" : g.action === "block" ? "err" : "warn"}" title="${(g.violations || []).map(x => x.rule).join(", ")}">정책 ${g.action}</span>` : ""}
      ${v.refused ? html`<span class="badge warn">자료에서 답을 찾지 못함</span>` : ""}</div>` : "";
  const mm = r.mismatch ? html`<div class="warnbox">고객 제품은 <b>${r.mismatch.product_model}</b> 인데 근거 일부가 다른 모델 자료입니다: ${html.join(r.mismatch.other_model_sources.map(o => html`${o.filename} (${o.models.join(", ")})`), " · ")}</div>` : "";
  const tk = r.ticket ? html`<div class="warnbox">티켓 <b>${r.ticket.id}</b> 생성 · ${r.ticket.reason} · 전달 ${r.ticket.delivered?.to === "local" ? "이 앱에만 기록" : html`${r.ticket.delivered?.to} (${r.ticket.delivered?.status ?? r.ticket.delivered?.error ?? "-"})`}</div>` : "";
  const src = (r.sources || []).length ? html`<details><summary class="small">근거 ${r.sources.length}개</summary><div class="stack mt-2">${r.sources.map((s, i) => html`<div class="src"><span class="cite">${i + 1}</span> <b class="small">${s.filename}</b> <span class="small muted mono">${s.score?.toFixed?.(3) ?? ""}</span><div class="small pre">${s.text}</div></div>`)}</div></details>` : "";
  return html`${steps}${triBox}${ph}${ver}${mm}${tk}${src}${r.trace_id ? html`<div class="small muted">요청 기록 <span class="mono">${r.trace_id}</span></div>` : ""}`;
}

function renderThread(s) {
  const msgs = s.messages || [];
  $("#c-thread").innerHTML = msgs.length ? html`${msgs.map(m => (m.role === "user" ? userBubble(m) : botCard(m)))}` : "";
}

async function openSession(sid) {
  ui.loading($("#c-thread"));
  try {
    cur = await api(`/api/as/sessions/${sid}`);
    localSet(SID_KEY, sid);
    renderHead(cur);
    renderThread(cur);
  } catch (e) {
    ui.error($("#c-thread"), e);
    localSet(SID_KEY, "");
  }
}

$("#c-new").onclick = e => busy(e.target, async () => {
  const s = await api("/api/as/sessions", { method: "POST", body: { customer: $("#c-customer").value.trim(), product_model: $("#c-product").value, channel: $("#c-channel").value } });
  cur = s;
  localSet(SID_KEY, s.id);
  renderHead(s);
  renderThread(s);
  $("#c-text").focus();
  loadRecent();
});

// ── 보내기 (글 · 사진 · 음성은 multipart — api() 의 form 으로) ───────────────
async function send() {
  if (!cur) return toast("상담을 먼저 시작하세요", "err");
  const text = $("#c-text").value.trim(), imgs = [...$("#c-images").files], audio = $("#c-audio").files[0];
  if (!text && !imgs.length && !audio) return toast("문의 내용이나 사진 · 음성을 넣어 주세요", "err");
  const form = new FormData();
  form.append("text", text);
  imgs.slice(0, 3).forEach(f => form.append("images", f));
  if (audio) form.append("audio", audio);
  if ($("#c-provider").value) form.append("provider", $("#c-provider").value);
  if ($("#c-model").value.trim()) form.append("model", $("#c-model").value.trim());
  $("#c-thread").insertAdjacentHTML("beforeend", html`${userBubble({ text: text || (audio ? "(음성)" : "(사진)"), images: imgs.length })}<div id="c-pending" class="loading" role="status">분류 · 검색 · 답변 · 검증 중… (로컬 LLM 은 수십 초)</div>`);
  $("#c-pending").scrollIntoView({ behavior: "smooth", block: "end" });
  try {
    const r = await busy($("#c-send"), () => api(`/api/as/sessions/${cur.id}/message`, { method: "POST", form }));
    $("#c-text").value = ""; $("#c-images").value = ""; $("#c-audio").value = "";
    cur = await api(`/api/as/sessions/${cur.id}`);
    renderHead(cur);
    // 저장된 대화를 다시 그리고, 마지막 답에만 이번 차례의 단계 · 근거 · 검증을 붙인다
    const msgs = cur.messages || [];
    const last = msgs.length - 1;
    $("#c-thread").innerHTML = html`${msgs.map((m, i) => (m.role === "user" ? userBubble(m) : botCard(m, i === last ? r : null)))}`;
    $("#c-thread").lastElementChild?.scrollIntoView({ behavior: "smooth", block: "start" });
    if (r.handoff) toast(`상담원에게 연결했습니다 (${r.ticket?.id})`, "ok");
    loadRecent();
  } catch {
    $("#c-pending")?.remove();  // 오류는 busy 가 알림으로 보여 준다
  }
}
$("#c-send").onclick = send;
$("#c-text").addEventListener("keydown", e => { if (e.key === "Enter" && e.ctrlKey) send(); });

// ── AS8 피드백 ─────────────────────────────────────────────────────────────
async function feedback(btn, resolved) {
  if (!cur) return;
  const r = await busy(btn, () => api(`/api/as/sessions/${cur.id}/feedback`, { method: "POST", body: { resolved, satisfaction: +$("#c-sat").value || null, comment: $("#c-comment").value.trim() } }));
  toast(resolved ? "해결로 기록했습니다" : `티켓 ${r.ticket?.id} 을 만들어 상담원에게 넘겼습니다`, "ok");
  $("#c-comment").value = ""; $("#c-sat").value = "";
  await openSession(cur.id);
  loadRecent();
}
$("#c-yes").onclick = e => feedback(e.target, true);
$("#c-no").onclick = e => feedback(e.target, false);

bindCtx();
loadSetup();
loadLlm();
loadRecent();
// 티켓 화면의 '대화 보기' 링크(?sid=)가 먼저, 없으면 이 브라우저에서 마지막으로 보던 상담
const saved = new URLSearchParams(location.search).get("sid") || localGet(SID_KEY);
if (saved) openSession(saved);
