// memory/eval.html 화면 스크립트 — 여러 세션 대화로 전체 기록 · 메모리 · 없음의 유형별 정답률 · 맥락 글자(ME7)
const METHOD = { full: "전체 기록", memory: "메모리", none: "없음(기준선)" };
const pct = v => (v == null ? "-" : `${(v * 100).toFixed(1)}%`);

$("#e-run").onclick = e => runJobInto(e.target, "/api/memory/eval", { personas: +$("#e-n").value || 4, extractor: $("#e-ext").value, k: +$("#e-k").value || 6,
  provider: $("#e-provider").value || null, model: $("#e-model").value.trim() || null }, $("#e-progress"), r => {
  const ms = Object.keys(r.summary), types = [...new Set(ms.flatMap(m => Object.keys(r.summary[m].by_type)))];
  $("#e-out").innerHTML = html`<div class="small muted">${r.model} · 고객 ${r.personas} · 추출 ${r.extractor} · ${r.seconds}초 · run #${r.run_id}</div>
    <div class="table-wrap"><table><tr><th>방식</th><th>정답률</th>${html.join(types.map(t => html`<th>${t}</th>`), "")}<th>맥락 글자</th></tr>
    ${html.join(ms.map(m => html`<tr><td>${METHOD[m]}</td><td><b>${pct(r.summary[m].acc)}</b></td>${html.join(types.map(t => html`<td>${pct(r.summary[m].by_type[t])}</td>`), "")}<td>${r.summary[m].context_chars}</td></tr>`), "")}</table></div>
    <details class="small"><summary>답 보기</summary><div class="table-wrap"><table><tr><th>유형</th><th>방식</th><th>질문</th><th>답</th><th></th></tr>
    ${html.join(r.rows.map(x => html`<tr><td>${x.type}</td><td>${METHOD[x.method]}</td><td>${x.q}</td><td>${x.answer}</td><td><span class="badge ${x.correct ? "ok" : "err"}">${x.correct ? "맞음" : "틀림"}</span></td></tr>`), "")}</table></div></details>`;
}).catch(err => ui.error($("#e-out"), err));
