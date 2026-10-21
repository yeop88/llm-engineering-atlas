// rlvr/eval.html 화면 스크립트 — 학습 / 시험 · 유형별 정답률, 레드팀, 외움(보상 해킹) 표시(RV6)
function render(r) {
  const types = [...new Set(r.models.flatMap(m => Object.keys(m.by_type)))];
  const sf = Object.fromEntries((r.safety || []).map(s => [s.model, s.summary]));
  $("#v-out").innerHTML = html`<div class="small muted">${r.tasks} · ${r.seconds}초${r.run_id ? ` · run #${r.run_id}` : ""}</div>
    <div class="table-wrap"><table><tr><th>모델</th><th>학습 정답률</th><th>시험 정답률</th>${html.join(types.map(t => html`<th class="small">${t}</th>`), "")}<th>평균 길이</th><th>공격 방어</th><th>정상 통과</th></tr>
    ${html.join(r.models.map(m => html`<tr><td class="small mono">${m.model}</td><td>${m.acc.train ?? "-"}</td><td>${m.acc.test ?? "-"}</td>
      ${html.join(types.map(t => html`<td class="small">${m.by_type[t] ? `${m.by_type[t].acc} (${m.by_type[t].n})` : "-"}</td>`), "")}<td class="small">${m.mean_chars}자</td>
      <td>${sf[m.model]?.attack_pass_rate ?? "-"}</td><td>${sf[m.model]?.benign_pass_rate ?? "-"}</td></tr>`), "")}</table></div>
    ${r.hacking ? (r.hacking.ok ? html`<span class="badge ok">외움 신호 없음</span>` : html`${html.join(r.hacking.flags.map(f => html`<div><span class="badge err">외움 의심</span> ${f}</div>`), "")}`) : ""}`;
}

$("#v-run").onclick = e => runJobInto(e.target, "/api/rlvr/eval", { tasks: $("#v-tasks").value, models: $("#v-models").value.split(",").map(s => s.trim()).filter(Boolean),
  max_per_split: +$("#v-n").value || 30, redteam: $("#v-rt").checked }, $("#v-progress"), render).catch(err => toast(err.message, "err"));

(async () => {
  const o = await api("/api/rlvr/overview");
  $("#v-tasks").innerHTML = html`${o.tasks.map(t => html`<option>${t.name}</option>`)}`;
  if (o.policies.length) $("#v-models").value = ["pt-base", o.policies[0].endpoint_model].join(", ");
})().catch(e => ui.error($("#v-out"), e));
