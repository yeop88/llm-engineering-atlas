// interp/inside.html 화면 스크립트 — 층별 탐침(IP3) · 내부 신호 vs 밖의 검증 환각 탐지 AUROC(IP6) · 방향 조종(IP5)
const pct = v => (v == null ? "-" : `${(v * 100).toFixed(1)}%`);
const nums = s => s.split(",").map(x => +x.trim()).filter(n => !Number.isNaN(n));

$("#i-run").onclick = e => runJobInto(e.target, "/api/interp/inside", { eval_set_id: +$("#i-set").value, max_queries: +$("#i-n").value || 20, layers: nums($("#i-layers").value),
  name: $("#i-name").value.trim() }, $("#i-progress"), r => {
  const h = r.hallucination;
  $("#i-out").innerHTML = html`<div class="small muted">${r.eval_set} · ${r.model}(층 ${r.n_layers}) · 질문 ${r.n_pairs} × 2 · ${r.seconds}초 · run #${r.run_id} · 저장 ${r.saved}</div>
    <h3>층별 탐침 정확도 — 근거 있음 / 뺌</h3><div class="table-wrap"><table><tr><th>층</th><th>정확도</th><th></th></tr>
    ${html.join(Object.entries(r.probe.by_layer).map(([l, a]) => html`<tr${+l === r.probe.best_layer ? html` class="selected"` : ""}><td>${l}</td><td>${pct(a)}</td><td><progress value="${a ?? 0}" max="1"></progress></td></tr>`), "")}</table></div>
    <div class="small">거절률: 근거 뺌 ${pct(r.refusal.without_refused)} · 근거 있음 ${pct(r.refusal.with_refused)}</div>
    <h3>환각 가려내기 (거절하지 않은 답 ${h.n}, 그중 근거 없이 답함 ${h.n_hallucinated ?? "-"})</h3>
    ${Object.keys(h.auroc || {}).length ? html`<div class="table-wrap"><table><tr><th>신호</th><th>AUROC</th></tr>${html.join(Object.entries(h.auroc).map(([k, v]) => html`<tr><td>${k}</td><td><b>${v}</b></td></tr>`), "")}</table></div>` : html`<p class="small muted">${h.note}</p>`}
    <details class="small"><summary>답 예시</summary>${html.join(r.examples.map(x => html`<div><b>${x.kind === "with" ? "근거 있음" : "근거 뺌"}</b> ${x.refused ? "(거절)" : ""} ${x.query}<div class="pre muted">${x.answer}</div></div>`), "")}</details>`;
  loadSaved();
}).catch(err => ui.error($("#i-out"), err));

$("#t-run").onclick = e => runJobInto(e.target, "/api/interp/steer", { name: $("#t-name").value, layer: +$("#t-layer").value || null, alphas: nums($("#t-alphas").value), max_queries: +$("#t-n").value || 10 },
  $("#t-progress"), r => {
    $("#t-out").innerHTML = html`<div class="small muted">${r.name} · 층 ${r.layer} · 질문 ${r.n_pairs} × 2 · ${r.seconds}초 · run #${r.run_id}</div>
      <div class="table-wrap"><table><tr><th>세기</th><th>근거 뺌 거절률(오르면 좋음)</th><th>근거 있음 거절률(오르면 부작용)</th><th>근거 있음 답의 근거율</th></tr>
      ${html.join(r.results.map(x => html`<tr><td>${x.alpha}</td><td><b>${pct(x.without_refused)}</b></td><td>${pct(x.with_refused)}</td><td>${pct(x.mean_supported)}</td></tr>`), "")}</table></div>`;
  }).catch(err => ui.error($("#t-out"), err));

async function loadSaved() {
  const o = await api("/api/interp/overview");
  $("#t-name").innerHTML = html`${o.saved.map(n => html`<option>${n}</option>`)}`;
  if (!o.saved.length) ui.empty($("#t-out"), "저장한 내부 신호가 없습니다 — 위에서 먼저 재세요.");
}

(async () => {
  await setupCollectionPickers({ col: $("#i-col"), set: $("#i-set") });
  await loadSaved();
})().catch(e => ui.error($("#i-out"), e));
