// G7 레드팀 시험: 공격 세트 개요 → 방어 모드 · 유형 · LLM 을 골라 실행 → 유형별 결과 · 질문별 판정 → 실행 기록 두 개 비교(예: off 대 enforce)
const TYPE = {
  injection_direct: "직접 인젝션",
  injection_indirect: "간접 인젝션 (문서 속 지시)",
  pii: "개인정보 노출",
  acl: "권한 없는 문서",
  danger: "위험한 자가 조치",
  benign: "정상 질문 (오탐)",
};
const MODE_LABEL = { off: "off", mask: "mask", enforce: "enforce" };
// 통과 · 실패는 색과 함께 기호 · 글자로 — 색만으로 구분하지 않게
const passBadge = ok => (ok ? html`<span class="badge ok">✓ 통과</span>` : html`<span class="badge err">✗ 실패</span>`);
const rateBadge = (rate, good = 0.9) => (rate == null ? html`<span class="muted">-</span>`
  : html`<span class="badge ${rate >= good ? "ok" : rate >= 0.5 ? "warn" : "err"}">${pct(rate)}%</span>`);

async function loadPreset() {
  try {
    const p = await api("/api/guardrails/redteam/preset");
    const by = {};
    p.items.forEach(i => { by[i.type] = (by[i.type] || 0) + 1; });
    $("#t-preset").innerHTML = html`<div class="small"><b>${p.name}</b> · 질문 ${p.n}개</div>
      <div class="row">${p.types.map(t => html`<span class="badge">${TYPE[t] || t} ${by[t]}</span>`)}</div>
      <div class="table-wrap"><table><tr><th>시험 문서</th><th>볼 수 있는 그룹</th></tr>
        ${p.documents.map(d => html`<tr><td class="small">${d.filename}</td><td>${d.acl?.length ? html.join(d.acl.map(g => html`<span class="badge warn">🔒 ${g}</span>`), " ") : html`<span class="badge muted">모두</span>`}</td></tr>`)}</table></div>
      <details><summary class="small">질문 목록</summary><div class="table-wrap scroll-md mt-2"><table><tr><th>id</th><th>유형</th><th>질문</th><th>그룹</th></tr>
        ${p.items.map(i => html`<tr><td class="small nowrap">${i.id}</td><td class="small nowrap">${TYPE[i.type] || i.type}</td><td class="small">${i.question}</td><td class="small">${html.join(i.groups || ["*"], ", ")}</td></tr>`)}</table></div></details>`;
    $("#t-types").innerHTML = html`${p.types.map(t => html`<label class="row small m-0"><input type="checkbox" name="t-type" value="${t}"> ${TYPE[t] || t}</label>`)}`;
  } catch (e) { ui.error($("#t-preset"), e); }
}

function summaryHtml(r) {
  const s = r.summary;
  const attack = s.attack_pass_rate == null ? null : 1 - s.attack_pass_rate;
  return html`<div class="grid cols-3">
      <div class="stat"><div class="label">방어 통과율 (공격)</div><div class="value">${pct(s.attack_pass_rate)}%</div><div class="small muted">높을수록 좋음</div></div>
      <div class="stat"><div class="label">공격 성공률</div><div class="value">${pct(attack)}%</div><div class="small muted">낮을수록 좋음</div></div>
      <div class="stat"><div class="label">정상 질문 답함</div><div class="value">${pct(s.benign_pass_rate)}%</div><div class="small muted">낮으면 정상 질문을 막는 것(오탐)</div></div></div>
    <div class="table-wrap"><table><tr><th>유형</th><th class="num">질문</th><th class="num">통과</th><th class="num">통과율</th><th class="num">공격 성공률</th></tr>
      ${Object.entries(s.by_type).map(([t, v]) => html`<tr><td>${TYPE[t] || t}</td><td class="num">${v.n}</td><td class="num">${v.passed}</td><td class="num">${rateBadge(v.rate)}</td>
        <td class="num">${t === "benign" ? html`<span class="muted small">해당 없음</span>` : html`${pct(1 - v.rate)}%`}</td></tr>`)}</table></div>`;
}

function rowsHtml(rows) {
  return html`<div class="table-wrap scroll-lg"><table><tr><th>유형</th><th>질문</th><th>판정</th><th>이유</th><th>상태</th><th>답변 (앞부분)</th></tr>
    ${rows.map(x => html`<tr><td class="small nowrap">${TYPE[x.type] || x.type}</td><td class="small">${x.question}</td><td>${passBadge(x.passed)}</td>
      <td class="small">${x.why}</td><td class="small">${x.status === "blocked" ? html`<span class="badge warn">⛔ 차단</span>` : x.status || ""}</td>
      <td class="small muted pre">${(x.answer || "").slice(0, 160)}</td></tr>`)}</table></div>`;
}

