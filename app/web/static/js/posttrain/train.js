// posttrain/train.html 화면 스크립트 — SFT · DPO 학습(P3 · P4), 학습한 모델 목록 · 지우기, 어댑터 병합(P5)
async function load() {
  const o = await api("/api/posttrain/overview");
  $("#t-env").innerHTML = html`기본 모델 <span class="mono">${o.base_model}</span> · 장치 ${o.device}${o.device === "cpu" ? " — CPU 학습은 느립니다(작은 걸음 수로 시작)" : ""}`;
  $("#t-data").innerHTML = html`${o.datasets.map(d => html`<option value="${d.name}" data-kind="${d.kind}">${d.name} (${d.kind} · ${d.n}건)</option>`)}`;
  const adapters = o.models.filter(m => m.kind === "llm_adapter");
  $("#t-init").innerHTML = html`<option value="">기본 모델에서</option>${adapters.filter(m => m.method === "sft").map(m => html`<option value="${m.id}">#${m.id} ${m.name}</option>`)}`;
  $("#t-models").innerHTML = o.models.length ? html`<div class="table-wrap"><table><tr><th></th><th>#</th><th>이름</th><th>종류</th><th>학습</th><th>끝점 모델</th><th></th></tr>
    ${html.join(o.models.map(m => html`<tr data-mid="${m.id}"><td>${m.kind === "llm_adapter" ? html`<input type="checkbox" data-pick aria-label="${m.name} 고르기">` : ""}</td><td class="small">${m.id}</td>
      <td class="small"><b>${m.name}</b><div class="muted mono">${m.base}</div></td><td class="small">${m.kind === "llm_merged" ? "병합 모델" : "어댑터"} · ${m.method}</td>
      <td class="small">${m.metrics?.loss_first != null ? html`손실 ${m.metrics.loss_first} → ${m.metrics.loss_last}` : ""}${m.metrics?.reward_acc_last != null ? html` · 선호 맞힘 ${m.metrics.reward_acc_last}` : ""}
        ${m.metrics?.seconds ? html` · ${m.metrics.seconds}초` : ""} · 예시 ${m.n_train}${m.exists ? "" : html` <span class="badge warn">파일 없음</span>`}</td>
      <td class="small mono">${m.endpoint_model}</td><td><button class="btn sm danger" data-del>지우기</button></td></tr>`), "")}</table></div>` : html`<div class="small muted">학습한 모델이 없습니다.</div>`;
  $$("[data-del]", $("#t-models")).forEach(b => b.onclick = async () => {
    const mid = b.closest("tr").dataset.mid;
    if (!(await ui.confirm(`모델 #${mid} 의 가중치 파일과 기록을 지웁니다.`, { ok: "지우기", danger: true }))) return;
    busy(b, () => api(`/api/posttrain/models/${mid}`, { method: "DELETE" })).then(load).catch(e => toast(e.message, "err"));
  });
}

$("#t-run").onclick = e => runJobInto(e.target, "/api/posttrain/train", { name: $("#t-name").value.trim(), dataset: $("#t-data").value, method: $("#t-method").value,
  init_adapter_id: +$("#t-init").value || null, max_steps: +$("#t-steps").value || 0, epochs: +$("#t-epochs").value || 1, max_len: +$("#t-len").value || 768, r: +$("#t-r").value || 8 },
  $("#t-progress"), r => { $("#t-out").innerHTML = html`<div class="small"><b>#${r.model_id}</b> 걸음 ${r.steps} · 손실 ${r.loss_first} → ${r.loss_last}${r.reward_acc_last != null ? ` · 선호 맞힘 ${r.reward_acc_last}` : ""} · ${r.seconds}초</div>`; load(); })
  .catch(err => toast(err.message, "err"));
$("#m-run").onclick = e => {
  const ids = $$("[data-pick]", $("#t-models")).filter(x => x.checked).map(x => +x.closest("tr").dataset.mid);
  if (!ids.length) return toast("합칠 어댑터를 고르세요", "err");
  runJobInto(e.target, "/api/posttrain/merge", { name: $("#m-name").value.trim(), adapters: ids, method: $("#m-method").value, into_base: $("#m-base").checked }, $("#m-progress"),
    () => { toast("합쳤습니다"); load(); }).catch(err => toast(err.message, "err"));
};
load().catch(e => ui.error($("#t-models"), e));
