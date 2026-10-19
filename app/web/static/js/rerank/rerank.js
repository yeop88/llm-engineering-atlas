// rerank/rerank.html 화면 스크립트 (템플릿에서 옮김 — 화면 JS 는 static/js/<영역>/<화면>.js)
setupCollectionPickers({ col: $("#r-col"), idx: $("#r-idx"), cs: $("#r-cs"), set: $("#r-set"), key: "rerank-col" });
$("#r-mode").addEventListener("change", () => { const b = $("#r-mode").value === "bm25"; $("#r-idx-wrap").hidden = b; $("#r-cs-wrap").hidden = !b; });
(async () => {
  const rr = (await getModels()).filter(m => m.kind === "reranker" && m.cached);
  $("#r-rr").innerHTML = rr.map(r => `<option value="${r.id}">${esc(r.name)}</option>`).join("") || '<option value="" disabled>받아 둔 리랭커가 없습니다 (1 임베딩 → 모델)</option>';
  if (rr.length) $("#r-rr").options[0].selected = true;
})();

$("#r-run").onclick = e => {
  const bm25 = $("#r-mode").value === "bm25";
  const body = {
    eval_set_id: +$("#r-set").value,
    config: { mode: $("#r-mode").value, index_id: bm25 ? null : +$("#r-idx").value || null, chunk_set_id: bm25 ? +$("#r-cs").value || null : null, candidates: 50 },
    reranker_ids: selectedIds($("#r-rr")), ks: $("#r-ks").value.split(",").map(x => +x.trim()).filter(x => x > 0),
    llm: $("#r-llm").checked ? { top: +$("#r-llm-top").value || 10, model: $("#r-llm-model").value.trim() || null } : null,
    max_queries: +$("#r-n").value || null,
  };
  if (!body.eval_set_id) return toast("평가 세트가 필요합니다", "err");
  runJobInto(e.target, "/api/rerank/evaluate", body, $("#r-progress"), render);
};

function render(r) {
  const rows = r.rows;
  $("#r-out").innerHTML = `<div class="row between"><h3>결과 · ${esc(r.eval_set?.name || "")}</h3><span class="small muted">질문 ${r.n_queries}개${r.seconds != null ? ` · ${r.seconds}s` : ""}${r.run_id ? ` · run #${r.run_id}` : ""}</span></div>
    <div class="table-wrap"><table><tr><th>리랭커</th><th class="num">후보 수</th><th>융합</th><th class="num">nDCG@10 (95% 구간)</th><th>리랭킹 없음 대비</th><th class="num">질문당 지연</th></tr>
    ${rows.map(x => `<tr><td class="small"><b>${esc(x.label.split(" · ")[0])}</b></td><td class="num">${x.k || "-"}</td><td class="small">${x.fusion ? "1단계와 RRF" : x.reranker ? "그대로" : "-"}</td>
      <td class="num">${pct(x["ndcg@10"])} <span class="small muted">(${pct(x.ci[0])}–${pct(x.ci[1])})</span></td><td class="small nowrap">${vsBadge(x.vs_none)}</td>
      <td class="num small nowrap">${(x.latency_ms.mean / 1000).toFixed(1)}s</td></tr>`).join("")}</table></div>
    <div class="small muted">지연 = 1단계 검색 + 쌍당 재정렬 시간 × 후보 수 (모델 로드 제외${Object.keys(r.load_seconds || {}).length ? ": " + Object.entries(r.load_seconds).map(([k, v]) => `${esc(k)} ${v}s`).join(", ") : ""}). '융합'은 리랭커 순위와 1단계 순위를 RRF 로 합친 것 — 리랭커가 1단계의 정답을 끌어내리는 실수를 줄입니다.</div>`;
}
