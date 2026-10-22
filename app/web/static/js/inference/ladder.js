// inference/ladder.html 화면 스크립트 — 최적화 사다리(IF3~IF9): 칸 고르기 · 실행 · 통과 표
const ratio = v => (v == null ? "-" : `×${v}`);

async function init() {
  const [m, st] = await Promise.all([api("/api/bigmodel/machine"), api("/api/inference/steps")]);
  const opts = html`${m.gguf.map(f => html`<option value="${f.name}">${f.name} · ${f.gb} GB</option>`)}`;
  $("#l-model").innerHTML = opts;
  $("#l-alt").innerHTML = html`<option value="">없음</option>${opts}`;
  $("#l-draft").innerHTML = html`<option value="">없음</option>${opts}`;
  $("#l-steps").innerHTML = html`${Object.entries(st.steps).filter(([k]) => k !== "baseline").map(([k, v]) => html`<label class="row small m-0"><input type="checkbox" value="${k}" checked> ${v.stage} ${v.label}</label>`)}`;
  if (!m.llama_server) toast("LLAMA_SERVER_BIN 이 설정되지 않아 실행할 수 없습니다", "err");
}

$("#l-run").onclick = e => runJobInto(e.target, "/api/inference/ladder", { model: $("#l-model").value, alt_model: $("#l-alt").value || null, draft: $("#l-draft").value || null,
  eval_set_id: +$("#l-set").value, max_queries: +$("#l-n").value, concurrency: +$("#l-conc").value, max_drop: +$("#l-drop").value,
  steps: [...document.querySelectorAll("#l-steps input:checked")].map(x => x.value) }, $("#l-progress"), r => {
  const s = r.summary;
  $("#l-out").innerHTML = html`<div class="small muted">${r.model} · ${r.eval_set} · 질문 ${r.n_queries} · 동시 ${r.concurrency} · ${r.seconds}초 · run #${r.run_id}</div>
    <div class="row small"><span>남긴 칸: <b>${s.kept.join(" → ") || "없음"}</b></span><span>p95 ${ratio(s.p95_change)}</span><span>처리량 ${ratio(s.tps_change)}</span>
      <span>성공 작업당 장치 시간 ${ratio(s.cost_change)}</span>${s.quality_diff ? html`<span>품질 차 ${s.quality_diff.diff >= 0 ? "+" : ""}${s.quality_diff.diff.toFixed(3)}</span>` : ""}<span class="muted">${s.canary || ""}</span></div>
    <div class="table-wrap"><table><tr><th>단계</th><th>칸</th><th>품질</th><th>p50 ms</th><th>p95 ms</th><th>토큰/초</th><th>성공</th><th>장치 초/성공</th><th>KV MiB</th><th>판정</th></tr>
    ${html.join(r.steps.map(x => html`<tr><td>${x.stage}</td><td>${x.label_ko || x.label}</td><td>${x.quality ?? "-"}</td><td>${x.p50_ms ?? "-"}</td><td>${x.p95_ms ?? "-"}</td><td>${x.tokens_per_s ?? "-"}</td>
      <td>${x.success ?? "-"}</td><td>${x.device_s_per_success ?? "-"}</td><td>${x.kv_cache_mib ?? "-"}</td>
      <td>${x.status === "skipped" ? html`<span class="badge muted">건너뜀</span> <span class="small muted">${x.why}</span>` : x.status === "error" ? html`<span class="badge err small">${x.error}</span>`
        : x.gate.pass ? html`<span class="badge ok">통과</span> <span class="small muted">${x.gate.why}</span>` : html`<span class="badge warn">탈락</span> <span class="small muted">${x.gate.why}</span>`}</td></tr>`), "")}</table></div>`;
}).catch(err => ui.error($("#l-out"), err));

init().catch(err => ui.error($("#l-out"), err));
setupCollectionPickers({ col: $("#l-col"), set: $("#l-set") }).catch(e => ui.error($("#l-out"), e));
