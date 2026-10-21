// reasoning/sampling.html 화면 스크립트 — 표본 수별 다수결 · 검증기 고르기 · pass@n(RS3), 검증기 AUROC(RS4)
const VNAME = { format: "형식('정답:' 줄)", grounded: "근거에 있음", process: "과정 채점", llm: "LLM 판정" };
const pct = v => (v == null ? "-" : `${(v * 100).toFixed(1)}%`);

function render(r) {
  const vs = Object.keys(r.verifiers);
  $("#s-out").innerHTML = html`<div class="small muted">${r.model} · 예산 ${r.budget || "끔"} · 온도 ${r.temperature} · 과제 ${r.n_tasks} · 평균 출력 ${r.mean_out_tokens} 토큰 · ${r.seconds}초 · run #${r.run_id}
    · 저장소 <span class="mono">${r.bank}</span></div>
    <div class="table-wrap"><table><tr><th>n</th><th>다수결</th>${html.join(vs.map(v => html`<th>고르기: ${VNAME[v]}</th>`), "")}<th>pass@n (상한)</th></tr>
    ${html.join(r.curve.map(c => html`<tr><td>${c.n}</td><td><b>${pct(c.majority)}</b></td>${html.join(vs.map(v => html`<td>${pct(c[`best:${v}`])}</td>`), "")}<td>${pct(c.pass)}</td></tr>`), "")}</table></div>
    <p class="small muted">n=1 이 한 번 풀기입니다. 다수결 · 고르기가 pass@n 에서 멀수록 고르는 방법(검증기)이 병목입니다.</p>`;
  $("#v-out").innerHTML = html`<div class="table-wrap"><table><tr><th>검증기</th><th>AUROC</th><th>0.5 기준 정확도</th><th>맞은 풀이</th><th>틀린 풀이</th></tr>
    ${html.join(vs.map(v => html`<tr><td>${VNAME[v]}</td><td><b>${r.verifiers[v].auroc ?? "-"}</b></td><td>${pct(r.verifiers[v].acc_at_half)}</td><td>${r.verifiers[v].n_pos}</td><td>${r.verifiers[v].n_neg}</td></tr>`), "")}</table></div>
    <p class="small muted">AUROC 0.5 = 동전 던지기, 1 = 완벽히 가름. 틀린 풀이가 없으면(모두 맞음) 잴 수 없습니다.</p>`;
}

$("#s-run").onclick = e => runJobInto(e.target, "/api/reasoning/sample", {
  tasks: $("#s-tasks").value, max_per_type: +$("#s-per").value || 10, n: +$("#s-n").value || 5, temperature: +$("#s-temp").value || 0.7, budget: +$("#s-budget").value || 0,
  verifiers: $$("[data-v]").filter(c => c.checked).map(c => c.dataset.v), provider: $("#s-provider").value || null, model: $("#s-model").value.trim() || null,
}, $("#s-progress"), render).catch(err => ui.error($("#s-out"), err));

(async () => {
  const o = await api("/api/reasoning/overview");
  $("#s-tasks").innerHTML = html`${o.tasks.map(t => html`<option>${t.name}</option>`)}`;
  $("#s-verifiers").innerHTML = html`검증기: ${html.join(o.verifiers.map(v => html`<label class="row m-0"><input type="checkbox" data-v="${v}" ${v !== "llm" ? "checked" : ""}> ${VNAME[v]}</label>`), " ")}`;
})().catch(e => ui.error($("#s-out"), e));
