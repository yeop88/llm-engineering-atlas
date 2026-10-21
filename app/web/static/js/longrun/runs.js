// longrun/runs.html 화면 스크립트 — 계획 보기 · 시작(LR1), 업무 목록 · 단계 체크포인트(LR3), 이어 하기 · 범위 늘리기 · 되돌리기 · 취소(LR2 · LR5 · LR7)
let CAT = null, PLAN = null;
const RUN = { planned: ["", "계획"], running: ["warn", "실행 중"], waiting: ["warn", "승인 대기"], paused: ["warn", "멈춤"], done: ["ok", "완료"], failed: ["err", "실패"], canceled: ["", "취소"], rolled_back: ["", "되돌림"] };
const STEP = { pending: ["", "대기"], running: ["warn", "실행 중"], done: ["ok", "끝"], failed: ["err", "실패"], waiting: ["warn", "승인 대기"], compensated: ["", "되돌림"], skipped: ["", "건너뜀"] };
const badge = (m, s) => html`<span class="badge ${(m[s] || ["", s])[0]}">${(m[s] || ["", s])[1]}</span>`;

function body() {
  return {
    planner: $("#l-planner").value, template: $("#l-template").value, goal: $("#l-goal").value.trim(),
    params: { days: +$("#l-days").value || 90, collection_id: +$("#l-col").value || null },
    scope: { max_steps: +$("#l-steps").value || 30, max_seconds: +$("#l-secs").value || 3600, max_cost: +$("#l-cost").value || 0,
      actions: $("#l-acts").value.split(",").map(s => s.trim()).filter(Boolean), collections: [] },
    provider: Ctx.get().provider || null, model: Ctx.get().model || null,
  };
}
const actTitle = a => CAT.actions.find(x => x.name === a)?.title || a;

function planHtml(p, notes) {
  return html`<div class="small"><b>${p.title || p.goal}</b> · ${p.planner === "llm" ? "LLM 계획" : "템플릿"} · 완료 조건 ${(p.criteria || []).join(", ") || "없음"}</div>
    ${notes?.length ? html`<ul class="small">${html.join(notes.map(n => html`<li><span class="badge warn">고침</span> ${n}</li>`), "")}</ul>` : ""}
    <ol class="small">${html.join(p.steps.map(s => html`<li><b>${s.name}</b> <span class="mono muted">${s.action}</span>${CAT.actions.find(a => a.name === s.action)?.irreversible ? html` <span class="badge err">되돌릴 수 없음</span>` : ""}
      ${s.deps?.length ? html` <span class="muted">← ${s.deps.map(d => d + 1).join(", ")}</span>` : ""}</li>`), "")}</ol>`;
}

async function loadRuns() {
  const rows = await api("/api/longrun/runs");
  $("#l-runs").innerHTML = rows.length ? html`<div class="table-wrap"><table><tr><th>#</th><th>목표</th><th>상태</th><th>쓴 것</th><th>판정</th><th>때</th></tr>
    ${html.join(rows.map(r => html`<tr><td><a href="#" data-run="${r.id}">${r.id}</a></td><td class="small">${r.goal.slice(0, 80)}</td><td>${badge(RUN, r.status)}</td>
      <td class="small">${r.usage.steps || 0}단계 · ${r.usage.seconds || 0}초${r.usage.tokens ? ` · ${fmtNum(r.usage.tokens)}토큰` : ""}</td>
      <td class="small">${r.verdict?.items ? (r.verdict.ok ? html`<span class="badge ok">완료 조건 통과</span>` : html`<span class="badge warn">검토 필요</span>`) : ""}</td>
      <td class="small nowrap">${r.at.slice(0, 16).replace("T", " ")}</td></tr>`), "")}</table></div>` : html`<div class="small muted">업무가 없습니다.</div>`;
  $$("[data-run]", $("#l-runs")).forEach(a => a.onclick = ev => { ev.preventDefault(); openRun(+a.dataset.run); });
}

