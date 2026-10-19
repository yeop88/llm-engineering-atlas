// distill/distill.html 화면 스크립트 (템플릿에서 옮김 — 화면 JS 는 static/js/<영역>/<화면>.js)
let dCol = null;
(async () => {
  const ms = await getModels();
  const emb = ms.filter(m => m.kind === "embedding" && m.cached && !(m.modalities || []).some(x => x !== "text"));
  const tch = ms.filter(m => m.cached && (m.kind === "reranker" || m.kind === "embedding"));
  $("#d-teacher").innerHTML = html.join(tch.map(m => html`<option value="${m.id}">${m.kind === "reranker" ? "[리랭커] " : ""}${m.name}</option>`), "");
  $("#d-student").innerHTML = html.join(emb.map(m => html`<option value="${m.id}">${m.name}</option>`), "");
  const kure = tch.find(m => /KURE/.test(m.hf_id)), small = emb.find(m => /granite-embedding-97m/.test(m.hf_id));
  if (kure) $("#d-teacher").value = kure.id;
  if (small) $("#d-student").value = small.id;
})();
setupCollectionPickers({ col: $("#d-col"), cs: $("#d-cs"), set: $("#d-set"), onDetail: d => (dCol = d) });
setupCollectionPickers({ col: $("#l-col"), cs: $("#l-cs"), idx: $("#l-idx") });

$("#d-run").onclick = async e => {
  const body = {
    teacher_model_id: +$("#d-teacher").value, base_model_id: +$("#d-student").value, collection_id: +$("#d-col").value, chunk_set_id: +$("#d-cs").value,
    eval_set_id: +$("#d-set").value || null, data_method: $("#d-method").value, n_passages: +$("#d-n").value || 100,
    epochs: +$("#d-ep").value || 1, batch_size: +$("#d-bs").value || 16, learning_rate: parseFloat($("#d-lr").value) || 2e-5,
  };
  const r = await busy(e.target, () => api("/api/distill", { method: "POST", body }));
  const box = $("#d-progress"); box.hidden = false;
  const done = await pollJob(r.job.id, j => { box.innerHTML = ui.jobProgress(j); }, 2000);
  box.innerHTML = done.status === "done" ? "" : html`<div class="errbox">${done.error || done.status}</div>`;
  box.hidden = done.status === "done";
  loadRuns();
};

async function loadRuns() {
  const runs = await api("/api/distill");
  $("#d-runs").innerHTML = runs.length ? html`<div class="table-wrap"><table><tr><th>#</th><th>교사 → 학생</th><th>상태</th><th class="num">nDCG@10 교사 / 학생 전 → 후</th><th>학습 후 vs 전</th><th>후 vs 교사</th><th class="num">격차 회복</th><th class="num">인코딩 (학생 / 교사)</th></tr>
    ${html.join(runs.map(r => { const c = r.metrics?.comparison || {}, m = c.models || {}, sp = c.texts_per_second || {};
      const v = k => (m[k] ? pct(m[k].metrics["ndcg@10"]) : "-");
      return html`<tr><td>${r.id}</td><td class="small">${r.name}</td><td><span class="badge ${r.status === "done" ? "ok" : r.status === "error" ? "err" : ""}">${r.status}</span>${r.error ? html`<div class="small muted">${r.error.slice(0, 120)}</div>` : ""}</td>
        <td class="num">${v("교사")} / ${v("학생 · 학습 전")} → <b>${v("학생 · 학습 후")}</b></td><td class="small nowrap">${c.after_vs_before ? vsBadge(c.after_vs_before) : "-"}</td>
        <td class="small nowrap">${c.after_vs_teacher ? vsBadge(c.after_vs_teacher) : "-"}</td><td class="num">${c.gap_closed != null ? pct(c.gap_closed) + "%" : "-"}</td>
        <td class="num small">${sp["학생 · 학습 후"] ?? "-"} / ${sp["교사"] ?? "-"} 개/s</td></tr>`; }), "")}</table></div>
    <div class="small muted">격차 회복 = (학습 후 − 학습 전) ÷ (교사 − 학습 전). 교사와 학생 차이가 1%p 미만이면 계산하지 않습니다.</div>` : html`<div class="empty">아직 증류 실행이 없습니다</div>`;
}
loadRuns();

$("#l-run").onclick = e => {
  const body = { collection_id: +$("#l-col").value, chunk_set_id: +$("#l-cs").value, config: { mode: "dense", index_id: +$("#l-idx").value },
    n_passages: +$("#l-n").value || 20, teacher_model: $("#l-teacher").value.trim() || null, min_support: parseFloat($("#l-min").value) || 0.8, name: $("#l-name").value.trim() };
  runJobInto(e.target, "/api/distill/llm-data", body, $("#l-progress"), r => {
    $("#l-out").innerHTML = html`<div class="small"><b>${r.file}</b> — 질문 ${r.asked}개 중 <b>${r.kept}개</b> 저장 · 버림: 거절 ${r.dropped.refused}, 근거율 낮음 ${r.dropped.low_support}, 잘못된 인용 ${r.dropped.invalid_citation}, 오류 ${r.dropped.error} · ${r.seconds}s</div>`;
    loadFiles();
  });
};
async function loadFiles() {
  const fs = await api("/api/distill/llm-data");
  $("#l-files").innerHTML = html.or(html.join(fs.map(f => html`<div class="small"><a href="/api/distill/llm-data/${encodeURIComponent(f.name)}">${f.name}</a> <span class="muted">${f.samples}개 · ${f.kb}KB</span></div>`), ""), html`<div class="empty">아직 없습니다</div>`);
}
loadFiles();
