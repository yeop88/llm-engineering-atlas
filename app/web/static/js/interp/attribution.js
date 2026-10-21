// interp/attribution.html 화면 스크립트 — 근거 지우기 기여 · 어텐션 vs 인용 · 정답 근거(IP2)
const pct = v => (v == null ? "-" : `${(v * 100).toFixed(1)}%`);

$("#a-run").onclick = e => runJobInto(e.target, "/api/interp/attribution", { eval_set_id: +$("#a-set").value, max_queries: +$("#a-n").value || 12, k: +$("#a-k").value || 4 },
  $("#a-progress"), r => {
    $("#a-out").innerHTML = html`<div class="small muted">${r.eval_set} · ${r.model} · 질문 ${r.n} · ${r.seconds}초 · run #${r.run_id}</div>
      <div class="table-wrap"><table><tr><th>비교</th><th>일치율</th></tr>
      <tr><td>지우기 기여 1위 = 정답 근거</td><td><b>${pct(r.drop_is_gold)}</b></td></tr>
      <tr><td>어텐션 1위 = 정답 근거</td><td>${pct(r.attention_is_gold)}</td></tr>
      <tr><td>어텐션 1위 = 지우기 기여 1위</td><td>${pct(r.attention_agrees_drop)}</td></tr>
      <tr><td>답이 인용한 근거 = 정답 근거 (인용한 답 ${r.n_cited})</td><td>${pct(r.cited_is_gold)}</td></tr>
      <tr><td>지우기 기여 1위가 인용한 근거 안</td><td>${pct(r.drop_is_cited)}</td></tr></table></div>
      ${html.join(r.rows.slice(0, 15).map(x => html`<details class="small"><summary>${x.query} — 기여 1위 [${x.top_drop}] · 정답 [${x.gold}] · 인용 ${x.cited.length ? x.cited.map(c => `[${c}]`).join("") : "없음"}</summary>
        <div class="pre">${x.answer}</div><table><tr><th>근거</th><th>지우면 로그확률 하락</th><th>어텐션</th></tr>
        ${html.join(x.drops.map((d, i) => html`<tr><td>[${i + 1}]${i + 1 === x.gold ? " 정답" : ""}</td><td>${d}</td><td>${x.attention[i] ?? "-"}</td></tr>`), "")}</table></details>`), "")}`;
  }).catch(err => ui.error($("#a-out"), err));

setupCollectionPickers({ col: $("#a-col"), set: $("#a-set") }).catch(e => ui.error($("#a-out"), e));
