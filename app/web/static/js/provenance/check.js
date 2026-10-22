// provenance/check.html 화면 스크립트 — 부딪히는 답(PV8) · 주장 단위 근거 평가
const pct = v => (v == null ? "-" : `${Math.round(v * 100)}%`);

$("#x-run").onclick = e => busy(e.target, () => api(`/api/provenance/contradictions?days=${+$("#x-days").value || 30}`)).then(r => {
  $("#x-out").innerHTML = r.contradictions.length ? html`<div class="small muted">답 ${r.checked}개 확인 · 부딪힘 후보 ${r.contradictions.length}개</div>
    <div class="table-wrap"><table><tr><th>질문</th><th>답 A</th><th>A 에만</th><th>답 B</th><th>B 에만</th></tr>
    ${html.join(r.contradictions.map(c => html`<tr><td class="small">${c.question}</td><td>#${c.a} <span class="small muted">${c.a_at}</span></td><td class="mono small">${c.only_a.join(" ")}</td>
      <td>#${c.b} <span class="small muted">${c.b_at}</span></td><td class="mono small">${c.only_b.join(" ")}</td></tr>`), "")}</table></div>`
    : html`<div class="small muted">답 ${r.checked}개에서 부딪힘을 찾지 못했습니다.</div>`;
}).catch(err => ui.error($("#x-out"), err));

$("#e-run").onclick = e => runJobInto(e.target, "/api/provenance/eval", { eval_set_id: +$("#e-set").value, max_queries: +$("#e-n").value,
  provider: $("#e-provider").value || null, model: $("#e-model").value.trim() || null }, $("#e-progress"), r => {
  const s = r.summary;
  $("#e-out").innerHTML = html`<div class="small muted">${r.eval_set} · ${r.model} · 질문 ${r.n} · ${r.seconds}초 · run #${r.run_id}</div>
    <div class="table-wrap"><table><tr><th>주장 수(평균)</th><th>근거 강함</th><th>약함</th><th>없음</th><th>인용 안 함</th><th>빠진 표시</th><th>인용 정확도</th><th>원본까지 추적</th><th>옛 판 근거</th><th>정답 근거 인용</th></tr>
      <tr><td>${s.n_claims}</td><td><b>${pct(s.strong)}</b></td><td>${pct(s.weak)}</td><td>${pct(s.none)}</td><td>${pct(s.uncited)}</td><td>${s.marks_missing}</td><td>${pct(s.cite_precision)}</td>
      <td><b>${pct(s.traceable)}</b></td><td>${s.stale_sources}</td><td>${pct(s.gold_cited)}</td></tr></table></div>
    <div class="table-wrap"><table><tr><th>질문</th><th>주장</th><th>강함</th><th>추적</th><th>빠진 표시</th><th>정답 근거</th><th>기록</th></tr>
    ${html.join(r.rows.map(x => html`<tr><td class="small">${x.query}</td><td>${x.n_claims}</td><td>${pct(x.strong)}</td><td>${pct(x.traceable)}</td><td>${x.marks_missing}</td>
      <td>${x.gold_cited ? "✓" : "✗"}</td><td><a href="/provenance/trace?trace=${x.trace_id}">#${x.trace_id}</a></td></tr>`), "")}</table></div>`;
}).catch(err => ui.error($("#e-out"), err));

setupCollectionPickers({ col: $("#e-col"), set: $("#e-set") }).catch(e => ui.error($("#e-out"), e));
