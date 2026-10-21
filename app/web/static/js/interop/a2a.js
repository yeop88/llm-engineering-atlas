// interop/a2a.html 화면 스크립트 — 상대 에이전트 카드, 작업 맡기기 · 결과 검증(IO3), 받은 · 맡긴 작업 목록(IO4)
const STATE = { submitted: ["", "접수"], working: ["warn", "진행"], completed: ["ok", "완료"], failed: ["err", "실패"], canceled: ["", "취소"], rejected: ["err", "거절"] };
const st = s => html`<span class="badge ${(STATE[s] || ["", s])[0]}">${(STATE[s] || ["", s])[1]}</span>`;

function renderTask(t) {
  const o = t.output || {};
  const v = o.verify;
  return html`<div class="card stack mt-2"><div class="row">${st(t.status)} <b>${t.skill}</b> <span class="small muted">${t.direction === "out" ? "→" : "←"} ${t.peer} · 시도 ${t.attempts} · 추적 <a class="mono" href="/interop/audit?trace=${t.trace_key}">${t.trace_key}</a></span>
      ${t.direction === "out" && t.status === "completed" ? (o.accepted ? html`<span class="badge ok">받아들임</span>` : html`<span class="badge err">받아들이지 않음</span>`) : ""}</div>
    ${t.error ? html`<div class="errbox small" role="alert">${t.error}</div>` : ""}
    ${o.text ? html`<div class="pre small">${o.text}</div>` : ""}
    <div class="small muted">${v ? `우리 자료로 근거 일치 ${v.supported_ratio ?? "-"}` : t.direction === "out" ? "검증 안 함(컬렉션 없음)" : ""}${o.flags?.length ? ` · 지시 문장 ${o.flags.length}개 뺌` : ""}${o.data ? ` · data ${JSON.stringify(o.data).slice(0, 200)}` : ""}</div></div>`;
}

async function loadTasks() {
  const rows = await api(`/api/interop/tasks${$("#a-dir").value ? `?direction=${$("#a-dir").value}` : ""}`);
  $("#a-tasks").innerHTML = rows.length ? html`<div class="table-wrap"><table><tr><th>작업</th><th>방향</th><th>상태</th><th>기술</th><th>상대</th><th>시도</th><th>때</th></tr>
    ${html.join(rows.map(t => html`<tr><td class="small mono"><a href="#" data-task="${t.id}">${t.id}</a></td><td class="small">${t.direction === "out" ? "맡김" : "받음"}</td><td>${st(t.status)}</td>
      <td class="small">${t.skill}</td><td class="small">${t.peer}</td><td class="small">${t.attempts}</td><td class="small nowrap">${t.at.slice(0, 16).replace("T", " ")}</td></tr>`), "")}</table></div><div id="a-task-detail"></div>`
    : html`<div class="small muted">작업이 없습니다.</div>`;
  $$("[data-task]", $("#a-tasks")).forEach(a => a.onclick = ev => { ev.preventDefault(); $("#a-task-detail").innerHTML = renderTask(rows.find(t => t.id === a.dataset.task)); });
}

$("#a-card").onclick = e => busy(e.target, () => api("/api/interop/a2a/card", { method: "POST", body: { url: $("#a-url").value.trim(), token: $("#a-token").value || null } }))
  .then(c => {
    $("#a-card-out").innerHTML = html`<div><b>${c.name}</b> <span class="small muted">${c.description} · 규격 ${c.protocolVersion} · ${c.preferredTransport} · <span class="mono">${c.url}</span></span></div>
      <ul class="small">${html.join((c.skills || []).map(s => html`<li><b class="mono">${s.id}</b> ${s.name} — ${s.description}</li>`), "")}</ul>`;
    const sel = $("#a-skill");
    if (c.skills?.length) sel.innerHTML = html`${c.skills.map(s => html`<option value="${s.id}">${s.id} — ${s.name}</option>`)}`;
  }).catch(err => ui.error($("#a-card-out"), err));
$("#a-send").onclick = e => {
  let meta = {};
  try { meta = $("#a-meta").value.trim() ? JSON.parse($("#a-meta").value) : {}; } catch { return toast("metadata 는 JSON 이어야 합니다", "err"); }
  if (!$("#a-text").value.trim()) return toast("맡길 일을 적으세요", "err");
  runJobInto(e.target, "/api/interop/a2a/delegate", { url: $("#a-url").value.trim(), token: $("#a-token").value || null, skill: $("#a-skill").value,
    text: $("#a-text").value.trim(), metadata: meta, verify_collection_id: +$("#a-verify").value || null }, $("#a-progress"), t => { $("#a-out").innerHTML = renderTask(t); loadTasks(); })
    .catch(err => toast(err.message, "err"));
};
$("#a-dir").addEventListener("change", () => loadTasks().catch(e => ui.error($("#a-tasks"), e)));

(async () => {
  const s = await api("/api/interop/servers");
  const self = s.self.a2a.replace(/\/a2a$/, "");
  $("#a-peers").innerHTML = html`<option value="${self}">이 앱</option>${s.a2a_peers.map(p => html`<option value="${p.url}">${p.name || p.url}</option>`)}`;
  if (!$("#a-url").value) $("#a-url").value = self;
  await setupCollectionPickers({ col: $("#a-verify") });
  loadTasks().catch(e => ui.error($("#a-tasks"), e));
})().catch(e => ui.error($("#a-tasks"), e));
