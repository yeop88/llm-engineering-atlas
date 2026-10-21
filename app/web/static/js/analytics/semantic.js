// analytics/semantic.html 화면 스크립트 — 의미 계층 정의(DA2), 위험 질의 시험(DA6)
$("#g-run").onclick = e => busy(e.target, () => api("/api/analytics/guard/test", { method: "POST", body: { source: $("#g-source").value } })).then(r => {
  $("#g-out").innerHTML = html`<div class="small"><b>${r.passed}/${r.n}</b> 기대대로</div><div class="table-wrap"><table><tr><th>시험</th><th>SQL</th><th>기대</th><th>결과</th><th>이유</th></tr>
    ${html.join(r.cases.map(c => html`<tr><td>${c.name}</td><td class="small mono">${c.sql}</td><td>${c.must_block ? "막힘" : "통과"}</td>
      <td><span class="badge ${c.ok ? "ok" : "err"}">${c.got === "ran" ? "실행됨" : c.got === "blocked" ? "막힘" : "오류"}</span></td><td class="small">${c.why}</td></tr>`), "")}</table></div>`;
}).catch(err => ui.error($("#g-out"), err));

(async () => {
  const [sem, src] = await Promise.all([api("/api/analytics/semantic"), api("/api/analytics/sources")]);
  $("#s-defs").innerHTML = html`<div class="table-wrap"><table><tr><th>지표</th><th>뜻</th><th>SQL 식</th></tr>
    ${html.join(Object.entries(sem.metrics).map(([k, m]) => html`<tr><td><b>${k}</b></td><td>${m.desc}</td><td class="mono small">${m.sql}</td></tr>`), "")}</table></div>
    <div>차원: ${html.join(Object.entries(sem.dimensions).map(([k, v]) => html`<span class="badge" title="${v}">${k}</span>`), " ")}</div>
    <div>필터: ${html.join(Object.keys(sem.filters).map(k => html`<span class="badge">${k}</span>`), " ")}</div>
    <div class="muted">기본 표: <span class="mono">${sem.base}</span></div>`;
  const demo = src.sources.filter(s => !s.name.startsWith("app"));
  $("#g-source").innerHTML = html`${demo.map(s => html`<option>${s.name}</option>`)}`;
  if (!demo.length) ui.empty($("#g-out"), "예시 자료가 없습니다 — 자연어로 데이터 묻기 화면에서 만드세요.");
})().catch(e => ui.error($("#s-defs"), e));
