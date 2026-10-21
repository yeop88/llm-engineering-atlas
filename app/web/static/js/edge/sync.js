// edge/sync.html 화면 스크립트 — 기기 등록 · 버전 관리 · 증분 동기화(ED5), 전송 정책 · 서버 재검사(ED6), 미룬 요청 처리(ED4)
const RULE = { raw: "원문", masked: "가림", stats: "집계만", never: "보내지 않음" };
const SAMPLE = [
  { kind: "feedback", payload: { question: "WM-200 E3 오류인데 고객 김민수 010-1234-5678 댁 배수가 안 돼요", rating: 2, feedback: "답이 다른 모델 기준이었음" } },
  { kind: "log", payload: { usage: "검색 12회 · 답변 5회", device_log: "배터리 41%" } },
  { kind: "feedback", payload: { customer: "이영희 / 서울시 강남구 테헤란로 1", photo: "IMG_0042.jpg", label: "배수 펌프 막힘" } },
];
let POLICY = {};
const mb = b => `${(b / 2 ** 20).toFixed(2)}MB`;
const kb = b => `${(b / 1024).toFixed(1)}KB`;

async function loadDevices() {
  const r = await api("/api/edge/devices");
  $("#d-summary").textContent = `기기 ${r.summary.n} · 판 뒤처짐 ${r.summary.behind} · 확인 필요 ${r.summary.stale} (기준 ${r.stale_hours}시간)`;
  $("#d-list").innerHTML = r.devices.length ? html`<div class="table-wrap"><table><tr><th>기기</th><th>프로필</th><th>팩 · 판</th><th>마지막 동기화</th><th>대기열</th><th>개인정보 위반</th><th>상태</th><th></th></tr>
    ${html.join(r.devices.map(d => html`<tr><td><span class="mono small">${d.id}</span> ${d.name}</td><td class="small">${d.profile}</td><td class="small">${d.pack || "-"} v${d.version}${d.latest ? ` / 최신 v${d.latest}` : ""}</td>
      <td class="small">${d.last_sync ? `${d.age_hours}시간 전` : "-"}</td><td>${d.queued}</td><td>${d.pii_flags ? html`<span class="badge err">${d.pii_flags}</span>` : "0"}</td>
      <td>${d.ok ? html`<span class="badge ok">최신</span>` : html.join(d.flags.map(f => html`<span class="badge warn">${f}</span>`), " ")}</td>
      <td class="nowrap"><button class="btn sm primary" data-sync="${d.id}">동기화</button> <button class="btn sm danger" data-del="${d.id}">삭제</button></td></tr>`), "")}</table></div>` : html`<p class="small muted">등록한 기기가 없습니다.</p>`;
  $("#u-device").innerHTML = html`${r.devices.map(d => html`<option value="${d.id}">${d.id} · ${d.name}</option>`)}`;
}

function deltaHtml(x) {
  return html`<div class="small"><b>${x.name}</b> ${x.from ? `v${x.from}` : "(없음)"} → v${x.to} · <span class="badge">${x.mode === "full" ? "전체" : "증분"}</span>
    ${x.verified ? html`<span class="badge ok">지문 일치 ${x.hash}</span>` : html`<span class="badge err">지문 불일치</span>`}</div>
    ${x.reason ? html`<div class="small muted">${x.reason}</div>` : ""}
    <div class="small">보낼 청크 ${x.send_chunks}${x.remove_chunk_ids ? ` · 지울 청크 ${x.remove_chunk_ids.length}` : ""} · 크기 ${kb(x.bytes)} / 전체 ${mb(x.full_bytes)}
      ${x.mode === "delta" ? html` (${((x.bytes / x.full_bytes) * 100).toFixed(1)}%) · 새 문서 ${x.added_docs.length} · 바뀐 문서 ${x.changed_docs.length} · 빠진 문서 ${x.removed_docs.length}` : ""}</div>`;
}

$("#d-list").addEventListener("click", async e => {
  const s = e.target.closest("[data-sync]"), d = e.target.closest("[data-del]");
  if (s) busy(s, () => api(`/api/edge/devices/${s.dataset.sync}/sync`, { method: "POST", body: {} }))
    .then(r => { $("#d-out").innerHTML = html`${deltaHtml(r.delta)}<div class="small muted">대기열 ${r.queued}개 — 아래 '올리기'로 보냅니다.</div>`; loadDevices(); })
    .catch(err => ui.error($("#d-out"), err));
  if (d && (await ui.confirm(`기기 ${d.dataset.del} 와 그 기록을 지울까요?`)))
    api(`/api/edge/devices/${d.dataset.del}`, { method: "DELETE" }).then(loadDevices).catch(err => toast(err.message, "err"));
});

$("#d-add").onclick = e => busy(e.target, () => api("/api/edge/devices", { method: "POST", body: { id: $("#d-id").value.trim(), name: $("#d-name").value.trim(), profile: $("#d-profile").value, pack: $("#d-pack").value } }))
  .then(loadDevices).catch(err => ui.error($("#d-out"), err));

