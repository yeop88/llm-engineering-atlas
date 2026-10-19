// multimodal/multimodal.html 화면 스크립트 (템플릿에서 옮김 — 화면 JS 는 static/js/<영역>/<화면>.js)
const urls = {};
// ── 컬렉션 갤러리 검색: RAG 검색 API 를 그대로 쓰고 결과를 썸네일 격자로 보여 준다 ──
async function gLoad() {
  const cols = await api("/api/collections");
  $("#g-col").innerHTML = cols.map(c => `<option value="${c.id}">${esc(c.name)}</option>`).join("") || '<option value="">컬렉션 없음</option>';
  applyCtx($("#g-col"));
  await gIdx();
}
async function gIdx() {
  if (!$("#g-col").value) return;
  const d = await api(`/api/collections/${$("#g-col").value}`);
  // 이미지 · 프레임이 든 청크 세트의 인덱스만 고르게 한다 — 글만 있는 인덱스는 이 화면에서 의미가 없다
  const media = new Set(d.chunk_sets.filter(c => c.stats?.n_media).map(c => c.id));
  const idx = d.indexes.filter(i => i.status === "ready" && media.has(i.chunk_set_id));
  $("#g-idx").innerHTML = idx.map(i => `<option value="${i.id}">${esc(i.model_hf_id.split("/").pop())} · #${i.id}</option>`).join("") || '<option value="">이미지 · 영상 인덱스 없음</option>';
  applyCtx($("#g-idx"));
}
$("#g-col").addEventListener("change", () => { gIdx(); });
$("#g-run").onclick = async e => {
  const q = $("#g-q").value.trim();
  if (!q || !$("#g-idx").value) return toast("인덱스와 검색어가 필요합니다", "err");
  const r = await busy(e.target, () => api(`/api/collections/${$("#g-col").value}/search`, { method: "POST", body: { query: q, configs: [{ mode: "dense", index_id: +$("#g-idx").value, top_k: +$("#g-k").value || 12 }] } }));
  const res = r.results[0];
  if (res.error) { $("#g-out").innerHTML = `<div class="errbox">${esc(res.error)}</div>`; return; }
  $("#g-out").innerHTML = res.results.map(x => x.media
    ? `<figure><a href="${x.media.source_url}${x.media.t != null ? `#t=${x.media.t}` : ""}" target="_blank" rel="noopener"><img src="${x.media.url}" alt="${esc(x.text)}" loading="lazy"></a><figcaption>#${x.rank} ${esc(x.text)} <span class="mono">${x.score.toFixed(3)}</span></figcaption></figure>`
    : `<figure><div class="small p-1">${esc(x.text.slice(0, 120))}</div><figcaption>#${x.rank} ${esc(x.filename)} <span class="mono">${x.score.toFixed(3)}</span></figcaption></figure>`).join("") || '<div class="empty">결과 없음</div>';
};
$("#g-q").addEventListener("keydown", e => { if (e.key === "Enter") $("#g-run").click(); });
gLoad();

fillModelSelect($("#m-models"), { multimodal: true });
$("#m-files").addEventListener("change", () => {
  Object.values(urls).forEach(URL.revokeObjectURL);
  const files = [...$("#m-files").files];
  files.forEach(f => (urls[f.name] = URL.createObjectURL(f)));
  $("#m-thumbs").innerHTML = files.map(f => `<figure><img src="${urls[f.name]}" alt=""><figcaption>${esc(f.name)}</figcaption></figure>`).join("") || '<div class="empty">이미지를 선택하세요</div>';
});
$("#m-run").onclick = async e => {
  const ids = selectedIds($("#m-models"));
  const files = [...$("#m-files").files];
  if (!ids.length || !files.length) return toast("모델과 이미지를 선택하세요", "err");
  const form = new FormData();
  form.append("model_ids", ids.join(","));
  form.append("query", $("#m-query").value);
  files.forEach(f => form.append("files", f));
  $("#m-out").innerHTML = '<div class="empty">모델 로드 및 인코딩 중…</div>';
  const r = await busy(e.target, () => api("/api/multimodal/retrieve", { method: "POST", form }));
  $("#m-out").innerHTML = r.results.map(res => `<div class="card result-col grow">
    <h3 class="mono break-all">${esc(res.hf_id)}</h3>
    ${res.error ? `<div class="errbox">${esc(res.error)}</div>` : `<div class="small muted">${res.seconds}s · Q: ${appliedInfo(res.applied.query)}</div>${warningsHtml(res.warnings)}
    <div class="thumbs mt-2">${res.ranking.map((x, i) => `<figure><img src="${urls[x.name]}" alt="">
      <figcaption><span class="badge ${i === 0 ? "ok" : "muted"}">#${i + 1}</span> <b class="mono">${x.score.toFixed(3)}</b><br>${esc(x.name)}</figcaption></figure>`).join("")}</div>`}
  </div>`).join("");
};
