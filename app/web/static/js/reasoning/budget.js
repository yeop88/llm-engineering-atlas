// reasoning/budget.html 화면 스크립트 — 생각 예산 곡선 · 꺾이는 점(RS1), 생각 라우터 채점(RS2)
const TYPE = { article_title: "조문 제목", article_number: "조문 번호", citation_count: "인용 수", calc: "계산" };
const pct = v => (v == null ? "-" : `${(v * 100).toFixed(1)}%`);
const base = () => ({ tasks: $("#b-tasks").value, max_per_type: +$("#b-n").value || 10, provider: $("#b-provider").value || null, model: $("#b-model").value.trim() || null });

function renderBudget(r) {
  const budgets = r.rows.map(x => x.budget);
  $("#b-out").innerHTML = html`<div class="small muted">${r.model} · 과제 ${r.n_tasks} · ${r.seconds}초 · run #${r.run_id} · 꺾이는 점 <b>${r.knee ?? "-"}</b></div>
    <div class="table-wrap"><table><tr><th>예산</th><th>정답률</th><th>생각 토큰</th><th>출력 토큰</th><th>시간(초)</th><th>예산 강제</th></tr>
    ${html.join(r.rows.map(x => html`<tr${x.budget === r.knee ? html` class="selected"` : ""}><td>${x.budget || "끔"}</td><td><b>${pct(x.acc)}</b></td><td>${x.think_tokens}</td><td>${x.out_tokens}</td><td>${x.seconds}</td><td>${pct(x.forced)}</td></tr>`), "")}</table></div>
    <h3>유형별 정답률</h3><div class="table-wrap"><table><tr><th>유형</th>${html.join(budgets.map(b => html`<th>${b || "끔"}</th>`), "")}<th>꺾이는 점</th></tr>
    ${html.join(Object.entries(r.by_type).map(([ty, d]) => html`<tr><td>${TYPE[ty] || ty}</td>${html.join(budgets.map(b => html`<td>${pct(d.acc[b])}</td>`), "")}<td><b>${d.knee ?? "-"}</b></td></tr>`), "")}</table></div>`;
}

$("#b-run").onclick = e => runJobInto(e.target, "/api/reasoning/budget", { ...base(), budgets: $("#b-budgets").value.split(",").map(s => +s.trim()).filter(n => !Number.isNaN(n)) },
  $("#b-progress"), renderBudget).catch(err => ui.error($("#b-out"), err));

$("#r-run").onclick = e => runJobInto(e.target, "/api/reasoning/route", { ...base(), budget: +$("#r-budget").value || 1024, router: $("#r-router").value }, $("#r-progress"), r => {
  $("#r-out").innerHTML = r.n ? html`<div class="small muted">${r.model} · 예산 ${r.budget} · ${r.router === "rule" ? "규칙" : "LLM"} 라우터 · 과제 ${r.n} · run #${r.run_id}</div>
    <div class="table-wrap"><table><tr><th>정책</th><th>정답률</th><th>평균 토큰</th><th>평균 시간(초)</th><th>켠 비율</th></tr>
    ${html.join(r.policies.map(p => html`<tr><td>${p.policy}</td><td><b>${pct(p.acc)}</b></td><td>${p.tokens}</td><td>${p.seconds}</td><td>${pct(p.on_rate)}</td></tr>`), "")}</table></div>
    <h3>유형별</h3><div class="table-wrap"><table><tr><th>유형</th><th>과제</th><th>라우터가 켬</th><th>끔 정답률</th><th>켬 정답률</th></tr>
    ${html.join(Object.entries(r.by_type).map(([ty, d]) => html`<tr><td>${TYPE[ty] || ty}</td><td>${d.n}</td><td>${pct(d.on_rate)}</td><td>${pct(d.off)}</td><td>${pct(d.on)}</td></tr>`), "")}</table></div>` : html`<p class="small muted">채점할 풀이가 없습니다.</p>`;
}).catch(err => ui.error($("#r-out"), err));

(async () => {
  const o = await api("/api/reasoning/overview");
  $$("[data-tasks]").forEach(s => { s.innerHTML = html`${o.tasks.map(t => html`<option>${t.name}</option>`)}`; });
  if (!o.tasks.length) ui.empty($("#b-out"), "과제가 없습니다 — RLVR 과제 화면(/rlvr/tasks)에서 먼저 만드세요.");
})().catch(e => ui.error($("#b-out"), e));