function renderResult(r, box = $("#t-out")) {
  box.innerHTML = html`<div class="row between"><h3 class="m-0">결과 · 방어 ${MODE_LABEL[r.mode] || r.mode}</h3>
      <span class="small muted">${r.preset} · ${r.llm?.model || ""}${r.run_id ? html` · run #${r.run_id}` : ""}</span></div>
    ${summaryHtml(r)}${rowsHtml(r.rows)}`;
}

$("#t-run").onclick = e => {
  const types = $$('input[name="t-type"]:checked').map(x => x.value);
  const body = { mode: $("#t-mode").value, types, provider: $("#t-provider").value || null, model: $("#t-model").value.trim() || null };
  runJobInto(e.target, "/api/guardrails/redteam", body, $("#t-progress"), r => { renderResult(r); loadRuns(); });
};

// ── 실행 기록 · 비교 ──
async function loadRuns() {
  try {
    const runs = await api("/api/guardrails/redteam/runs?limit=30");
    if (!runs.length) {
      ui.empty($("#t-runs"), "아직 실행 기록이 없습니다");
      $("#t-a").innerHTML = $("#t-b").innerHTML = html`<option value="">기록 없음</option>`;
      return;
    }
    $("#t-runs").innerHTML = html`<div class="table-wrap scroll-sm"><table><tr><th>#</th><th>시각</th><th>방어 모드</th><th>제목</th><th class="num">방어 통과율</th><th class="num">정상 답함</th><th></th></tr>
      ${runs.map(r => html`<tr><td class="num small">${r.id}</td><td class="small nowrap">${fmtDate(r.created_at)}</td><td><span class="badge muted">${r.mode}</span></td><td class="small">${r.title}</td>
        <td class="num">${rateBadge(r.summary?.attack_pass_rate)}</td><td class="num">${rateBadge(r.summary?.benign_pass_rate)}</td>
        <td><button type="button" class="btn sm" data-run="${r.id}">보기</button></td></tr>`)}</table></div>`;
    const opts = html`${runs.map(r => html`<option value="${r.id}">#${r.id} · ${r.mode} · ${fmtDate(r.created_at)}</option>`)}`;
    $("#t-a").innerHTML = opts; $("#t-b").innerHTML = opts;
    // 기본 비교: 가장 최근의 off 실행과 enforce 실행(없으면 최근 두 개)
    const off = runs.find(r => r.mode === "off"), enf = runs.find(r => r.mode === "enforce");
    $("#t-a").value = String((off || runs[1] || runs[0]).id);
    $("#t-b").value = String((enf && enf !== off ? enf : runs[0]).id);
  } catch (e) { ui.error($("#t-runs"), e); }
}
$("#t-runs").addEventListener("click", async e => {
  const b = e.target.closest("button[data-run]");
  if (!b) return;
  const r = await busy(b, () => api(`/api/guardrails/redteam/runs/${b.dataset.run}`));
  renderResult(r);
  $("#t-out").scrollIntoView({ behavior: "smooth", block: "start" });
});

$("#t-cmp").onclick = async e => {
  if (!$("#t-a").value || !$("#t-b").value) return toast("비교할 실행 기록이 없습니다", "err");
  const [a, b] = await busy(e.target, () => Promise.all([$("#t-a").value, $("#t-b").value].map(id => api(`/api/guardrails/redteam/runs/${id}`))));
  const types = [...new Set([...Object.keys(a.summary.by_type), ...Object.keys(b.summary.by_type)])];
  const bRows = Object.fromEntries(b.rows.map(x => [x.id, x]));
  // 같은 질문 id 끼리 맞춰, 판정이 달라진 질문만 보인다(방어를 켜서 막힌 것 · 새로 뚫린 것)
  const changed = a.rows.filter(x => bRows[x.id] && bRows[x.id].passed !== x.passed);
  const diff = (x, y) => (x == null || y == null ? "" : html`${y - x >= 0 ? "+" : ""}${((y - x) * 100).toFixed(1)}%p`);
  const head = r => html`#${r.id} · ${r.mode}`;
  $("#t-cmp-out").innerHTML = html`<div class="table-wrap"><table><tr><th>유형</th><th class="num">${head(a)}</th><th class="num">${head(b)}</th><th class="num">차이</th></tr>
      <tr><td><b>방어 통과율 (공격)</b></td><td class="num">${rateBadge(a.summary.attack_pass_rate)}</td><td class="num">${rateBadge(b.summary.attack_pass_rate)}</td><td class="num">${diff(a.summary.attack_pass_rate, b.summary.attack_pass_rate)}</td></tr>
      <tr><td><b>정상 질문 답함</b></td><td class="num">${rateBadge(a.summary.benign_pass_rate)}</td><td class="num">${rateBadge(b.summary.benign_pass_rate)}</td><td class="num">${diff(a.summary.benign_pass_rate, b.summary.benign_pass_rate)}</td></tr>
      ${types.map(t => html`<tr><td>${TYPE[t] || t}</td><td class="num">${rateBadge(a.summary.by_type[t]?.rate)}</td><td class="num">${rateBadge(b.summary.by_type[t]?.rate)}</td>
        <td class="num">${diff(a.summary.by_type[t]?.rate, b.summary.by_type[t]?.rate)}</td></tr>`)}</table></div>
    <h3>판정이 달라진 질문 ${changed.length}개</h3>
    ${changed.length ? html`<div class="table-wrap scroll-md"><table><tr><th>유형</th><th>질문</th><th>${head(a)}</th><th>${head(b)}</th></tr>
      ${changed.map(x => html`<tr><td class="small nowrap">${TYPE[x.type] || x.type}</td><td class="small">${x.question}</td>
        <td class="small">${passBadge(x.passed)} ${x.why}</td><td class="small">${passBadge(bRows[x.id].passed)} ${bRows[x.id].why}</td></tr>`)}</table></div>`
      : html`<div class="small muted">두 실행에서 판정이 같습니다.</div>`}`;
};

async function loadLlmModels() {
  try { const m = await api("/api/llm/models"); $("#t-model-list").innerHTML = html.join(m.models.map(x => html`<option value="${x}">`), ""); } catch { /* 로컬 서버가 꺼져 있으면 목록 없음 */ }
}

loadPreset();
loadRuns();
loadLlmModels();
