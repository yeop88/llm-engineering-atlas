// compress/eval.html 화면 스크립트 — 방법 × 압축률별 정답률 · 남은 글자 · 숫자 · 조항 보존 · 시간(KC6)
const pct = v => (v == null ? "-" : `${(v * 100).toFixed(1)}%`);

$("#e-run").onclick = e => runJobInto(e.target, "/api/compress/eval", { eval_set_id: +$("#e-set").value, max_queries: +$("#e-n").value || 15,
  ratios: $("#e-ratios").value.split(",").map(s => +s.trim()).filter(n => n > 0 && n <= 1), provider: $("#e-provider").value || null, model: $("#e-model").value.trim() || null },
  $("#e-progress"), r => {
    $("#e-out").innerHTML = html`<div class="small muted">${r.eval_set} · 답 ${r.model} · 압축 ${r.compressor} · ${r.seconds}초 · run #${r.run_id}</div>
      <div class="table-wrap"><table><tr><th>방법</th><th>남길 비율</th><th>정답률</th><th>실제 남은 글자</th><th>숫자 · 조항 보존</th><th>압축(초)</th><th>답(초)</th></tr>
      ${html.join(r.results.map(x => html`<tr><td>${x.label}</td><td>${x.ratio}</td><td><b>${pct(x.quality)}</b></td><td>${pct(x.char_ratio)}</td><td>${pct(x.preserved)}</td><td>${x.compress_seconds}</td><td>${x.answer_seconds}</td></tr>`), "")}</table></div>`;
  }).catch(err => ui.error($("#e-out"), err));

setupCollectionPickers({ col: $("#e-col"), set: $("#e-set") }).catch(e => ui.error($("#e-out"), e));