async function openRun(id) {
  const r = await api(`/api/longrun/runs/${id}`);
  const can = s => ["planned", "paused", "waiting", "failed"].includes(s);
  $("#l-detail").innerHTML = html`<div class="card stack mt-2"><div class="row"><b>업무 #${r.id}</b> ${badge(RUN, r.status)} <span class="small muted">${r.goal}</span></div>
    <div class="row">${can(r.status) && r.status !== "failed" ? html`<button class="btn sm primary" data-go>이어 하기</button>` : ""}
      ${r.status === "paused" || r.status === "failed" ? html`<button class="btn sm" data-go>실패 · 반려 단계부터 다시</button>` : ""}
      ${r.status === "paused" ? html`<button class="btn sm" data-extend>범위 늘리기(+10단계 · +30분)</button>` : ""}
      ${!["running", "rolled_back"].includes(r.status) && r.steps.some(s => s.status === "done" && CAT.actions.find(a => a.name === s.action)?.compensable) ? html`<button class="btn sm danger" data-rollback>되돌리기</button>` : ""}
      ${!["done", "failed", "canceled", "rolled_back"].includes(r.status) ? html`<button class="btn sm" data-cancel>취소</button>` : ""}
      <span class="small muted">범위: ${r.scope.max_steps}단계 · ${r.scope.max_seconds}초${r.scope.max_cost ? ` · $${r.scope.max_cost}` : ""} · 쓴 것 ${r.usage.steps || 0}단계 · ${r.usage.seconds || 0}초</span></div>
    <div class="table-wrap"><table><tr><th>#</th><th>단계</th><th>상태</th><th>시도</th><th>결과(체크포인트)</th></tr>
    ${html.join(r.steps.map(s => html`<tr><td class="small">${s.idx + 1}</td><td class="small"><b>${s.name}</b> <span class="mono muted">${s.action}</span>${s.irreversible ? html` <span class="badge err">되돌릴 수 없음</span>` : ""}
        ${s.approved_by ? html`<div class="muted">승인 ${s.approved_by}</div>` : ""}</td><td>${badge(STEP, s.status)}</td><td class="small">${s.attempts}</td>
      <td class="small">${s.error ? html`<div class="errbox small">${s.error}</div>` : ""}${s.output && Object.keys(s.output).length ? html`<details><summary>보기</summary>${s.output.report ? html`<div class="pre small">${s.output.report}</div>` : ""}
        <pre class="pre small scroll-md">${JSON.stringify(s.output.report ? { ...s.output, report: "(위)" } : s.output, null, 1).slice(0, 4000)}</pre></details>` : ""}</td></tr>`), "")}</table></div>
    ${r.verdict?.items ? html`<div class="small"><b>완료 판정 (LR6)</b> ${html.join(r.verdict.items.map(i => html`<div>${i.ok ? html`<span class="badge ok">통과</span>` : html`<span class="badge err">미달</span>`} ${i.key} — ${i.detail}</div>`), "")}</div>` : ""}
    <details class="small"><summary>기록 ${r.log.length}</summary><ul>${html.join(r.log.map(l => html`<li><span class="mono">${l.at.slice(11, 19)}</span> <span class="badge">${l.kind}</span> ${l.msg}</li>`), "")}</ul></details></div>`;
  const box = $("#l-detail");
  $$("[data-go]", box).forEach(b => b.onclick = () => busy(b, () => api(`/api/longrun/runs/${id}/go`, { method: "POST", body: {} })).then(j => watch(id, j)).catch(e => toast(e.message, "err")));
  $("[data-extend]", box)?.addEventListener("click", e => busy(e.target, () => api(`/api/longrun/runs/${id}/extend`, { method: "POST", body: { max_steps: 10, max_seconds: 1800 } })).then(() => openRun(id)).catch(err => toast(err.message, "err")));
  $("[data-cancel]", box)?.addEventListener("click", e => busy(e.target, () => api(`/api/longrun/runs/${id}/cancel`, { method: "POST" })).then(() => { openRun(id); loadRuns(); }).catch(err => toast(err.message, "err")));
  $("[data-rollback]", box)?.addEventListener("click", async e => {
    if (!(await ui.confirm("끝난 단계의 보상 작업(보낸 보고서 파일 삭제 · 웹훅 철회 알림)을 나중 단계부터 실행합니다.", { ok: "되돌리기", danger: true }))) return;
    busy(e.target, () => api(`/api/longrun/runs/${id}/rollback?confirm=true`, { method: "POST" })).then(() => { openRun(id); loadRuns(); }).catch(err => toast(err.message, "err"));
  });
}

async function watch(id, job) {
  await pollJob(job.id, () => {}, 1500).catch(() => {});
  openRun(id);
  loadRuns();
}

$("#l-preview").onclick = e => busy(e.target, () => api("/api/longrun/plan", { method: "POST", body: body() }))
  .then(r => { PLAN = r.plan; $("#l-plan").innerHTML = planHtml(r.plan, r.notes); }).catch(err => ui.error($("#l-plan"), err));
$("#l-start").onclick = e => busy(e.target, () => api("/api/longrun/runs", { method: "POST", body: { ...body(), plan: PLAN } }))
  .then(r => { toast(`업무 #${r.id} 를 시작했습니다`); PLAN = null; loadRuns(); openRun(r.id); if (r.job) watch(r.id, r.job); }).catch(err => toast(err.message, "err"));

(async () => {
  CAT = await api("/api/longrun/catalog");
  $("#l-template").innerHTML = html`${Object.entries(CAT.templates).map(([k, t]) => html`<option value="${k}">${t.title}</option>`)}`;
  await setupCollectionPickers({ col: $("#l-col") });
  loadRuns();
  const want = new URLSearchParams(location.search).get("run");
  if (want) openRun(+want);
})().catch(e => ui.error($("#l-runs"), e));
