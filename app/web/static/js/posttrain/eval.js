// posttrain/eval.html 화면 스크립트 — 학습 전후 품질 · 안전성 비교(P6), 병합 모델 GGUF 변환 · 양자화(P7)
function render(r) {
  const sf = Object.fromEntries((r.safety || []).map(s => [s.model, s.summary]));
  $("#e-out").innerHTML = html`<div class="small muted">${r.eval_set.name} · 질문 ${r.n_queries} · ${r.seconds}초${r.run_id ? ` · run #${r.run_id}` : ""}</div>
    <div class="table-wrap"><table><tr><th>모델</th><th>품질</th><th>기준 대비</th><th>거절 · 답함</th><th>생성 속도</th><th>공격 방어</th><th>정상 통과</th></tr>
    ${html.join(r.quality.map(q => q.status !== "ok" ? html`<tr><td class="small">${q.model}</td><td colspan="6"><span class="badge err">실패</span> ${q.error}</td></tr>` : html`<tr><td class="small mono">${q.model}</td>
      <td>${q.quality}${q.quality_ci ? html`<div class="small muted">[${q.quality_ci.join(", ")}]</div>` : ""}</td>
      <td class="small">${q.vs_first ? html`${q.vs_first.diff > 0 ? "+" : ""}${q.vs_first.diff} ${q.vs_first.significant ? html`<span class="badge ${q.vs_first.diff < 0 ? "err" : "ok"}">유의</span>` : html`<span class="badge">불확실</span>`}` : "기준"}</td>
      <td class="small">${q.summary?.correct_refusal != null ? `바른 거절 ${q.summary.correct_refusal}` : ""} · 답함 ${q.summary?.answer_rate ?? "-"}</td><td class="small">${q.tokens_per_second ?? "-"} 토큰/초</td>
      <td>${sf[q.model] ? sf[q.model].attack_pass_rate : "-"}</td><td>${sf[q.model] ? sf[q.model].benign_pass_rate : "-"}</td></tr>`), "")}</table></div>`;
}

async function load() {
  const o = await api("/api/posttrain/overview");
  const merged = o.models.filter(m => m.kind === "llm_merged");
  $("#x-model").innerHTML = merged.length ? html`${merged.map(m => html`<option value="${m.id}">#${m.id} ${m.name}</option>`)}` : html`<option value="">병합 모델 없음 — SFT · DPO · 병합에서 기본 모델에 합치기</option>`;
  $("#x-env").innerHTML = o.convert_script ? html`<span class="badge ok">변환 스크립트 있음</span>` : html`<span class="badge warn">LLAMA_CONVERT_SCRIPT 없음</span> — 실행할 명령만 보여 줍니다(llama.cpp 저장소의 convert_hf_to_gguf.py)`;
  if (o.models.length && $("#e-models").value === "pt-base") $("#e-models").value = ["pt-base", ...o.models.slice(0, 2).map(m => m.endpoint_model)].join(", ");
}

$("#e-run").onclick = e => runJobInto(e.target, "/api/posttrain/evaluate", { models: $("#e-models").value.split(",").map(s => s.trim()).filter(Boolean), eval_set_id: +$("#e-set").value,
  max_queries: +$("#e-n").value || 10, redteam: $("#e-rt").checked }, $("#e-progress"), render).catch(err => toast(err.message, "err"));
$("#x-run").onclick = e => {
  if (!$("#x-model").value) return toast("병합 모델이 없습니다", "err");
  runJobInto(e.target, "/api/posttrain/export", { model_id: +$("#x-model").value, quant: $("#x-q").value }, $("#x-progress"), r => {
    $("#x-out").innerHTML = html`${r.ok ? html`<span class="badge ok">변환함</span> ${html.join((r.files || []).map(f => html`<span class="mono small">${f.path} (${f.gb}GB)</span>`), " · ")}` : html`<span class="badge warn">${r.reason}</span>`}
      <pre class="pre small">${(r.commands || []).join("\n")}</pre>${(r.steps || []).length ? html`<details class="small"><summary>출력</summary><pre class="pre small">${r.steps.map(s => `${s.step} (${s.code})\n${s.tail}`).join("\n\n")}</pre></details>` : ""}`;
  }).catch(err => toast(err.message, "err"));
};
setupCollectionPickers({ col: $("#e-col"), set: $("#e-set") }).catch(() => {});
load().catch(e => ui.error($("#x-env"), e));
