// compress/kv.html 화면 스크립트 — KV 남기기 정책 × 비율, 키 · 값 비트별 충실도(KC3~KC5)
const POL = { full: "가득 참(기준)", window: "최근 창만", sink_window: "첫 토큰 + 최근 창", heavy: "누적 주의", snap: "질문 관찰 창" };
const pct = v => (v == null ? "-" : `${(v * 100).toFixed(1)}%`);

$("#k-run").onclick = e => runJobInto(e.target, "/api/compress/kv", { eval_set_id: +$("#k-set").value, max_queries: +$("#k-n").value || 8, max_new: +$("#k-new").value || 40,
  keeps: $("#k-keeps").value.split(",").map(s => +s.trim()).filter(n => n > 0 && n <= 1) }, $("#k-progress"), r => {
  $("#k-out").innerHTML = html`<div class="small muted">${r.eval_set} · ${r.model} · ${r.seconds}초 · run #${r.run_id}</div>
    <div class="table-wrap"><table><tr><th>정책</th><th>남길 비율</th><th>실제 남김</th><th>다음 토큰 일치</th><th>KL</th><th>갈라진 답</th></tr>
    ${html.join(r.results.map(x => html`<tr><td>${POL[x.policy] || x.policy}</td><td>${x.keep}</td><td>${pct(x.kept_ratio)}</td><td><b>${pct(x.top1)}</b></td><td>${x.kl}</td><td>${pct(x.diverged)}</td></tr>`), "")}</table></div>`;
}).catch(err => ui.error($("#k-out"), err));

(async () => {
  await setupCollectionPickers({ col: $("#k-col"), set: $("#k-set") });
  $("#k-model").textContent = `모델: ${(await api("/api/compress/options")).model} (작은 공개 LM, 처음 쓸 때 내려받음)`;
})().catch(e => ui.error($("#k-out"), e));
