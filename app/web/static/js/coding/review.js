// coding/review.html 화면 스크립트 — 규칙 · LLM 리뷰의 정밀도 · 재현율(CD5), diff 직접 검사
const llmBody = () => ({ use_llm: $("#v-llm").checked, provider: $("#v-provider").value || null, model: $("#v-model").value.trim() || null });
const yes = v => (v == null ? "-" : v ? "지적" : "통과");

$("#v-run").onclick = e => busy(e.target, () => api("/api/coding/review/eval", { method: "POST", body: llmBody() })).then(r => {
  $("#v-out").innerHTML = html`<div class="table-wrap"><table><tr><th>리뷰</th><th>사례</th><th>정밀도</th><th>재현율</th></tr>
    <tr><td>규칙</td><td>${r.rule.n}</td><td><b>${r.rule.precision ?? "-"}</b></td><td><b>${r.rule.recall ?? "-"}</b></td></tr>
    ${r.llm ? html`<tr><td>LLM</td><td>${r.llm.n}</td><td><b>${r.llm.precision ?? "-"}</b></td><td><b>${r.llm.recall ?? "-"}</b></td></tr>` : ""}</table></div>
    <div class="table-wrap"><table><tr><th>사례</th><th>정답</th><th>규칙</th><th>LLM</th></tr>
    ${html.join(r.rows.map(x => html`<tr><td class="small">${x.name}</td><td>${x.bad ? "나쁨" : "좋음"}</td><td><span class="badge ${x.rule === x.bad ? "ok" : "err"}">${yes(x.rule)}</span></td>
      <td>${x.llm == null ? "-" : html`<span class="badge ${x.llm === x.bad ? "ok" : "err"}">${yes(x.llm)}</span>`}</td></tr>`), "")}</table></div>
    <div class="small muted">run #${r.run_id}</div>`;
}).catch(err => ui.error($("#v-out"), err));

$("#d-run").onclick = e => busy(e.target, () => api("/api/coding/review", { method: "POST", body: { diff: $("#d-diff").value, ...llmBody() } })).then(r => {
  $("#d-out").innerHTML = html`${r.issues.length ? html`<ul class="small">${html.join(r.issues.map(i => html`<li><span class="badge warn">${i.rule}</span> ${i.file} — <span class="mono">${i.match}</span></li>`), "")}</ul>` : html`<span class="badge ok">규칙 지적 없음</span>`}
    ${r.llm ? html`<div class="small">LLM: ${r.llm.ok ? "문제 없음" : r.llm.issues.join(" / ") || r.llm.error || ""}</div>` : ""}`;
}).catch(err => ui.error($("#d-out"), err));
