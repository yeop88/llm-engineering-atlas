// compliance/audit.html 화면 스크립트 — 영향 평가 초안 · 저장 · 승인(RC5), 통제 감사 실행 · 기록(RC8)
let CAT = null;
const DECISION = { proceed: "진행", proceed_with_conditions: "조건부 진행", hold: "보류" };
const STATUS = { pass: ["ok", "통과"], fail: ["err", "실패"], partial: ["warn", "부분"], gap: ["err", "없음"], manual: ["", "수동"], no_evidence: ["warn", "근거 없음"], error: ["err", "오류"] };
const badge = s => html`<span class="badge ${(STATUS[s] || ["", s])[0]}">${(STATUS[s] || ["", s])[1]}</span>`;

function renderEvidence(r) {
  const ev = r.evidence;
  const ndcg = ev.retrieval?.["ndcg@10"];
  const line = (label, x, body) => x ? html`<li><b>${label}</b> run #${x.run_id} (${x.days_ago}일 전) — ${body}</li>` : html`<li><b>${label}</b> <span class="muted">기록 없음</span></li>`;
  $("#a-evidence").innerHTML = html`<ul class="small">
    ${line("검색 평가", ev.retrieval, ev.retrieval && html`${ev.retrieval.config} · nDCG@10 ${ndcg}${ev.retrieval.ci ? ` [${ev.retrieval.ci.join(", ")}]` : ""}`)}
    ${line("레드팀", ev.redteam, ev.redteam && html`${ev.redteam.mode} · 공격 방어 ${pct(ev.redteam.attack_pass_rate)}% · 정상 통과 ${pct(ev.redteam.benign_pass_rate)}%`)}
    ${line("대화 평가", ev.conversation, ev.conversation && "후속 질문 · 되묻기 · 메모리")}
    ${line("드리프트", ev.drift, ev.drift && html`경보 ${ev.drift.alerts.length}`)}
    ${ev.pii ? html`<li><b>근거 자료 속 개인정보</b> 문서 ${ev.pii.documents_with_pii}개 ${html.join(Object.entries(ev.pii.counts).map(([k, v]) => html`<span class="badge">${k} ${v}</span>`), " ")}</li>` : ""}</ul>
    <b>자동으로 짚은 것 ${r.findings.length}</b>
    ${r.findings.length ? html`<div class="table-wrap"><table><tr><th>영역</th><th>집단</th><th>내용</th></tr>${html.join(r.findings.map(f => html`<tr><td class="small">${f.area}</td><td class="small">${f.group}</td><td class="small">${f.note}</td></tr>`), "")}</table></div>` : html`<div class="small muted">없음</div>`}`;
}

async function loadList() {
  const rows = await api("/api/compliance/impact");
  const name = k => CAT.profiles.find(p => p.key === k)?.name || k;
  $("#a-list").innerHTML = rows.length ? html`<div class="table-wrap"><table><tr><th>#</th><th>기능</th><th>결론</th><th>짚은 것</th><th>상태</th></tr>
    ${html.join(rows.map(r => html`<tr><td class="small">${r.id}</td><td class="small">${name(r.subject)} <span class="muted">${r.by} · ${r.at.slice(0, 10)}</span></td>
      <td class="small">${DECISION[r.data.decision]}<details><summary>내용</summary><div class="pre small">영향: ${r.data.affected || "-"}\n완화책: ${r.data.mitigations || "-"}</div></details></td>
      <td class="small">${r.data.findings.length}</td>
      <td class="small">${r.status === "approved" ? html`<span class="badge ok">승인 · ${r.reviewed_by}</span>` : html`<span class="badge">초안</span> <button class="btn sm" data-approve="${r.id}">승인</button>`}</td></tr>`), "")}</table></div>` : "";
  $$("[data-approve]", $("#a-list")).forEach(b => b.onclick = async () => {
    if (!(await ui.confirm("이 영향 평가를 승인할까요? 승인한 사람으로 이름이 남습니다.", { ok: "승인" }))) return;
    busy(b, () => api(`/api/compliance/records/${b.dataset.approve}/confirm`, { method: "POST" })).then(loadList).catch(e => toast(e.message, "err"));
  });
}

function renderAudit(r) {
  $("#a-out").innerHTML = html`<div class="row">${html.join(Object.entries(r.counts).map(([k, v]) => html`${badge(k)} ${v}`), " · ")} <span class="small muted">${r.at.slice(0, 19).replace("T", " ")}${r.run_id ? ` · run #${r.run_id}` : ""}</span></div>
    <div class="table-wrap"><table><tr><th>통제</th><th>결과</th><th>증적</th></tr>
    ${html.join(r.rows.map(x => html`<tr><td class="small"><b>${x.name}</b> <span class="muted">${x.kind}</span></td><td>${badge(x.status)}</td>
      <td class="small">${x.detail}${x.evidence ? html`<details><summary>증적</summary><pre class="pre small">${JSON.stringify(x.evidence, null, 1)}</pre></details>` : ""}</td></tr>`), "")}</table></div>`;
}

async function loadRuns() {
  const rows = await api("/api/compliance/audit/runs");
  $("#a-runs").innerHTML = rows.length ? html`<h3>감사 기록</h3><div class="small">${html.join(rows.map(r => html`<div><a href="#" data-run="${r.id}">#${r.id}</a> ${r.at.slice(0, 16).replace("T", " ")} · ${r.reason} —
    ${html.join(Object.entries(r.counts || {}).map(([k, v]) => html`${(STATUS[k] || ["", k])[1]} ${v}`), " · ")}</div>`), "")}</div>` : "";
  $$("[data-run]", $("#a-runs")).forEach(a => a.onclick = ev => { ev.preventDefault(); api(`/api/compliance/audit/runs/${a.dataset.run}`).then(renderAudit).catch(e => toast(e.message, "err")); });
}

$("#a-draft").onclick = e => busy(e.target, () => api(`/api/compliance/impact/draft${$("#a-col").value ? `?collection_id=${$("#a-col").value}` : ""}`))
  .then(renderEvidence).catch(err => ui.error($("#a-evidence"), err));
$("#a-save").onclick = e => busy(e.target, () => api("/api/compliance/impact", { method: "POST", body: {
  profile: $("#a-profile").value, collection_id: +$("#a-col").value || null, affected: $("#a-affected").value, mitigations: $("#a-mitig").value, decision: $("#a-decision").value } }))
  .then(() => { toast("초안을 저장했습니다 — 측정 기록은 저장 순간의 값으로 남습니다"); loadList(); }).catch(err => toast(err.message, "err"));
$("#a-run").onclick = e => busy(e.target, () => api("/api/compliance/audit/run", { method: "POST" })).then(r => { renderAudit(r); loadRuns(); }).catch(err => ui.error($("#a-out"), err));

(async () => {
  CAT = await api("/api/compliance/catalog");
  $("#a-profile").innerHTML = html`${CAT.profiles.map(p => html`<option value="${p.key}">${p.name}</option>`)}`;
  await setupCollectionPickers({ col: $("#a-col") });
  loadList().catch(e => ui.error($("#a-list"), e));
  loadRuns().catch(() => {});
})().catch(e => ui.error($("#a-evidence"), e));
