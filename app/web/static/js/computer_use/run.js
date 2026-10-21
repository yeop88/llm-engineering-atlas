// computer_use/run.html 화면 스크립트 — 과제 실행 · 걸음 · 상태 확인(CU2 · CU3), 위험 행동 승인 · 이어 가기(CU4)
let TASKS = [];
const llm = () => ({ provider: $("#r-provider").value || null, model: $("#r-model").value.trim() || null });

function runHtml(r) {
  const c = r.check;
  return html`<div class="row small"><span class="mono">${r.id}</span> ${r.task} · <span class="badge ${r.status === "waiting" ? "warn" : ""}">${r.status === "waiting" ? "승인 대기" : r.status}</span>
    ${c ? html`<span class="badge ${c.success ? "ok" : "err"}">${c.success ? "성공" : c.goal_met ? "목표는 이뤘으나 인젝션을 따름" : "실패"}</span>${c.injection.length ? html` <span class="badge err">${c.injection.join(", ")}</span>` : ""}` : ""}
    · 토큰 ${r.tokens ?? 0}</div>
    <ol class="small">${html.join((r.log || []).map(s => html`<li><span class="mono">${JSON.stringify(s.action)}</span>${s.target ? html` <b>${s.target}</b>` : ""}
      ${s.approval ? html` <span class="badge ${s.approval === "denied" ? "err" : "warn"}">${{ auto: "자동 승인", approved: "승인됨", denied: "거부", waiting: "승인 대기" }[s.approval]}</span>` : ""}
      ${s.blocked ? html` <span class="badge err">막힘</span>` : ""}${s.result ? html` <span class="muted">${s.result.error || (s.result.changed === false ? "바뀐 것 없음" : "")}${(s.result.alerts || []).length ? ` · 알림: ${s.result.alerts.join(" / ")}` : ""}</span>` : ""}
      ${s.thought ? html`<div class="muted">${s.thought}</div>` : ""}</li>`), "")}</ol>
    ${r.summary ? html`<div class="small">요약: ${r.summary}</div>` : ""}
    ${r.final ? html`<details><summary class="small">최종 사이트 상태</summary><pre class="mono small pre">${JSON.stringify(r.final, null, 1)}</pre></details>` : ""}`;
}

function showWaiting(r) {
  if (r.status !== "waiting") return;
  $("#a-out").innerHTML = html`<div class="stack"><div><b>${r.task}</b> 실행이 <b>'${r.target}'</b> 앞에서 멈췄습니다 — 되돌릴 수 없는 행동입니다.</div>
    <pre class="mono small pre">${JSON.stringify(r.pending)}</pre><div class="row"><button class="btn primary" data-ok="1">승인</button> <button class="btn danger" data-ok="0">거부</button></div></div>`;
  $$("[data-ok]", $("#a-out")).forEach(btn => btn.onclick = () => runJobInto(btn, `/api/computer-use/runs/${r.id}/approve`, { approve: btn.dataset.ok === "1", ...llm() }, $("#r-progress"), done));
}

function done(r) {
  $("#r-out").innerHTML = runHtml(r);
  if (r.status === "waiting") showWaiting(r); else $("#a-out").textContent = "멈춘 실행이 없습니다.";
  loadRuns();
}

$("#r-task").onchange = () => { $("#r-goal").textContent = (TASKS.find(t => t.id === $("#r-task").value) || {}).goal || ""; };
$("#r-run").onclick = e => runJobInto(e.target, "/api/computer-use/runs", { task: $("#r-task").value, max_steps: +$("#r-steps").value || 15, ...llm(),
  config: { observe: $("#r-observe").value, approval: $("#r-approval").value, isolate: $("#r-isolate").checked, allowlist: $("#r-allow").checked } }, $("#r-progress"), done)
  .catch(err => ui.error($("#r-out"), err));

async function loadRuns() {
  const o = await api("/api/computer-use/overview");
  $("#a-runs").innerHTML = o.runs.length ? html`<div class="table-wrap"><table><tr><th>실행</th><th>과제</th><th>상태</th><th>결과</th><th>시각</th><th></th></tr>
    ${html.join(o.runs.map(r => html`<tr><td class="mono small">${r.id}</td><td>${r.task}</td><td>${r.status}</td><td>${r.check ? (r.check.success ? "성공" : "실패") : "-"}</td><td class="small">${r.created_at}</td>
      <td><button class="btn sm" data-show="${r.id}">보기</button></td></tr>`), "")}</table></div>` : html`<p class="small muted">실행 기록 없음</p>`;
}
$("#a-runs").addEventListener("click", e => {
  const b = e.target.closest("[data-show]");
  if (b) api(`/api/computer-use/runs/${b.dataset.show}`).then(r => { $("#r-out").innerHTML = runHtml(r); showWaiting(r); }).catch(err => toast(err.message, "err"));
});

(async () => {
  TASKS = (await api("/api/computer-use/overview")).tasks;
  $("#r-task").innerHTML = html`${TASKS.map(t => html`<option value="${t.id}">${t.id}${t.injection ? " (인젝션 있음)" : ""}</option>`)}`;
  $("#r-task").onchange();
  await loadRuns();
})().catch(e => ui.error($("#r-out"), e));
