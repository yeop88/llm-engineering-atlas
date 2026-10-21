// interp/space.html 화면 스크립트 — 임베딩 공간 지표(IP1), 희소 오토인코더 특징(IP4)
const pct = v => (v == null ? "-" : `${(v * 100).toFixed(1)}%`);

$("#s-run").onclick = e => runJobInto(e.target, "/api/interp/space", { collection_id: +$("#s-col").value, model_ids: selectedIds($("#s-models")), max_chunks: +$("#s-n").value || 600 },
  $("#s-progress"), r => {
    $("#s-out").innerHTML = html`<div class="small muted">청크 ${r.n_chunks} · ${r.seconds}초 · run #${r.run_id}</div><div class="table-wrap"><table>
      <tr><th>모델</th><th>차원</th><th>이방성(낮을수록 고름)</th><th>유효 차원</th><th>상위 10 · 50 주성분</th><th>문서 군집</th><th>한-영 검색@1</th><th>번역 쌍 − 아무 쌍</th></tr>
      ${html.join(r.models.map(m => html`<tr><td class="mono small">${m.model}</td><td>${m.dim}</td><td>${m.anisotropy}</td><td>${m.effective_dim}</td><td>${pct(m.pca_top10)} · ${pct(m.pca_top50)}</td>
        <td>${m.doc_separation ?? "-"}</td><td>${pct(m.cross_lingual["retrieval@1"])}</td><td>${m.cross_lingual.gap}</td></tr>`), "")}</table></div>`;
  }).catch(err => ui.error($("#s-out"), err));

$("#f-run").onclick = e => runJobInto(e.target, "/api/interp/sae", { collection_id: +$("#s-col").value, layer: +$("#f-layer").value || 14, max_texts: +$("#f-texts").value || 200,
  mult: +$("#f-mult").value || 4, l1: +$("#f-l1").value || 0.001, steps: +$("#f-steps").value || 400 }, $("#f-progress"), r => {
  $("#f-out").innerHTML = html`<div class="small">층 ${r.layer} · 토큰 ${r.n_tokens} · 특징 ${r.n_features} · 설명한 분산 <b>${pct(r.explained)}</b> · 평균 켜진 특징 ${r.l0} · 안 켜진 특징 ${pct(r.dead)} · ${r.seconds}초 · run #${r.run_id}</div>
    <div class="table-wrap"><table><tr><th>특징</th><th>켜지는 비율</th><th>최대</th><th>가장 세게 켜진 글 조각</th></tr>
    ${html.join(r.features.map(f => html`<tr><td>#${f.feature}</td><td>${pct(f.freq)}</td><td>${f.max}</td><td class="small mono">${html.join(f.examples.map(x => html`<div>${x}</div>`), "")}</td></tr>`), "")}</table></div>`;
}).catch(err => ui.error($("#f-out"), err));

(async () => {
  await setupCollectionPickers({ col: $("#s-col") });
  await fillModelSelect($("#s-models"));
  $("#f-model").textContent = `모델: ${(await api("/api/interp/overview")).model} (POSTTRAIN_BASE_MODEL, 처음 쓸 때 내려받음)`;
})().catch(e => ui.error($("#s-out"), e));
