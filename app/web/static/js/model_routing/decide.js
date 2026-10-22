// model_routing/decide.html 화면 스크립트 — 라우팅 결정(MR1~MR6) · 답하기와 승격(MR7) · 후보 목록(MR5)
const RISK = { low: ["ok", "낮음"], mid: ["warn", "중간"], high: ["err", "높음"] };
let W = {};

function body() {
  const weights = Object.fromEntries(Object.keys(W).map(k => [k, +$(`#w-${k}`).value]));
  return { text: $("#d-text").value, channel: $("#d-channel").value, has_image: $("#d-image").checked, budget_ms: +$("#d-budget").value || null,
    max_cost: $("#d-cost").value === "" ? null : +$("#d-cost").value, weights, use_llm: $("#d-llm").checked };
}

function decisionHtml(d) {
  const r = RISK[d.risk.level];
  return html`<div class="row small"><span>유형 <b>${d.task.label}</b> <span class="muted">(${d.task.by} · ${d.task.why})</span></span>
      <span>위험 <span class="badge ${r[0]}">${r[1]}</span> ${d.risk.domains.join(" · ")}${d.risk.injection ? " · 인젝션 의심" : ""}</span>
      <span>품질 하한 ${d.floor}</span><span>예산 ${d.budget_ms}ms</span><span>경로 <span class="mono">${d.path}</span></span>
      ${d.human_approval ? html`<span class="badge warn">사람 승인 필요</span>` : ""}</div>
    <div class="small">승격 사슬: <b>${d.chain.join(" → ")}</b></div>
    <div class="table-wrap"><table><tr><th>후보</th><th>종류</th><th>품질</th><th>p95 ms</th><th>비용</th><th>점수</th><th>하한</th><th>제외 이유</th></tr>
    ${html.join(d.candidates.map(c => html`<tr><td>${c.name}${c.name === d.pick ? html` <span class="badge ok">선택</span>` : ""}</td><td>${c.kind}</td>
      <td>${c.quality}${c.measured ? "" : html` <span class="small muted">추정</span>`}</td><td>${c.p95_ms}</td><td>${c.cost}</td><td>${c.score ?? "-"}</td>
      <td>${c.meets_floor ? "✓" : "✗"}</td><td class="small">${c.excluded.join(" · ") || "-"}</td></tr>`), "")}</table></div>`;
}

$("#d-run").onclick = e => busy(e.target, () => api("/api/model-routing/decide", { method: "POST", body: body() })).then(d => {
  $("#d-out").innerHTML = decisionHtml(d);
}).catch(err => ui.error($("#d-out"), err));

$("#d-answer").onclick = e => busy(e.target, () => api("/api/model-routing/answer", { method: "POST", body: { ...body(), collection_id: +$("#d-col").value } })).then(r => {
  $("#d-out").innerHTML = decisionHtml(r.decision);
  $("#a-out").innerHTML = html`<div class="small">시도: ${html.join(r.tries.map(t => html`<span class="badge ${t.pass ? "ok" : "warn"}">${t.candidate} · ${t.why}${t.ms ? ` · ${t.ms}ms` : ""}</span> `), "")}</div>
    ${r.answer ? html`<div class="pre">${r.answer}</div>${r.status === "approval" ? html`<div class="badge warn">사람 승인 대기 — 외부 행동 · 인젝션 의심 요청</div>` : ""}${ui.aiNotice(r.notice, r.trace_id)}`
      : html`<div class="errbox">${r.why}</div>`}`;
}).catch(err => ui.error($("#a-out"), err));

api("/api/model-routing/candidates").then(r => {
  W = r.weights;
  $("#d-channel").innerHTML = html`${Object.entries(r.budgets).map(([k, v]) => html`<option value="${k}">${k} (${v}ms)</option>`)}`;
  $("#d-channel").value = "api";
  $("#d-weights").innerHTML = html`${Object.entries(W).map(([k, v]) => html`<div class="field"><label for="w-${k}">가중치 ${k}</label><input id="w-${k}" type="number" value="${v}" min="0" max="1" step="0.05" class="w-md"></div>`)}`;
  $("#c-out").innerHTML = html`<div class="table-wrap"><table><tr><th>이름</th><th>제공자</th><th>종류</th><th>모달리티</th><th>유형별 품질</th><th>p95 ms</th><th>비용</th><th>신뢰성</th><th>잰 날</th></tr>
    ${html.join(r.candidates.map(c => html`<tr><td>${c.name}</td><td>${c.provider}</td><td>${c.kind}</td><td>${c.modalities.join(" · ")}</td>
      <td class="small">${Object.entries(c.quality || {}).map(([t, q]) => `${t} ${q}`).join(" · ") || "-"}</td><td>${c.p95_ms ?? "-"}</td><td>${c.cost ?? "-"}</td><td>${c.reliability}</td><td>${c.measured_at || "-"}</td></tr>`), "")}</table></div>`;
}).catch(err => ui.error($("#c-out"), err));
setupCollectionPickers({ col: $("#d-col") }).catch(e => ui.error($("#a-out"), e));
