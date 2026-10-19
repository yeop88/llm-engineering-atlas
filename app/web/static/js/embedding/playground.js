const lines = el => el.value.split("\n").map(s => s.trim()).filter(Boolean);
const dimVal = el => (el.value ? Number(el.value) : null);
const pre = new URLSearchParams(location.search).get("model");

async function init() {
  const preferred = pre ? [pre] : [];
  await fillModelSelect($("#r-models"), { preferred });
  await fillModelSelect($("#s-model"), { preferred });
  await fillModelSelect($("#e-model"), { preferred });
  [["#r-models", "#r-dim"], ["#s-model", "#s-dim"], ["#e-model", "#e-dim"]].forEach(([m, d]) => {
    fillDimSelect($(m), $(d));
    $(m).addEventListener("change", () => fillDimSelect($(m), $(d)));
  });
  initTabs();
}

// ── 검색 비교 ──
$("#r-run").onclick = async e => {
  const model_ids = selectedIds($("#r-models"));
  if (!model_ids.length) return toast("모델을 선택하세요", "err");
  const documents = lines($("#r-docs"));
  const body = { model_ids, query: $("#r-query").value, documents, top_k: Number($("#r-k").value), truncate_dim: dimVal($("#r-dim")) };
  $("#r-out").innerHTML = html`<div class="empty">모델 로드 및 인코딩 중… (처음 사용하는 모델은 다운로드가 필요합니다)</div>`;
  const r = await busy(e.target, () => api("/api/retrieve", { method: "POST", body }));
  // 모델 간 1위 문서 일치 여부 표시
  const top1 = r.results.filter(x => x.ranking).map(x => x.ranking[0].index);
  const agree = top1.length > 1 && top1.every(i => i === top1[0]);
  $("#r-out").innerHTML = r.results.map(res => html`
    <div class="card result-col grow">
      <h3 class="mono break-all">${res.hf_id}</h3>
      ${res.error ? html`<div class="errbox">${res.error}</div>` : html`
      <div class="small muted">${res.dim}차원 · ${res.seconds}s</div>
      <div class="small muted">Q: ${appliedInfo(res.applied.query)}<br>D: ${appliedInfo(res.applied.document)}</div>
      ${warningsHtml(res.warnings)}
      ${html.join(res.ranking.map((x, i) => html`<div class="rank-item">
        <div class="row between"><span class="badge ${i === 0 ? "ok" : "muted"}">#${i + 1} · doc ${x.index + 1}</span><b class="mono">${x.score.toFixed(4)}</b></div>
        <div class="bar" style="width:${Math.max(2, x.score * 100)}%; margin:4px 0"></div>
        <div class="small">${x.text}</div></div>`), "")}`}
    </div>`).join("") + (top1.length > 1 ? html`<div class="small muted" style="min-width:140px">${agree ? "✅ 모든 모델의 1위가 같습니다" : "⚠️ 모델별 1위가 다릅니다"}</div>` : "");
};

// ── 유사도 행렬 ──
$("#s-run").onclick = async e => {
  const texts = lines($("#s-texts"));
  const body = { model_id: Number($("#s-model").value), texts, role: $("#s-role").value, truncate_dim: dimVal($("#s-dim")) };
  const r = await busy(e.target, () => api("/api/similarity", { method: "POST", body }));
  const short = t => (t.length > 22 ? t.slice(0, 22) + "…" : t);
  $("#s-out").innerHTML = html`<div class="small muted mb-2">${r.hf_id} · ${r.dim}차원 · ${r.seconds}s · ${appliedInfo(r.applied)}</div>${warningsHtml(r.warnings)}
    <table class="heatmap"><tr><th></th>${html.join(r.texts.map((t, i) => html`<th title="${t}">${i + 1}</th>`), "")}</tr>
    ${html.join(r.matrix.map((row, i) => html`<tr><th title="${r.texts[i]}">${i + 1}. ${short(r.texts[i])}</th>${html.join(row.map((v, j) =>
      html`<td style="background:${heatColor(v)}" title="${r.texts[i]}\n↔ ${r.texts[j]}">${v.toFixed(3)}</td>`), "")}</tr>`), "")}</table>`;
};

// ── 임베딩 ──
$("#e-run").onclick = async e => {
  const body = { model_id: Number($("#e-model").value), texts: lines($("#e-texts")), role: $("#e-role").value, truncate_dim: dimVal($("#e-dim")), normalize: $("#e-norm").checked, preview: Number($("#e-preview").value) };
  const r = await busy(e.target, () => api("/api/embed", { method: "POST", body }));
  $("#e-out").innerHTML = html`<div class="row small muted mb-2"><span>${r.hf_id}</span><span>· ${r.dim}차원</span><span>· ${r.seconds}s</span><span>· ${r.texts_per_second ?? "-"} texts/s</span></div>
    <div class="small mb-2">적용: ${appliedInfo(r.applied)}${r.applied.prompt_text ? html` → <code>${r.applied.prompt_text}</code>` : ""}</div>${warningsHtml(r.warnings)}
    <table><tr><th>텍스트</th><th class="num">norm</th><th class="num">mean</th><th class="num">std</th><th>앞부분 값</th></tr>
    ${html.join(r.items.map(it => html`<tr><td>${it.text}</td><td class="num">${it.norm}</td><td class="num">${it.stats.mean}</td><td class="num">${it.stats.std}</td>
      <td><code class="small">[${html.join(it.preview, ", ")}${it.preview.length < r.dim ? ", …" : ""}]</code></td></tr>`), "")}</table>`;
};

// ── 임베딩 지도 ──
// "그룹: 문장" 형식 파싱 (그룹 이름은 공백 없는 20자 이하일 때만 인정 → 문장 속 콜론과 구분)
function parseItems(raw) {
  return raw.split("\n").map(s => s.trim()).filter(Boolean).map(line => {
    const m = /^([^\s:：]{1,20})\s*[:：]\s*(.+)$/.exec(line);
    return m ? { group: m[1], text: m[2] } : { group: "", text: line };
  });
}
function updateCount() {
  const items = parseItems($("#p-texts").value);
  const groups = [...new Set(items.map(i => i.group || "기본"))];
  $("#p-count").textContent = `${items.length}개 문장 · 그룹 ${groups.length}개${groups.length > 3 ? " (4번째 그룹부터는 회색 + 모양으로 구분)" : ""}`;
}
$("#p-texts").addEventListener("input", updateCount);

let lastMap = null;
$("#p-run").onclick = async e => {
  const model_ids = selectedIds($("#p-models"));
  if (!model_ids.length) return toast("모델을 선택하세요", "err");
  if (model_ids.length > 3) return toast("임베딩 지도는 최대 3개 모델까지 비교합니다", "err");
  if (typeof Chart === "undefined") return toast("차트 라이브러리(Chart.js CDN)를 불러오지 못했습니다", "err");
  const body = { model_ids, items: parseItems($("#p-texts").value), method: $("#p-method").value, role: $("#p-role").value, pair_groups: $("#p-pair").checked };
  $("#p-out").innerHTML = html`<div class="empty">모델 로드 및 인코딩 중…</div>`;
  lastMap = await busy(e.target, () => api("/api/projection", { method: "POST", body }));
  BenchCharts.renderProjection($("#p-out"), lastMap, { showLabels: $("#p-labels").checked });
};
$("#p-labels").addEventListener("change", () => {
  if (lastMap) BenchCharts.renderProjection($("#p-out"), lastMap, { showLabels: $("#p-labels").checked });
});

init().then(async () => {
  await fillModelSelect($("#p-models"), { preferred: pre ? [pre] : [] });
  updateCount();
});
