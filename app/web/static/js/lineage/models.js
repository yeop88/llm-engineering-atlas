// lineage/models.html 화면 스크립트 — GGUF · HF 모델 읽기, 계열 · 구조 · 맥락 · 모달리티 · 라이선스 표(LN1~LN6)
async function load() {
  const r = await api("/api/lineage/models");
  if (!r.models.length) { ui.empty($("#m-out"), "아직 읽은 모델이 없습니다 — 가진 GGUF 를 읽거나 HF 저장소 id 를 넣으세요."); return; }
  $("#m-out").innerHTML = html`<div class="table-wrap"><table><tr><th>모델</th><th>계열 · 세대</th><th>구조</th><th>파라미터</th><th>층 · 차원 · KV 머리</th><th>맥락</th><th>모달리티</th><th>라이선스</th><th>기반 모델</th><th></th></tr>
    ${html.join(r.models.map(m => html`<tr><td class="small">${m.file || m.name}${m.quantized_by ? html`<div class="muted">양자화 ${m.quantized_by}${m.bpw ? ` · ${m.bpw}비트` : ""}</div>` : ""}</td>
      <td>${m.family} ${m.generation || ""}<div class="small muted">${m.org}</div></td><td class="mono small">${m.arch}${m.experts ? html`<div>MoE ${m.experts_used}/${m.experts}</div>` : ""}</td>
      <td>${m.params_b}B${m.size_label ? html` <span class="small muted">(${m.size_label})</span>` : ""}</td><td class="small">${m.layers} · ${m.hidden} · ${m.kv_heads}</td>
      <td class="small">${m.context.trained ?? "-"}${m.context.rope_scaling ? html`<div class="muted">확장 ${JSON.stringify(m.context.rope_scaling)}</div>` : ""}${m.context.sliding_window ? html`<div class="muted">창 ${m.context.sliding_window}</div>` : ""}</td>
      <td class="small">${m.modalities.join(" · ")}${m.mmproj === false && m.modalities.includes("image") ? html` <span class="badge warn">투영기 파일 없음</span>` : ""}</td>
      <td class="small">${m.license.name || m.license.id || "-"}${m.license.check ? html` <span class="badge warn">확인 필요</span><div class="muted">${m.license.notes.join(" · ")}</div>` : ""}</td>
      <td class="small">${m.base_models.map(b => b.repo ? html`<a href="${b.repo}" rel="noopener">${b.name || b.repo}</a>` : b.name).join(" ") || "-"}</td>
      <td><button class="btn sm danger" data-del="${m.key}">지우기</button></td></tr>`), "")}</table></div>`;
}

$("#m-out").addEventListener("click", async e => {
  const b = e.target.closest("[data-del]");
  if (!b || !(await ui.confirm(`${b.dataset.del} 를 계보에서 지울까요?`))) return;
  api(`/api/lineage/models/${encodeURIComponent(b.dataset.del)}`, { method: "DELETE" }).then(load).catch(err => toast(err.message, "err"));
});
$("#m-scan").onclick = e => busy(e.target, () => api("/api/lineage/scan", { method: "POST" })).then(r => {
  toast(`${r.read.length}개 읽음${r.errors.length ? ` · 실패 ${r.errors.length}` : ""}`);
  return load();
}).catch(err => ui.error($("#m-out"), err));
$("#m-hf-run").onclick = e => busy(e.target, () => api("/api/lineage/inspect", { method: "POST", body: { hf_id: $("#m-hf").value.trim() } })).then(load).catch(err => toast(err.message, "err"));
load().catch(err => ui.error($("#m-out"), err));
