// embedding/hub.html 화면 스크립트 (템플릿에서 옮김 — 화면 JS 는 static/js/<영역>/<화면>.js)
async function search(btn) {
  const qs = new URLSearchParams({ q: $("#q").value, sort: $("#sort").value, limit: $("#limit").value });
  if ($("#pipe").value) qs.set("pipeline_tag", $("#pipe").value);
  $("#rows").innerHTML = html`<tr><td colspan="7" class="empty">검색 중…</td></tr>`;
  const rows = await busy(btn, () => api(`/api/hub/search?${qs}`));
  $("#rows").innerHTML = html.or(html.join(rows.map(r => html`<tr>
    <td><a class="mono" href="https://huggingface.co/${r.hf_id}" target="_blank" rel="noopener">${r.hf_id}</a>
      ${r.gated ? html`<span class="badge warn">gated</span>` : ""} ${r.sentence_transformers ? html`<span class="badge">ST</span>` : ""}
      <div class="small muted">${r.pipeline_tag || ""}</div></td>
    <td class="num">${fmtNum(r.downloads)}</td><td class="num">${fmtNum(r.likes)}</td>
    <td class="nowrap">${(r.created_at || "").slice(0, 10)}</td><td class="small">${r.library || "-"}</td><td class="small">${r.license || "-"}</td>
    <td class="right nowrap"><button class="btn sm" onclick="info('${r.hf_id}', this)">상세</button>
      ${r.registered_id ? html`<a class="btn sm" href="/embedding/models/${r.registered_id}">등록됨 →</a>` : html`<button class="btn sm primary" onclick="importModel('${r.hf_id}', this)">추가</button>`}</td>
  </tr>`), ""), html`<tr><td colspan="7" class="empty">결과 없음</td></tr>`);
}
$("#d-go").onclick = async e => {
  const qs = new URLSearchParams({ days: $("#d-days").value, min_likes: $("#d-likes").value });
  const r = await busy(e.target, () => api(`/api/hub/discover?${qs}`));
  $("#d-rows").innerHTML = html.or(html.join(r.candidates.map(c => html`<tr>
    <td><a class="mono" href="https://huggingface.co/${c.hf_id}" target="_blank" rel="noopener">${c.hf_id}</a>
      ${c.korean ? html`<span class="badge ok">한국어</span>` : ""} ${c.gated ? html`<span class="badge warn">gated</span>` : ""} ${c.sentence_transformers ? html`<span class="badge">ST</span>` : ""}</td>
    <td class="small">${c.found_by}</td><td class="num">${fmtNum(c.likes)}</td><td class="num">${c.age_days}</td><td class="small">${c.license || "-"}</td>
    <td class="num small">${c.score}</td>
    <td class="right nowrap"><button class="btn sm" onclick="info('${c.hf_id}', this)">상세</button> <button class="btn sm primary" onclick="importModel('${c.hf_id}', this)">추가</button></td>
  </tr>`), ""), html`<tr><td colspan="7" class="empty">조건에 맞는 새 후보가 없습니다</td></tr>`);
};
async function info(id, btn) {
  const m = await busy(btn, () => api(`/api/hub/info?hf_id=${encodeURIComponent(id)}`));
  $("#dlg-title").textContent = id;
  const prompts = Object.entries(m.prompts || {});
  $("#dlg-body").innerHTML = html`<div class="kv">${html.join([
    ["파라미터", m.params], ["차원(추정)", m.dim], ["최대 길이", fmtNum(m.max_seq_len)], ["라이선스", m.license], ["언어", m.languages],
    ["모달리티", m.modalities.join(", ")], ["trust_remote_code", m.trust_remote_code], ["gated", m.gated], ["저장소 크기", fmtBytes(m.size_bytes)],
    ["sentence-transformers", m.sentence_transformers], ["쿼리/문서 프롬프트", `${m.query_prompt || "-"} / ${m.document_prompt || "-"}`],
  ].map(([k, v]) => html`<div>${k}</div><div>${v ?? "-"}</div>`), "")}</div>
  ${prompts.length ? html`<h3 class="mt-4">정의된 프롬프트</h3><pre>${html.join(prompts.map(([k, v]) => html`${k}: ${v}`), "\n")}</pre>` : ""}`;
  $("#dlg").showModal();
}
async function importModel(id, btn) {
  const m = await busy(btn, () => api("/api/hub/import", { method: "POST", body: { hf_id: id } }));
  toast(`${m.hf_id} 추가됨`, "ok");
  btn.outerHTML = html`<a class="btn sm" href="/embedding/models/${m.id}">등록됨 →</a>`;
}
$("#go").onclick = e => search(e.target);
$("#q").addEventListener("keydown", e => { if (e.key === "Enter") search($("#go")); });
search($("#go"));
