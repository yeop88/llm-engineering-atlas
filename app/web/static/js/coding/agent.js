// coding/agent.html 화면 스크립트 — 깬 코드 과제 만들기(CD6), 에이전트 실행 · 걸음 · diff · 리뷰 지적(CD2~CD5)
const pct = v => (v == null ? "-" : `${(v * 100).toFixed(1)}%`);
const TOOL = { plan: "계획", search: "찾기", read: "읽기", replace: "고치기", test: "테스트", done: "끝", invalid: "형식 오류", error: "오류" };

async function load() {
  const o = await api("/api/coding/overview");
  if (!$("#t-tests").value) $("#t-tests").value = o.default_tests.join(", ");
  $("#r-tasks").innerHTML = html`${o.tasks.map(t => html`<option value="${t.name}">${t.name} · ${t.n}과제 (시도 ${t.tried} · 살아남음 ${t.survived})</option>`)}`;
}

$("#t-build").onclick = e => runJobInto(e.target, "/api/coding/tasks", { name: $("#t-name").value.trim(), n: +$("#t-n").value || 10,
  tests: $("#t-tests").value.split(",").map(s => s.trim()).filter(Boolean) }, $("#t-progress"), r => {
  $("#t-out").innerHTML = html`<div class="small">과제 <b>${r.n}</b>개 · 돌연변이 시도 ${r.tried} · 테스트가 못 잡음(살아남음) ${r.survived}</div>`;
  load();
}).catch(err => ui.error($("#t-out"), err));

$("#t-refresh").onclick = async e => {
  if (!(await ui.confirm("작업 공간 원본을 지금 저장소로 다시 만들까요? 이미 만든 과제의 줄 번호가 달라질 수 있습니다."))) return;
  busy(e.target, () => api("/api/coding/refresh", { method: "POST" })).then(r => toast(`함수 ${r.functions}개로 다시 만듦`)).catch(err => toast(err.message, "err"));
};

function rowHtml(r) {
  return html`<details class="card p-2"><summary class="row small"><b>${r.task}</b> <span class="badge ${r.resolved ? "ok" : "err"}">${r.resolved ? "해결" : r.touched_tests ? "테스트를 고침(무효)" : "미해결"}</span>
    ${r.n_steps}걸음 · 고침 ${r.edits} · ${r.tokens} 토큰 · ${r.seconds}초 · diff ${r.diff_lines}줄${r.found_file ? "" : " · 깨진 파일을 고치지 않음"}
    ${r.review.length ? html`<span class="badge warn">리뷰 ${r.review.map(x => x.rule).join(", ")}</span>` : ""}</summary>
    <ol class="small">${html.join(r.steps.map(s => html`<li><span class="badge">${TOOL[s.tool] || s.tool}</span> ${s.thought || ""} <span class="mono">${s.input ? JSON.stringify(s.input).slice(0, 200) : ""}</span>
      ${s.observation ? html`<pre class="pre small m-0">${String(s.observation).slice(0, 600)}</pre>` : ""}</li>`), "")}</ol>
    ${r.diff ? html`<pre class="mono small pre">${r.diff}</pre>` : html`<p class="small muted">바꾼 것 없음</p>`}
    ${r.llm_review ? html`<div class="small">LLM 리뷰: ${r.llm_review.ok ? "문제 없음" : r.llm_review.issues.join(" / ")}</div>` : ""}</details>`;
}

$("#r-run").onclick = e => runJobInto(e.target, "/api/coding/run", { tasks: $("#r-tasks").value, ids: $("#r-ids").value.split(",").map(s => s.trim()).filter(Boolean),
  max_steps: +$("#r-steps").value || 12, llm_review: $("#r-llm-review").checked, provider: $("#r-provider").value || null, model: $("#r-model").value.trim() || null }, $("#r-progress"), r => {
  $("#r-out").innerHTML = html`<div class="small"><b>해결률 ${pct(r.resolved)}</b> · 깨진 파일을 고침 ${pct(r.found_file)} · 평균 ${r.mean_steps}걸음 · ${r.mean_tokens} 토큰 · 테스트를 고친 시도 ${r.touched_tests}
    · 리뷰 지적 ${r.review_flags} · ${r.model} · ${r.seconds}초 · run #${r.run_id}</div>${html.join(r.rows.map(rowHtml), "")}`;
}).catch(err => ui.error($("#r-out"), err));

load().catch(e => ui.error($("#t-out"), e));
