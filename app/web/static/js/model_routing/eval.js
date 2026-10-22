// model_routing/eval.html 화면 스크립트 — 후보 보정, 라우터 · 강한 후보 · 싼 후보 채점(MR7 · MR8)
const pct = v => (v == null ? "-" : `${Math.round(v * 100)}%`);
const POL = { router: "라우터(승격 포함)", strongest: "늘 가장 강한 후보", cheapest: "늘 가장 싼 후보" };

$("#c-run").onclick = e => runJobInto(e.target, "/api/model-routing/calibrate", { eval_set_id: +$("#c-set").value, max_queries: +$("#c-n").value }, $("#c-progress"), r => {
  $("#c-out").innerHTML = html`<div class="small muted">${r.eval_set} · 질문 ${r.n_queries} · ${r.seconds}초 · run #${r.run_id}</div>
    <div class="table-wrap"><table><tr><th>후보</th><th>품질(전체)</th><th>유형별</th><th>p95 ms</th><th>호출당 비용</th><th>성공률</th></tr>
    ${html.join(Object.entries(r.calibrated).map(([n, c]) => html`<tr><td>${n}</td><td><b>${c.quality.all ?? "-"}</b></td>
      <td class="small">${Object.entries(c.quality).filter(([t]) => t !== "all").map(([t, q]) => `${t} ${q}`).join(" · ")}</td><td>${c.p95_ms ?? "-"}</td><td>${c.cost}</td><td>${pct(c.reliability)}</td></tr>`), "")}</table></div>`;
}).catch(err => ui.error($("#c-out"), err));

$("#e-run").onclick = e => runJobInto(e.target, "/api/model-routing/eval", { eval_set_id: +$("#c-set").value, max_queries: +$("#e-n").value, channel: $("#e-channel").value },
  $("#e-progress"), r => {
    const s = r.summary;
    $("#e-out").innerHTML = html`<div class="small muted">${r.eval_set} · 질문 ${r.n_queries} · 강한 ${r.strongest} · 싼 ${r.cheapest} · ${r.seconds}초 · run #${r.run_id}</div>
      ${s.router_vs ? html`<div class="row small"><span>라우터가 지킨 품질(싼 → 강한 사이) <b>${pct(s.router_vs.quality_kept)}</b></span><span>강한 후보 대비 아낀 비용 <b>${pct(s.router_vs.cost_saved)}</b></span></div>` : ""}
      <div class="table-wrap"><table><tr><th>정책</th><th>품질</th><th>p50 ms</th><th>p95 ms</th><th>비용 합</th><th>승격률</th><th>사람에게</th></tr>
      ${html.join(["router", "strongest", "cheapest"].filter(p => s[p]).map(p => html`<tr><td>${POL[p]}</td><td><b>${s[p].quality}</b></td><td>${s[p].p50_ms}</td><td>${s[p].p95_ms}</td>
        <td>${s[p].cost}</td><td>${pct(s[p].escalation_rate)}</td><td>${pct(s[p].human_rate)}</td></tr>`), "")}</table></div>
      <div class="small muted">라우터가 처음 고른 후보: ${Object.entries(r.picks).map(([k, v]) => `${k} ${v}`).join(" · ")}</div>`;
  }).catch(err => ui.error($("#e-out"), err));

setupCollectionPickers({ col: $("#c-col"), set: $("#c-set") }).catch(e => ui.error($("#c-out"), e));
