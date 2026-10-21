// context/hygiene.html 화면 스크립트 — 틀린 이전 단계 결과를 넣었을 때 막는 방법별 오염률 · 정답률(CX6)
const pct = v => (v == null ? "-" : `${(v * 100).toFixed(1)}%`);

$("#h-run").onclick = e => runJobInto(e.target, "/api/context/hygiene", { eval_set_id: +$("#h-set").value, max_queries: +$("#h-n").value || 30,
  provider: $("#h-provider").value || null, model: $("#h-model").value.trim() || null }, $("#h-progress"), r => {
  const rs = r.results;
  const rows = Object.entries(rs).filter(([k]) => k !== "n_usable");
  $("#h-out").innerHTML = html`<div class="small muted">${r.eval_set} · ${r.model} · 질문 ${r.n} 중 근거에 수가 있는 ${rs.n_usable} · ${r.seconds}초 · run #${r.run_id}</div>
    ${rs.n_usable ? html`<div class="table-wrap"><table><tr><th>막는 방법</th><th>질문</th><th>오염률(틀린 수를 따름)</th><th>정답률</th></tr>
    ${html.join(rows.map(([, d]) => html`<tr><td>${d.label}</td><td>${d.n}</td><td><b>${pct(d.contaminated)}</b></td><td>${pct(d.quality)}</td></tr>`), "")}</table></div>`
    : html`<p class="small muted">근거 문장에 수가 있는 질문이 없습니다 — 다른 평가 세트를 고르세요.</p>`}`;
}).catch(err => ui.error($("#h-out"), err));

setupCollectionPickers({ col: $("#h-col"), set: $("#h-set") }).catch(e => ui.error($("#h-out"), e));
