// computer_use/eval.html 화면 스크립트 — 방어 설정별 성공률 · 인젝션을 따른 비율(CU5 · CU6), 기록 재생
const pct = v => (v == null ? "-" : `${(v * 100).toFixed(1)}%`);
const CONFIGS = [
  { observe: "raw", isolate: false, allowlist: false, approval: "approve" },
  { observe: "tree", isolate: false, allowlist: false, approval: "approve" },
  { observe: "tree", isolate: true, allowlist: false, approval: "approve" },
  { observe: "tree", isolate: true, allowlist: true, approval: "approve" },
];
const label = c => `${c.observe === "raw" ? "숨은 글까지" : "트리만"} · ${c.isolate ? "격리" : "격리 없음"} · ${c.allowlist ? "허용 도메인만" : "도메인 제한 없음"}`;

$("#e-run").onclick = e => runJobInto(e.target, "/api/computer-use/eval", { configs: CONFIGS, max_steps: +$("#e-steps").value || 15,
  provider: $("#e-provider").value || null, model: $("#e-model").value.trim() || null }, $("#e-progress"), r => {
  const tasks = r.results[0].rows.map(x => x.task);
  $("#e-out").innerHTML = html`<div class="small muted">${r.model} · ${r.seconds}초 · run #${r.run_id}</div>
    <div class="table-wrap"><table><tr><th>설정</th><th>성공률</th><th>목표 달성</th><th>인젝션을 따름</th><th>평균 걸음</th></tr>
    ${html.join(r.results.map(o => html`<tr><td class="small">${label(o.config)}</td><td><b>${pct(o.success)}</b></td><td>${pct(o.goal_met)}</td><td><b>${pct(o.injection_followed)}</b></td><td>${o.mean_steps}</td></tr>`), "")}</table></div>
    <div class="table-wrap"><table><tr><th>과제</th>${html.join(r.results.map((o, i) => html`<th>설정 ${i + 1}</th>`), "")}</tr>
    ${html.join(tasks.map(t => html`<tr><td>${t}</td>${html.join(r.results.map(o => { const x = o.rows.find(y => y.task === t); return html`<td class="small">
      <span class="badge ${x.success ? "ok" : "err"}">${x.success ? "성공" : "실패"}</span>${x.injection.length ? html` <span class="badge err">${x.injection.join(", ")}</span>` : ""} ${x.steps}걸음${x.blocked ? ` · 막힘 ${x.blocked}` : ""}</td>`; }), "")}</tr>`), "")}</table></div>`;
}).catch(err => ui.error($("#e-out"), err));

$("#p-go").onclick = e => busy(e.target, () => api(`/api/computer-use/runs/${$("#p-run").value}/replay`, { method: "POST" })).then(r => {
  $("#p-out").innerHTML = html`<span class="badge ${r.same ? "ok" : "err"}">${r.same ? "같은 최종 상태" : "결과가 다름"}</span> 재생 판정: ${r.check.success ? "성공" : "실패"}${r.check.injection.length ? ` · ${r.check.injection.join(", ")}` : ""}`;
}).catch(err => ui.error($("#p-out"), err));

(async () => {
  const o = await api("/api/computer-use/overview");
  const done = o.runs.filter(r => r.status === "done");
  $("#p-run").innerHTML = html`${done.map(r => html`<option value="${r.id}">${r.id} · ${r.task} · ${r.check?.success ? "성공" : "실패"}</option>`)}`;
})().catch(e => ui.error($("#p-out"), e));
