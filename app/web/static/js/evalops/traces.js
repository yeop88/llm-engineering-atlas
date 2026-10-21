// 평가 · 관측 E3 · E4: 비용 · 지연 대시보드, 요청 목록(표시 · 검색으로 거르기), 한 건 상세(단계 시간 · 근거 · 검증 · 가드레일)
const KIND = { answer: "답변 생성", as: "AS 상담", ab: "A/B 실험", flow: "연결 실행", agent: "에이전트", redteam: "레드팀" };
const STEP = { guard_input: "입력 방어", search: "검색", guard_context: "근거 검사", llm: "LLM 답변", verify: "검증", guard_output: "출력 정책" };
const FLAG_CLS = { 느림: "warn", 실패: "err", 차단: "err", "근거 약함": "warn", "관련 없음": "warn", 거절: "muted", 싫어요: "err" };
const FAIL = { retrieval: "검색 실패", citation: "인용 · 근거 실패", off_topic: "질문과 상관없는 답", over_refusal: "과도한 거절", policy: "정책 위반 · 차단" };
const GROUPS = { by_day: "날짜별", by_route: "경로별", by_model: "모델별", by_kind: "종류별" };
let dash = null;

const ms = v => (v == null ? "-" : v >= 10000 ? `${(v / 1000).toFixed(1)}s` : `${Math.round(v)}ms`);
const money = v => (v == null ? "-" : v === 0 ? "0" : `$${Number(v).toFixed(v < 0.01 ? 6 : 4)}`);
const ratio = v => (v == null ? "-" : `${Math.round(v * 100)}%`);
const flagBadges = fl => html.join((fl || []).map(f => html`<span class="badge ${FLAG_CLS[f] || ""}">${f}</span>`), " ");
const fbBadge = f => (f === 1 ? html`<span class="badge ok">좋아요</span>` : f === -1 ? html`<span class="badge err">싫어요</span>` : "");
const filters = () => `days=${$("#t-days").value}${$("#t-kind").value ? `&kind=${$("#t-kind").value}` : ""}`;
const EMPTY = "아직 요청 기록이 없습니다. 답변 생성 화면에서 질문하거나 AS 상담 · A/B 실험을 쓰면 요청마다 기록이 쌓입니다.";

// ── 비용 · 지연 대시보드 ────────────────────────────────────────────────────
async function loadCost() {
  const box = $("#c-out");
  ui.loading(box);
  try { dash = await api(`/api/evalops/cost?${filters()}`); } catch (e) { return ui.error(box, e); }
  if (!dash.n) return ui.empty(box, EMPTY, { href: "/rag/answer", label: "답변 생성으로" });
  const o = dash.overall, per = dash.per_answer;
  const stat = (label, v, sub) => html`<div class="stat"><div class="label">${label}</div><div class="value">${v}</div><div class="small muted">${sub}</div></div>`;
  const noPrice = !Object.keys(dash.prices || {}).length;
  box.innerHTML = html`<div class="grid cols-4">
      ${stat("요청", fmtNum(dash.n), html`실패 ${o.errors} · 차단 ${o.blocked}`)}
      ${stat("지연 p50 / p95", html`${ms(o.p50_ms)} <span class="small muted">/ ${ms(o.p95_ms)}</span>`, `평균 ${ms(o.mean_ms)}`)}
      ${stat("토큰 (답변당)", html`${fmtNum(per.tokens_in)} → ${fmtNum(per.tokens_out)}`, `전체 입력 ${fmtNum(o.tokens_in)} · 출력 ${fmtNum(o.tokens_out)}`)}
      ${stat("비용", money(o.cost), html`답변당 ${money(per.cost)}${noPrice ? " · 단가 미설정(LLM_PRICES)" : ""}`)}
    </div>
    <h3>단계별 시간 <span class="small muted">어디에 시간이 쓰이나 — 비율은 전체 요청 시간 대비</span></h3>
    <div class="trace">${dash.steps.map(s => html`<div class="trace-step" title="${s.step} · ${s.n}회"><div><b>${STEP[s.step] || s.step}</b></div>
      <div><span class="ms">${ms(s.mean_ms)}</span> <span class="muted">평균</span></div><div class="muted">p95 ${ms(s.p95_ms)} · ${ratio(s.share)}</div></div>`)}</div>
    <div class="row mt-2"><div class="field"><label for="c-group">묶어 보기</label><select id="c-group">${Object.entries(GROUPS).map(([k, v]) => html`<option value="${k}">${v}</option>`)}</select></div></div>
    <div id="c-table"></div>`;
  $("#c-group").onchange = renderGroup;
  renderGroup();
}
function renderGroup() {
  const k = $("#c-group").value, rows = dash[k] || [];
  $("#c-table").innerHTML = html`<div class="table-wrap scroll-md"><table><tr><th>${GROUPS[k]}</th><th class="num">요청</th><th class="num">p50</th><th class="num">p95</th><th class="num">입력 토큰</th><th class="num">출력 토큰</th><th class="num">비용</th><th class="num">실패 · 차단</th></tr>
    ${(k === "by_day" ? rows.slice().reverse() : rows).map(r => html`<tr><td>${k === "by_kind" ? KIND[r.key] || r.key : r.key}</td><td class="num">${fmtNum(r.n)}</td><td class="num">${ms(r.p50_ms)}</td><td class="num">${ms(r.p95_ms)}</td>
      <td class="num">${fmtNum(r.tokens_in)}</td><td class="num">${fmtNum(r.tokens_out)}</td><td class="num">${money(r.cost)}</td><td class="num">${r.errors} · ${r.blocked}</td></tr>`)}</table></div>`;
}

