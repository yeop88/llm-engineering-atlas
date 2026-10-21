// rlvr/tasks.html 화면 스크립트 — 검증 가능한 과제 만들기(RV1), 환경-실제 차이(RV2), 보상 항목별 기여(RV3)
const TYPE = { article_title: "조문 제목", article_number: "조문 번호", citation_count: "인용 수(그래프)", calc: "계산(시험 전용)" };

async function load() {
  const o = await api("/api/rlvr/overview");
  $("#k-list").innerHTML = o.tasks.length ? html`<div class="table-wrap"><table><tr><th>과제</th><th>학습</th><th>시험</th><th>유형별</th></tr>
    ${html.join(o.tasks.map(t => html`<tr><td class="mono small">${t.name}</td><td>${t.train}</td><td>${t.test}</td><td class="small">${html.join(Object.entries(t.counts || {}).map(([k, v]) => html`${TYPE[k] || k} ${v}`), " · ")}</td></tr>`), "")}</table></div>` : "";
  $$("[data-tasks]").forEach(sel => { sel.innerHTML = html`${o.tasks.map(t => html`<option>${t.name}</option>`)}`; });
  $("#k-weights").innerHTML = html`보상 항목: ${html.join(Object.entries(o.weights).map(([k, v]) => html`<span class="badge">${k} ${v}</span>`), " ")} — 정답은 마지막 '정답:' 줄만 봅니다(본문 중간 숫자를 정답으로 읽지 않게).`;
}

$("#k-build").onclick = e => busy(e.target, () => api("/api/rlvr/tasks", { method: "POST", body: { name: $("#k-name").value.trim(), collection_id: +$("#k-col").value, graph: $("#k-graph").value.trim(), n_per_type: +$("#k-n").value || 30 } }))
  .then(r => {
    $("#k-out").innerHTML = html`<div class="small">학습 ${r.train} · 시험 ${r.test} — ${html.join(Object.entries(r.counts).map(([k, v]) => html`${TYPE[k] || k} ${v}`), " · ")}</div>
      <ul class="small">${html.join(r.examples.map(t => html`<li><span class="badge">${TYPE[t.type]}</span> ${t.q} → <b>${t.answer}</b></li>`), "")}</ul>`;
    load();
  }).catch(err => ui.error($("#k-out"), err));
$("#k-env").onclick = e => busy(e.target, () => api("/api/rlvr/env/check", { method: "POST", body: { tasks: $("#k-env-tasks").value, n: 10 } }))
  .then(r => { $("#k-env-out").innerHTML = html`<div class="small">과제 ${r.n} · 근거 파일 겹침 ${r.docs_overlap} · 그래프 집계 같음 ${r.graph_same} · 기록에서 되돌린 것 ${r.recorded}
    ${r.docs_overlap < 0.8 ? html` <span class="badge warn">기록이 낡았을 수 있음 — 기록 파일을 지우고 다시</span>` : html` <span class="badge ok">기록 = 실제</span>`}</div>`; })
  .catch(err => ui.error($("#k-env-out"), err));
$("#k-score").onclick = e => busy(e.target, () => api("/api/rlvr/score", { method: "POST", body: { tasks: $("#k-r-tasks").value, task_id: $("#k-r-id").value.trim(), text: $("#k-r-text").value } }))
  .then(r => { $("#k-score-out").innerHTML = html`<div class="small"><b>${r.task.q}</b> 정답 ${r.task.answer}</div><div class="row small"><b>보상 ${r.reward}</b>
    ${html.join(Object.entries(r.parts).map(([k, v]) => html`<span class="badge ${v < 0 ? "warn" : v > 0 ? "ok" : ""}">${k} ${v}</span>`), " ")} · 맞음 ${r.correct ? "예" : "아니요"} · 읽은 정답 '${r.final ?? "-"}'</div>`; })
  .catch(err => ui.error($("#k-score-out"), err));

setupCollectionPickers({ col: $("#k-col") }).catch(() => {});
load().catch(e => ui.error($("#k-list"), e));
