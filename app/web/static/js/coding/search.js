// coding/search.html 화면 스크립트 — 함수 단위 코드 검색(BM25 · 기호 · 호출 그래프)과 깬 코드 과제로 잰 hit@k(CD1)
const METHOD = { bm25: "BM25 만", symbol: "BM25 + 기호", graph: "BM25 + 기호 + 호출 그래프" };
const pct = v => (v == null ? "-" : `${(v * 100).toFixed(1)}%`);

$("#s-run").onclick = e => busy(e.target, () => api("/api/coding/search", { method: "POST", body: { query: $("#s-q").value, method: $("#s-method").value, k: 10 } }))
  .then(r => { $("#s-out").innerHTML = html`<ol class="small">${html.join(r.results.map(x => html`<li><span class="mono">${x.file}:${x.start}</span> <b>${x.name}</b> <span class="muted">(${x.score})</span>${x.doc ? html`<div class="muted">${x.doc.slice(0, 140)}</div>` : ""}</li>`), "")}</ol>`; })
  .catch(err => ui.error($("#s-out"), err));

$("#e-run").onclick = e => busy(e.target, () => api("/api/coding/search/eval", { method: "POST", body: { tasks: $("#e-tasks").value, k: +$("#e-k").value || 5 } })).then(r => {
  $("#e-out").innerHTML = html`<div class="small muted">${r.tasks} · 과제 ${r.n} · run #${r.run_id}</div><div class="table-wrap"><table><tr><th>방법</th><th>hit@${r.k}</th><th>MRR</th></tr>
    ${html.join(Object.entries(r.methods).map(([m, d]) => html`<tr><td>${METHOD[m]}</td><td><b>${pct(d.hit)}</b></td><td>${d.mrr}</td></tr>`), "")}</table></div>`;
}).catch(err => ui.error($("#e-out"), err));

(async () => {
  const o = await api("/api/coding/overview");
  $("#s-info").textContent = `복사본의 함수 · 클래스 ${o.functions}개`;
  $$("[data-tasks]").forEach(s => { s.innerHTML = html`${o.tasks.map(t => html`<option>${t.name}</option>`)}`; });
  if (!o.tasks.length) ui.empty($("#e-out"), "깬 코드 과제가 없습니다 — 코딩 에이전트 화면에서 만드세요.");
})().catch(e => ui.error($("#s-out"), e));