// ── 요청 목록 ──────────────────────────────────────────────────────────────
async function loadList() {
  const box = $("#t-list");
  ui.loading(box);
  const q = $("#t-q").value.trim();
  let res;
  try {
    res = await api(`/api/evalops/traces?${filters()}${$("#t-flag").value ? `&flag=${encodeURIComponent($("#t-flag").value)}` : ""}${q ? `&q=${encodeURIComponent(q)}` : ""}`);
  } catch (e) { return ui.error(box, e); }
  if (!res.n) return ui.empty(box, EMPTY, { href: "/rag/answer", label: "답변 생성으로" });
  if (!res.rows.length) return ui.empty(box, `조건에 맞는 요청이 없습니다 (기간 안 전체 ${res.n}건).`);
  box.innerHTML = html`<div class="small muted">기간 안 ${fmtNum(res.n)}건 중 ${fmtNum(res.rows.length)}건 · '느림' 기준 = p95 ${ms(res.slow_ms)}</div>
    <div class="table-wrap scroll-lg"><table><tr><th>#</th><th>시각</th><th>종류</th><th>질문</th><th>모델</th><th class="num">시간</th><th class="num">토큰</th><th class="num">비용</th><th>표시</th></tr>
    ${res.rows.map(t => html`<tr><td><button class="btn sm" data-trace="${t.id}">#${t.id}</button></td><td class="small nowrap">${fmtDate(t.created_at)}</td>
      <td class="small">${KIND[t.kind] || t.kind}${t.arm ? html` <span class="badge">${t.arm}</span>` : ""}${t.route ? html`<div class="muted">${t.route}</div>` : ""}</td>
      <td class="small">${t.question}</td><td class="small mono">${t.model || "-"}</td><td class="num">${ms(t.total_ms)}</td>
      <td class="num small">${fmtNum(t.tokens_in)}→${fmtNum(t.tokens_out)}</td><td class="num small">${money(t.cost)}</td>
      <td class="small">${flagBadges(t.flags)} ${t.status !== "ok" && !t.flags.length ? html`<span class="badge err">${t.status}</span>` : ""}</td></tr>`)}</table></div>`;
}
$("#t-list").addEventListener("click", e => { const b = e.target.closest("[data-trace]"); if (b) openTrace(+b.dataset.trace); });

