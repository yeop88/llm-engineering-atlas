// as/tickets.html 화면 스크립트 — AS7 티켓 처리 · AS8 지표
const TST = { open: ["warn", "접수"], in_progress: ["", "처리 중"], done: ["ok", "완료"] };
const URG = { safety: ["err", "안전"], high: ["warn", "높음"], normal: ["", "보통"] };
const tBadge = (map, k) => (k && map[k] ? html`<span class="badge ${map[k][0]}">${map[k][1]}</span>` : html`<span class="badge muted">${k || "-"}</span>`);
const ratio = v => (v == null ? "-" : `${pct(v)}%`);
let rows = [], selected = null;

async function loadMetrics() {
  const box = $("#m-out");
  ui.loading(box);
  try {
    const m = await api(`/api/as/metrics?days=${$("#m-days").value}`);
    if (!m.n) return ui.empty(box, `최근 ${m.days}일 동안 상담이 없습니다.`, { href: "/as/console", label: "상담 창 열기" });
    box.innerHTML = html`<div class="grid cols-4">
        <div class="stat"><div class="value">${fmtNum(m.n)}</div><div class="label">상담 수</div></div>
        <div class="stat"><div class="value">${ratio(m.resolution_rate)}</div><div class="label">해결률 (해결 응답 ÷ 응답한 상담 ${m.n_feedback}건)</div></div>
        <div class="stat"><div class="value">${ratio(m.handoff_rate)}</div><div class="label">이관률 (상담원에게 넘긴 상담 ÷ 전체)</div></div>
        <div class="stat"><div class="value">${m.satisfaction ?? "-"}</div><div class="label">만족도 (1~5 평균)</div></div></div>
      <div class="table-wrap mt-4"><table><thead><tr><th>의도</th><th class="num">상담</th><th class="num">해결</th><th class="num">이관</th><th class="num">이관률</th></tr></thead>
        <tbody>${m.by_intent.map(r => html`<tr><td>${r.intent}</td><td class="num">${r.n}</td><td class="num">${r.resolved || 0}</td><td class="num">${r.handoff || 0}</td><td class="num">${ratio((r.handoff || 0) / r.n)}</td></tr>`)}</tbody></table></div>`;
  } catch (e) { ui.error(box, e); }
}
$("#m-days").onchange = loadMetrics;

async function loadTickets() {
  const box = $("#t-list");
  ui.loading(box);
  try {
    const st = $("#t-status").value;
    rows = await api(`/api/as/tickets${st ? `?status=${st}` : ""}`);
    if (!rows.length) return ui.empty(box, st ? "이 상태의 티켓이 없습니다." : "티켓이 없습니다. 상담 창에서 '해결 안 됨'을 누르거나 안전 문의를 넣으면 생깁니다.");
    box.innerHTML = html`<div class="table-wrap scroll-lg"><table><thead><tr><th>접수 번호</th><th>고객 · 모델</th><th>사유</th><th>긴급도</th><th>상태</th></tr></thead>
      <tbody>${rows.map(s => html`<tr data-sid="${s.id}" class="${selected === s.id ? "best" : ""}"><td><a href="#${s.id}" data-sid="${s.id}">${s.ticket.id}</a><div class="small muted">${fmtDate(s.ticket.created_at)}</div></td>
        <td>${s.customer || "(이름 없음)"}<div class="small muted">${s.product_model || "모델 모름"} · ${s.intent || "-"}</div></td>
        <td class="small">${s.ticket.reason}</td><td>${tBadge(URG, s.urgency)}</td><td>${tBadge(TST, s.ticket.status)}</td></tr>`)}</tbody></table></div>`;
  } catch (e) { ui.error(box, e); }
}
$("#t-status").onchange = loadTickets;
$("#t-list").addEventListener("click", e => {
  const el = e.target.closest("[data-sid]");
  if (!el) return;
  e.preventDefault();
  showDetail(el.dataset.sid);
});

function showDetail(sid) {
  const s = rows.find(r => r.id === sid);
  const box = $("#t-detail");
  if (!s) return ui.empty(box, "티켓을 찾을 수 없습니다.");
  selected = sid;
  const t = s.ticket, d = t.delivered || {};
  box.innerHTML = html`<div class="row between"><h2 class="m-0">${t.id}</h2>${tBadge(TST, t.status)}</div>
    <div class="kv">
      <div>사유</div><div>${t.reason}</div>
      <div>고객</div><div>${t.customer || "(이름 없음)"}</div>
      <div>제품 모델</div><div>${t.product_model || "모름"}</div>
      <div>의도 · 긴급도</div><div>${t.intent || "-"} ${tBadge(URG, t.urgency)}</div>
      <div>오류 코드</div><div>${html.or(html.join((t.codes || []).map(c => html`<span class="badge muted">${c}</span>`), " "), html`<span class="muted">없음</span>`)}</div>
      <div>사진</div><div>${t.photos || 0}장</div>
      <div>전달</div><div>${d.to === "local" ? "이 앱에만 기록 (AS_TICKET_WEBHOOK 미설정)" : html`${d.to} ${d.error ? html`<span class="badge err">${d.error}</span>` : html`<span class="badge ${d.status < 300 ? "ok" : "warn"}">HTTP ${d.status}</span>`}`}</div>
      <div>접수 시각</div><div>${fmtDate(t.created_at)}</div>
    </div>
    <div><b class="small">증상 (고객이 말한 것, 최근 5개)</b>${html.or(html.join((t.symptoms || []).map(x => html`<div class="q-bubble mt-1 pre">${x}</div>`), ""), html`<div class="small muted">없음</div>`)}</div>
    <div><b class="small">이미 안내한 조치</b>${html.or(html.join((t.tried || []).map(x => html`<div class="small">${x}</div>`), ""), html`<div class="small muted">안내한 단계 없음</div>`)}</div>
    ${t.note ? html`<div class="small">처리 메모: <span class="pre">${t.note}</span></div>` : ""}
    <div class="row">
      <div class="field"><label for="t-new-status">상태 바꾸기</label><select id="t-new-status" class="w-xl">${Object.entries(TST).map(([k, [, label]]) => html`<option value="${k}"${k === t.status ? raw(" selected") : ""}>${label}</option>`)}</select></div>
      <div class="field grow"><label for="t-note">메모</label><input id="t-note" maxlength="1000" value="${t.note || ""}" placeholder="예: 3일 방문 예약"></div>
      <div class="self-end"><button class="btn primary" id="t-save">저장</button></div>
    </div>
    <div class="small"><a href="/as/console?sid=${s.id}">상담 창에서 대화 보기</a></div>`;
  $("#t-save").onclick = async e => {
    const status = $("#t-new-status").value;
    // 완료로 바꾸면 상담이 '종료'로 닫힌다 — 실수로 누르지 않게 한 번 묻는다
    if (status === "done" && t.status !== "done" && !(await ui.confirm(`티켓 ${t.id} 을 완료로 바꾸고 상담을 종료할까요?`, { ok: "완료 처리" }))) return;
    const updated = await busy(e.target, () => api(`/api/as/tickets/${s.id}`, { method: "PATCH", body: { status, note: $("#t-note").value.trim() } }));
    toast("티켓을 저장했습니다", "ok");
    Object.assign(s, updated);
    await loadTickets();
    if (rows.some(r => r.id === sid)) showDetail(sid);
    else ui.empty(box, "저장했습니다. 지금 상태 걸러보기에서는 이 티켓이 보이지 않습니다.");
    loadMetrics();
  };
}

loadMetrics();
loadTickets().then(() => { if (location.hash) showDetail(location.hash.slice(1)); });
