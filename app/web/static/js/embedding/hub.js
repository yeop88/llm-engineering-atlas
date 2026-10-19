// embedding/hub.html 화면 스크립트 (템플릿에서 옮김 — 화면 JS 는 static/js/<영역>/<화면>.js)
async function search(btn) {
  const qs = new URLSearchParams({ q: $("#q").value, sort: $("#sort").value, limit: $("#limit").value });
  if ($("#pipe").value) qs.set("pipeline_tag", $("#pipe").value);
  $("#rows").innerHTML = '<tr><td colspan="7" class="empty">검색 중…</td></tr>';
  const rows = await busy(btn, () => api(`/api/hub/search?${qs}`));
  $("#rows").innerHTML = rows.map(r => `<tr>
    <td><a class="mono" href="https://huggingface.co/${esc(r.hf_id)}" target="_blank" rel="noopener">${esc(r.hf_id)}</a>
      ${r.gated ? '<span class="badge warn">gated</span>' : ""} ${r.sentence_transformers ? '<span class="badge">ST</span>' : ""}
      <div class="small muted">${esc(r.pipeline_tag || "")}</div></td>
    <td class="num">${fmtNum(r.downloads)}</td><td class="num">${fmtNum(r.likes)}</td>
    <td class="nowrap">${(r.created_at || "").slice(0, 10)}</td><td class="small">${esc(r.library || "-")}</td><td class="small">${esc(r.license || "-")}</td>
    <td class="right nowrap"><button class="btn sm" onclick="info('${esc(r.hf_id)}', this)">상세</button>
      ${r.registered_id ? `<a class="btn sm" href="/models/${r.registered_id}">등록됨 →</a>` : `<button class="btn sm primary" onclick="importModel('${esc(r.hf_id)}', this)">추가</button>`}</td>
  </tr>`).join("") || '<tr><td colspan="7" class="empty">결과 없음</td></tr>';
}
$("#d-go").onclick = async e => {
  const qs = new URLSearchParams({ days: $("#d-days").value, min_likes: $("#d-likes").value });
  const r = await busy(e.target, () => api(`/api/hub/discover?${qs}`));
  $("#d-rows").innerHTML = r.candidates.map(c => `<tr>
    <td><a class="mono" href="https://huggingface.co/${esc(c.hf_id)}" target="_blank" rel="noopener">${esc(c.hf_id)}</a>
      ${c.korean ? '<span class="badge ok">한국어</span>' : ""} ${c.gated ? '<span class="badge warn">gated</span>' : ""} ${c.sentence_transformers ? '<span class="badge">ST</span>' : ""}</td>
    <td class="small">${esc(c.found_by)}</td><td class="num">${fmtNum(c.likes)}</td><td class="num">${c.age_days}</td><td class="small">${esc(c.license || "-")}</td>
    <td class="num small">${c.score}</td>
    <td class="right nowrap"><button class="btn sm" onclick="info('${esc(c.hf_id)}', this)">상세</button> <button class="btn sm primary" onclick="importModel('${esc(c.hf_id)}', this)">추가</button></td>
  </tr>`).join("") || '<tr><td colspan="7" class="empty">조건에 맞는 새 후보가 없습니다</td></tr>';
};
async function info(id, btn) {
  const m = await busy(btn, () => api(`/api/hub/info?hf_id=${encodeURIComponent(id)}`));
  $("#dlg-title").textContent = id;
  const prompts = Object.entries(m.prompts || {});
  $("#dlg-body").innerHTML = `<div class="kv">${[
    ["파라미터", m.params], ["차원(추정)", m.dim], ["최대 길이", fmtNum(m.max_seq_len)], ["라이선스", m.license], ["언어", m.languages],
    ["모달리티", m.modalities.join(", ")], ["trust_remote_code", m.trust_remote_code], ["gated", m.gated], ["저장소 크기", fmtBytes(m.size_bytes)],
    ["sentence-transformers", m.sentence_transformers], ["쿼리/문서 프롬프트", `${m.query_prompt || "-"} / ${m.document_prompt || "-"}`],
  ].map(([k, v]) => `<div>${k}</div><div>${esc(v ?? "-")}</div>`).join("")}</div>
  ${prompts.length ? `<h3 style="margin-top:14px">정의된 프롬프트</h3><pre>${esc(prompts.map(([k, v]) => `${k}: ${v}`).join("\n"))}</pre>` : ""}`;
  $("#dlg").showModal();
}
async function importModel(id, btn) {
  const m = await busy(btn, () => api("/api/hub/import", { method: "POST", body: { hf_id: id } }));
  toast(`${m.hf_id} 추가됨`, "ok");
  btn.outerHTML = `<a class="btn sm" href="/models/${m.id}">등록됨 →</a>`;
}
$("#go").onclick = e => search(e.target);
$("#q").addEventListener("keydown", e => { if (e.key === "Enter") search($("#go")); });
search($("#go"));