// ── 한 건 상세 ─────────────────────────────────────────────────────────────
function guardInfo(g) {
  if (!g || !Object.keys(g).length) return html`<span class="muted">기록 없음</span>`;
  const out = g.output || {}, pii = Object.entries(out.pii || {});
  const parts = [];
  if (g.input) parts.push(g.input.suspicious ? html`<span class="badge warn" title="${html.join((g.input.hits || []).map(h => `${h.rule}: ${h.match}`), " / ")}">입력 인젝션 의심 (규칙 ${g.input.score})</span>` : html`<span class="badge ok">입력 이상 없음</span>`);
  if (g.context?.length) parts.push(html`<span class="badge warn">지시가 숨은 근거 ${g.context.length}개</span>`);
  if (g.restricted) parts.push(html`<span class="badge muted">권한 제한 적용</span>`);
  if (pii.length) parts.push(html`<span class="badge warn">개인정보 ${html.join(pii.map(([k, n]) => `${k} ${n}`), " · ")}</span>`);
  if (out.violations?.length) parts.push(html`<span class="badge err" title="${html.join(out.violations.map(v => `${v.rule}: ${v.match}`), " / ")}">정책 위반 ${out.violations.length}</span>`);
  if (out.action) parts.push(html`<span class="badge ${out.action === "pass" ? "ok" : out.action === "block" ? "err" : "warn"}">출력 정책 ${({ pass: "통과", fix: "수정", block: "차단" })[out.action] || out.action}</span>`);
  if (g.action === "block") parts.push(html`<span class="badge err">요청 차단</span>`);
  if (g.changed) parts.push(html`<span class="badge muted">답을 고쳐 내보냄</span>`);
  return html.join(parts, " ");
}
async function openTrace(id) {
  const box = $("#t-detail");
  box.hidden = false;
  ui.loading(box);
  let t;
  try { t = await api(`/api/evalops/traces/${id}`); } catch (e) { return ui.error(box, e); }
  const v = t.verify || {}, s = t.signals || {};
  const total = t.total_ms || 1;
  box.innerHTML = html`<div class="row between"><h2 class="m-0">요청 #${t.id}</h2><span class="small muted">${fmtDate(t.created_at)} · ${KIND[t.kind] || t.kind} · ${t.user}${t.client ? html` (${t.client})` : ""}</span></div>
    <div class="row small">${flagBadges(t.flags)} ${html.join((t.failures || []).map(f => html`<span class="badge err" title="개선 루프 분류">${FAIL[f] || f}</span>`), " ")} ${fbBadge(t.feedback)}${t.feedback_reason ? html` <span class="small">${t.feedback_reason}</span>` : ""}${t.feedback_note ? html` <span class="small muted">"${t.feedback_note}"</span>` : ""}</div>
    <div class="q-bubble">${t.question}</div>
    <div class="answer pre">${t.answer || html`<span class="muted">(답 없음)</span>`}</div>
    ${t.error ? html`<div class="errbox">${t.error}</div>` : ""}
    <h3>단계 <span class="small muted">전체 ${ms(t.total_ms)}</span></h3>
    <div class="trace">${(t.steps || []).map(st => html`<div class="trace-step" title="${JSON.stringify(st)}"><div><b>${STEP[st.name] || st.name}</b></div>
      <div><span class="ms">${ms(st.ms)}</span> <span class="muted">${ratio(st.ms / total)}</span></div>
      <div class="muted">${st.n != null ? html`결과 ${st.n}` : ""}${st.flagged ? html`의심 ${st.flagged}` : ""}${st.tokens_out != null ? html`토큰 ${st.tokens_in}→${st.tokens_out}` : ""}</div></div>`)}</div>
    <div class="grid cols-2">
      <div class="kv">
        <div>모델</div><div class="mono">${t.model || "-"}</div>
        <div>경로</div><div>${t.route || "-"}</div>
        <div>컬렉션</div><div>${t.collection_id ? html`<a href="/rag/collections/${t.collection_id}">#${t.collection_id}</a>` : "-"}</div>
        <div>토큰 · 비용</div><div>${fmtNum(t.tokens_in)} → ${fmtNum(t.tokens_out)} · ${money(t.cost)}</div>
        <div>상태</div><div>${t.status}</div>
        ${t.session_id ? html`<div>세션</div><div class="mono small">${t.session_id}</div>` : ""}
        ${t.experiment_id ? html`<div>실험</div><div><a href="/evalops/experiments?exp=${t.experiment_id}">#${t.experiment_id}</a> · 팔 ${t.arm}</div>` : ""}
      </div>
      <div class="kv">
        <div>근거 일치</div><div>${ratio(v.supported_ratio)}${v.refused ? html` <span class="badge muted">거절</span>` : ""}</div>
        <div>질문 관련성</div><div>${ratio(v.relevant_ratio)}${v.off_topic ? html` <span class="badge warn">관련 낮은 문장 ${v.off_topic}</span>` : ""}</div>
        <div>잘못된 인용</div><div>${v.invalid_citations?.length ? html.join(v.invalid_citations, ", ") : "없음"}${v.citations?.n ? html` · 번호 ${v.citations.n}개 중 자료에 없음 ${v.citations.not_found}` : ""}</div>
        <div>검색 확신도</div><div>1위 ${num3(s.top1)} · 1·2위 차 ${num3(s.gap)} · 결과 ${s.n ?? "-"}</div>
        <div>가드레일</div><div>${guardInfo(t.guard)}</div>
      </div>
    </div>
    <details><summary class="small">근거 ${(t.sources || []).length}개</summary><div class="stack mt-2">${html.or(html.join((t.sources || []).map((x, i) => html`<div class="small"><span class="cite">${i + 1}</span> ${x.filename || "-"} <span class="muted mono">문서 #${x.document_id} · 청크 ${x.chunk_id}</span></div>`)), html`<div class="small muted">근거 없음</div>`)}</div></details>
    <details><summary class="small">기록 원본 (해시 사슬)</summary><div class="small mono break-all mt-2">hash ${t.hash}<br>prev ${t.prev_hash || "-"}</div></details>`;
  box.scrollIntoView({ behavior: "smooth", block: "start" });
}
const num3 = v => (v == null ? "-" : Number(v).toFixed(3));

// 정기 점검 · 경보: 주기 · 마지막 · 다음 실행, 지금 돌리기, 최근 경보(실행 기록에서 계산)
const RUN_PAGE = { redteam: "/guardrails/redteam", drift: "/evalops/drift", regression: "/evalops/sets#regression" };
async function loadWatch() {
  const box = $("#w-out");
  try {
    const w = await api("/api/evalops/watch?days=30");
    const sched = html`<div class="table-wrap"><table><tr><th>점검</th><th>주기</th><th>마지막 실행</th><th>다음 실행</th><th></th></tr>
      ${html.join(w.schedules.map(s => html`<tr><td><b>${s.label}</b>${s.mode ? html` <span class="small muted">방어 ${s.mode}</span>` : ""}</td>
        <td>${s.enabled ? `${s.every_hours}시간마다` : html`<span class="badge">꺼짐</span>`}</td>
        <td class="small">${s.last_at ? html`<a href="${RUN_PAGE[s.kind]}">${fmtDate(s.last_at)}</a>` : "-"}</td>
        <td class="small">${s.not_ready ? html`<span class="badge warn">준비 안 됨</span> ${s.not_ready}` : s.next_at ? fmtDate(s.next_at) : "-"}</td>
        <td><button class="btn sm" data-watch="${s.kind}">지금 점검</button></td></tr>`), "")}</table></div>`;
    const alerts = w.alerts.length
      ? html`<ul class="stack">${html.join(w.alerts.map(a => html`<li><span class="badge err">경보</span> <b>${a.label}</b> · ${a.message}
          <span class="small muted">— ${fmtDate(a.at)} · ${a.title}${a.scheduled ? " · 정기" : ""}</span></li>`), "")}</ul>`
      : html`<div class="small"><span class="badge ok">경보 없음</span> 최근 30일 점검에서 나빠진 것이 없습니다.</div>`;
    box.innerHTML = html`${sched}<h3 class="mt-2">최근 경보 (30일)</h3>${alerts}
      <div class="small muted">${w.webhook ? "경보를 ALERT_WEBHOOK 으로도 보냅니다." : "ALERT_WEBHOOK 이 없어 이 화면에만 표시합니다."}</div>`;
    $$("[data-watch]", box).forEach(b => { b.onclick = () => runJobInto(b, `/api/evalops/watch/${b.dataset.watch}/run`, {}, $("#w-progress"), () => { toast("점검을 마쳤습니다"); loadWatch(); }); });
  } catch (e) { ui.error(box, e); }
}

function reload() { loadCost(); loadList(); loadWatch(); }
$("#t-reload").onclick = reload;
$("#t-days").onchange = reload;
$("#t-kind").onchange = reload;
$("#t-search").onclick = loadList;
$("#t-flag").onchange = loadList;
$("#t-q").addEventListener("keydown", e => { if (e.key === "Enter") loadList(); });
reload();
// 다른 화면(피드백 · 개선 루프)의 ?trace= 링크로 들어오면 그 기록을 바로 연다
const wantTrace = new URLSearchParams(location.search).get("trace");
if (wantTrace) openTrace(+wantTrace);
