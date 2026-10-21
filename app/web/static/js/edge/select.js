// edge/select.html 화면 스크립트 — 기기 프로필 → 임베딩 × 벡터 정밀도 × LLM 조합 추천(ED1 · ED2)
let PROFILES = {};

function comboRows(rows, withLlm) {
  if (!rows.length) return html`<p class="small muted">예산 안의 조합이 없습니다.</p>`;
  return html`<div class="table-wrap"><table><tr><th>임베딩</th><th>가중치 · 차원 · 벡터</th>${withLlm ? html`<th>LLM</th>` : ""}<th>메모리</th><th>색인</th><th>recall@10</th>${withLlm ? html`<th>답변 품질</th><th>점수</th>` : ""}<th>손실(검색 · 답변)</th></tr>
    ${html.join(rows.map(r => html`<tr><td class="small mono">${r.embedding}${r.pareto ? html` <span class="badge ok">파레토</span>` : ""}</td>
      <td class="small">${r.weight} · ${r.dim} · ${r.precision}</td>${withLlm ? html`<td class="small mono">${r.llm}</td>` : ""}<td>${r.ram_gb}GB</td><td class="small">${r.index_mb}MB</td><td>${r.recall}</td>
      ${withLlm ? html`<td>${r.quality ?? html`<span class="badge warn">미측정</span>`}${r.eval_set ? html` <span class="small muted">${r.eval_set}</span>` : ""}</td><td><b>${r.score ?? "-"}</b></td>` : ""}
      <td class="small">−${r.loss.retrieval}${r.loss.answer != null ? ` · −${r.loss.answer}` : ""}</td></tr>`), "")}</table></div>`;
}

function render(r) {
  const nearest = r.nearest.length ? html`<h3>가장 가까운 조합 (예산 초과)</h3><ul class="small">${html.join(r.nearest.map(n => html`<li class="mono">${n.embedding} · ${n.precision} + ${n.llm} — ${n.over.join(", ")}</li>`), "")}</ul>` : "";
  $("#s-out").innerHTML = html`<div class="small muted">후보 ${r.n_candidates} · 예산 안 ${r.n_fit} · 앱 예산 ${r.profile.budget_gb}GB · 청크 ${r.n_chunks}개</div>
    <h3>검색 + 답변</h3>${comboRows(r.with_llm, true)}${nearest}
    <h3>검색만 (LLM 없이 근거를 보여 줌)</h3>${comboRows(r.search_only, false)}`;
  $("#s-llms").innerHTML = r.llms.length ? html`<div class="table-wrap"><table><tr><th>파일</th><th>비트</th><th>파일</th><th>메모리 추정</th><th>사진</th><th>품질</th><th>지연(초/질문)</th><th>실측</th></tr>
    ${html.join(r.llms.map(l => html`<tr><td class="small mono">${l.name}</td><td>${l.quant}</td><td>${l.gb}GB</td><td>${l.ram_gb}GB</td><td>${l.vision ? "예" : "-"}</td>
      <td>${l.quality ?? "-"}</td><td>${l.mean_seconds ?? "-"}</td><td class="small muted">${l.source ? `${l.source} · ${l.eval_set}` : "-"}</td></tr>`), "")}</table></div>
    <p class="small muted">KV 캐시 추정: 맥락 1K 토큰당 ${r.kv_gb_per_1k}GB.</p>` : html`<p class="small muted">LLM_MODELS_DIR 에 GGUF 파일이 없습니다.</p>`;
}

function showProfile() {
  const p = PROFILES[$("#s-profile").value];
  $("#s-budget").value = p.budget_gb;
  $("#s-profile-info").textContent = `RAM ${p.ram_gb}GB 중 앱 예산 ${p.budget_gb}GB · 저장 공간 ${p.disk_gb}GB · 가속 ${p.accel}${p.vision ? " · 카메라" : ""}`;
}

$("#s-run").onclick = e => busy(e.target, () => api("/api/edge/recommend", { method: "POST", body: { profile: $("#s-profile").value, budget_gb: +$("#s-budget").value || null,
  n_chunks: +$("#s-chunks").value || 3000, ctx: +$("#s-ctx").value || 4096 } })).then(render).catch(err => ui.error($("#s-out"), err));

(async () => {
  PROFILES = (await api("/api/edge/profiles")).profiles;
  $("#s-profile").innerHTML = html`${Object.entries(PROFILES).map(([k, p]) => html`<option value="${k}" ${k === "tablet" ? "selected" : ""}>${p.label}</option>`)}`;
  $("#s-profile").onchange = showProfile;
  showProfile();
})().catch(e => ui.error($("#s-out"), e));
