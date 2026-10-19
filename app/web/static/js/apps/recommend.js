// apps/recommend.html 화면 스크립트 (템플릿에서 옮김 — 화면 JS 는 static/js/<영역>/<화면>.js)
const votes = {};  // key -> 1 | -1
let picker, model;
const updateTaste = () => {
  const v = Object.values(votes);
  $("#taste").textContent = `👍 ${v.filter(x => x > 0).length} · 👎 ${v.filter(x => x < 0).length}`;
};
$("#diversity").addEventListener("input", e => ($("#div-v").textContent = e.target.value));
$("#div-v").textContent = $("#diversity").value;

$("#load").onclick = async e => {
  const r = await busy(e.target, () => api("/api/apps/items", { method: "POST", body: { source: picker.get(), limit: 500 } }));
  Object.keys(votes).forEach(k => delete votes[k]); updateTaste();
  $("#items").innerHTML = r.items.map(it => `<div class="row" style="flex-wrap:nowrap;align-items:flex-start" data-key="${esc(it.key)}">
      <button class="btn sm" data-vote="1" title="좋아요">👍</button><button class="btn sm" data-vote="-1" title="싫어요">👎</button>
      <div class="small">${it.label ? `<span class="badge muted">${esc(it.label)}</span> ` : ""}${it.filename ? `<b>${esc(it.filename)}</b> ` : ""}${esc(it.text)}</div></div>`).join("")
    + (r.n > r.items.length ? `<div class="small muted">처음 ${r.items.length}개만 표시 (전체 ${r.n}개가 추천 대상)</div>` : "");
};
$("#items").addEventListener("click", e => {
  const b = e.target.closest("[data-vote]"); if (!b) return;
  const row = b.closest("[data-key]"); const k = row.dataset.key; const v = +b.dataset.vote;
  votes[k] = votes[k] === v ? 0 : v;
  row.querySelectorAll("[data-vote]").forEach(x => x.classList.toggle("primary", votes[k] === +x.dataset.vote));
  updateTaste();
});
$("#run").onclick = async e => {
  const body = { ...model(), source: picker.get(), liked: Object.keys(votes).filter(k => votes[k] > 0), disliked: Object.keys(votes).filter(k => votes[k] < 0),
                 interest: $("#interest").value, top_k: +$("#topk").value, diversity: +$("#diversity").value };
  const r = await Apps.run(e.target, $("#progress"), "/api/apps/recommend", body);
  if (!r) return;
  $("#out").hidden = false;
  $("#out").innerHTML = `<div class="row between"><h2>추천 결과</h2><span class="small muted">대상 ${r.n_items}개 · 평균 관련도 ${r.coverage} · 추천끼리 평균 유사도 ${r.intra_similarity} (낮을수록 다양) · ${r.seconds}s</span></div>
    ${r.results.map(x => `<div class="rank-item"><div class="row between small"><span><span class="badge ${x.rank === 1 ? "ok" : "muted"}">#${x.rank}</span> ${x.label ? `<span class="badge muted">${esc(x.label)}</span>` : ""} ${x.filename ? `<b>${esc(x.filename)}</b>` : ""}</span><b class="mono">${x.score.toFixed(3)}</b></div>
      <div class="small">${esc(x.text)}</div>
      ${x.because ? `<div class="small muted">추천 이유: 👍 한 "${esc(x.because.text)}" 와 유사도 ${x.because.similarity}</div>` : ""}</div>`).join("")}`;
};
(async () => {
  picker = await Apps.sourcePicker($("#src"), { app: "recommend", labels: "optional" });
  model = await Apps.modelPicker($("#model"), $("#dim"));
})();
