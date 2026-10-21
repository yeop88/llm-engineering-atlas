// analytics/eval.html 화면 스크립트 — 정답 SQL 결과와 비교한 실행 정확도 · 유형별 · 방식별(DA7)
const MODE = { sql: "SQL 생성(연결)", sql_full_schema: "SQL 생성(전체 스키마)", semantic: "의미 계층" };
const pct = v => (v == null ? "-" : `${(v * 100).toFixed(1)}%`);

$("#e-run").onclick = e => runJobInto(e.target, "/api/analytics/eval", { source: $("#e-source").value, modes: $$("[data-mode]").filter(c => c.checked).map(c => c.dataset.mode),
  max_tries: +$("#e-tries").value || 3, provider: $("#e-provider").value || null, model: $("#e-model").value.trim() || null }, $("#e-progress"), r => {
  const modes = Object.keys(r.modes), types = [...new Set(modes.flatMap(m => Object.keys(r.modes[m].by_type)))];
  $("#e-out").innerHTML = html`<div class="small muted">${r.source} · ${r.model} · 질문 ${r.n} · ${r.seconds}초 · run #${r.run_id}</div>
    <div class="table-wrap"><table><tr><th>방식</th><th>정답률</th>${html.join(types.map(t => html`<th>${t}</th>`), "")}<th>연결 재현율</th><th>평균 시도</th><th>고쳐서 맞힘</th></tr>
    ${html.join(modes.map(m => { const d = r.modes[m]; return html`<tr><td>${MODE[m]}</td><td><b>${pct(d.acc)}</b></td>${html.join(types.map(t => html`<td>${pct(d.by_type[t]?.acc)}</td>`), "")}
      <td>${pct(d.link_recall)}</td><td>${d.mean_tries}</td><td>${d.repaired}</td></tr>`; }), "")}</table></div>
    ${html.join(modes.map(m => html`<details><summary class="small">${MODE[m]} — 틀린 질문 ${r.modes[m].rows.filter(x => !x.correct).length}개</summary><ul class="small">
      ${html.join(r.modes[m].rows.filter(x => !x.correct).map(x => html`<li><b>${x.id}</b> ${x.q}<pre class="mono pre m-0">${x.sql || "(SQL 없음)"}</pre></li>`), "")}</ul></details>`), "")}`;
}).catch(err => ui.error($("#e-out"), err));

(async () => {
  const [src, qs] = await Promise.all([api("/api/analytics/sources"), api("/api/analytics/eval/questions")]);
  const demo = src.sources.filter(s => !s.name.startsWith("app"));
  $("#e-source").innerHTML = html`${demo.map(s => html`<option>${s.name}</option>`)}`;
  if (!demo.length) ui.empty($("#e-out"), "예시 자료가 없습니다 — 자연어로 데이터 묻기 화면에서 만드세요.");
  $("#e-qs").innerHTML = html`<ol>${html.join(qs.questions.map(q => html`<li><span class="badge">${q.type}</span> ${q.q} <pre class="mono pre m-0">${q.sql}</pre></li>`), "")}</ol>`;
})().catch(e => ui.error($("#e-out"), e));