$("#x-run").onclick = e => {
  const q = new URLSearchParams();
  if (+$("#x-from").value) q.set("from_version", $("#x-from").value);
  if (+$("#x-to").value) q.set("to_version", $("#x-to").value);
  busy(e.target, () => api(`/api/edge/packs/${$("#x-pack").value}/delta?${q}`)).then(x => { $("#x-out").innerHTML = deltaHtml(x); }).catch(err => ui.error($("#x-out"), err));
};

function policy() { return Object.fromEntries($$("[data-rule]").map(s => [s.dataset.rule, s.value])); }
function events() { return JSON.parse($("#u-events").value || "[]"); }
function reportHtml(rep, stats) {
  const masked = Object.entries(rep.masked || {});
  return html`<div class="small">기기에서 가림: ${masked.length ? html.join(masked.map(([t, n]) => html`<span class="badge">${t} ${n}</span>`), " ") : "없음"} · 뺀 항목: ${(rep.dropped || []).join(", ") || "없음"}
    ${Object.keys(stats || {}).length ? ` · 집계만: ${Object.entries(stats).map(([k, v]) => `${k} ${v.n}건`).join(", ")}` : ""}</div>`;
}

$("#u-preview").onclick = e => busy(e.target, () => api("/api/edge/privacy/preview", { method: "POST", body: { events: events(), policy: policy() } }))
  .then(r => {
    $("#u-out").innerHTML = html`${reportHtml(r.report, r.stats)}<div class="table-wrap"><table><tr><th>보낼 값</th><th>서버 재검사</th></tr>
      ${html.join(r.events.map((ev, i) => html`<tr><td class="small mono pre">${JSON.stringify(ev.payload, null, 1)}</td>
        <td class="small">${r.server_check[i].violations.length ? html.join(r.server_check[i].violations.map(v => html`<div><span class="badge err">${v.type}</span> ${v.field}</div>`), "") : html`<span class="badge ok">통과</span>`}</td></tr>`), "")}</table></div>`;
  }).catch(err => ui.error($("#u-out"), err));

$("#u-send").onclick = e => busy(e.target, () => api(`/api/edge/devices/${$("#u-device").value}/upload`, { method: "POST", body: { events: events(), policy: policy(), prepare: $("#u-prepare").checked, include_queued: $("#u-queued").checked } }))
  .then(r => {
    $("#u-out").innerHTML = html`<div class="small">저장 ${r.stored}건 · 미룬 요청 ${r.deferred} · 서버가 찾은 위반 ${r.violations ? html`<span class="badge err">${r.violations}</span> — 가린 값만 저장, 기기에 표시` : html`<span class="badge ok">0</span>`}</div>${reportHtml(r.report || {}, r.stats)}`;
    loadDevices(); loadEvents();
  }).catch(err => ui.error($("#u-out"), err));

async function loadEvents() {
  const r = await api("/api/edge/events?limit=50");
  $("#v-list").innerHTML = r.events.length ? html`<div class="table-wrap"><table><tr><th>#</th><th>기기</th><th>종류</th><th>상태</th><th>내용</th><th>결과</th><th>위반</th></tr>
    ${html.join(r.events.map(ev => html`<tr><td>${ev.id}</td><td class="mono small">${ev.device_id}</td><td>${ev.kind}</td><td><span class="badge">${ev.status}</span></td>
      <td class="small">${JSON.stringify(ev.payload).slice(0, 160)}</td><td class="small">${(ev.result.answer || ev.result.note || ev.result.error || "").slice(0, 160)}</td>
      <td>${ev.violations.length ? html`<span class="badge err">${ev.violations.length}</span>` : ""}</td></tr>`), "")}</table></div>` : html`<p class="small muted">올라온 기록이 없습니다.</p>`;
}

$("#v-reload").onclick = () => loadEvents().catch(err => ui.error($("#v-list"), err));
$("#v-process").onclick = e => runJobInto(e.target, "/api/edge/events/process", { provider: $("#v-provider").value || null, model: $("#v-model").value.trim() || null }, $("#v-progress"),
  () => loadEvents()).catch(err => ui.error($("#v-list"), err));

(async () => {
  const [pr, ov, pv] = await Promise.all([api("/api/edge/profiles"), api("/api/edge/overview"), api("/api/edge/privacy/preview", { method: "POST", body: { events: [] } })]);
  $("#d-profile").innerHTML = html`${Object.entries(pr.profiles).map(([k, p]) => html`<option value="${k}" ${k === "tablet" ? "selected" : ""}>${p.label}</option>`)}`;
  const packs = html`${ov.packs.map(p => html`<option>${p.name}</option>`)}`;
  $("#d-pack").innerHTML = packs;
  $("#x-pack").innerHTML = packs;
  POLICY = pv.policy;
  $("#u-policy").innerHTML = html`${Object.entries(POLICY).map(([k, v]) => html`<div class="field"><label for="rule-${k}">${k}</label><select id="rule-${k}" data-rule="${k}">
    ${pv.rules.map(r => html`<option value="${r}" ${r === v ? "selected" : ""}>${RULE[r]}</option>`)}</select></div>`)}`;
  $("#u-events").value = JSON.stringify(SAMPLE, null, 1);
  await Promise.all([loadDevices(), loadEvents()]);
})().catch(e => ui.error($("#d-list"), e));
