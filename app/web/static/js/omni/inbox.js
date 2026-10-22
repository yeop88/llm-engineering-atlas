// omni/inbox.html 화면 스크립트 — 채널 흉내로 보내기 · 재전송(OM1 · OM6), 고객 세션 · 넘김 요약(OM5), 대기열 훈련(OM6)
let CH = {};
let last = null; // 마지막으로 보낸 요청(재전송 시험에 같은 외부 id 로 다시)
const label = c => CH[c]?.label || c;
const STATUS = { processed: ["ok", "처리"], sent: ["ok", "보냄"], received: ["warn", "대기"], failed: ["err", "실패"], duplicate: ["", "중복"] };
const llmRef = () => ({ provider: $("#s-provider").value || null, model: $("#s-model").value.trim() || null });

function replyHtml(r) {
  if (!r.reply) return html`<div class="small muted">${r.error ? `처리 실패(다시 시도 대기): ${r.error}` : "답 없음(글이 없는 메시지)"}</div>`;
  const rp = r.reply;
  return html`<div class="pre">${rp.text}</div>
    ${rp.buttons?.length ? html`<div class="row">${rp.buttons.map(b => html`<span class="badge">${b}</span>`)}</div>` : ""}
    ${rp.spoken ? html`<div class="small"><b>읽는 글</b> ${rp.spoken}</div>` : ""}
    <div class="small muted">${rp.chars}자${rp.truncated ? " · 줄임" : ""}${Object.keys(rp.masked || {}).length ? ` · 가림 ${Object.entries(rp.masked).map(([k, v]) => `${k} ${v}`).join(", ")}` : ""}</div>
    ${ui.aiNotice(r.notice, r.trace_id)}`;
}

async function send(again) {
  const f = $("#s-image").files[0];
  const image_b64 = f && !again ? await new Promise(res => { const rd = new FileReader(); rd.onload = () => res(rd.result); rd.readAsDataURL(f); }) : last?.image_b64 || null;
  const body = again ? last : { channel: $("#s-channel").value, address: $("#s-address").value.trim(), text: $("#s-text").value, collection_id: +$("#s-col").value || null,
    verified_phone: $("#s-phone").value.trim() || null, external_id: `ui-${Date.now()}`, image_b64, ...llmRef() };
  last = body;
  $("#s-again").disabled = false;
  const r = await api("/api/omni/send", { method: "POST", body });
  $("#s-out").innerHTML = html`<div class="row small">
      ${r.duplicate ? html`<span class="badge warn">중복 — 처리 · 답하지 않음</span>` : html`<span class="badge ok">새 메시지</span>`}
      <span>고객 <b>${r.customer}</b> (${{ known: "아는 주소", phone: "같은 전화번호로 찾음", new: "새 고객" }[r.identified]})</span>
      <span>${r.same_session ? "기존 세션에 이어짐" : "새 세션"} · #${r.session_id}</span><span class="muted">${r.seconds}초</span>
      ${r.pointer ? html`<span class="badge">가리킴 ${r.pointer}</span>` : ""}${r.caught_up ? html`<span class="badge warn">밀린 메시지 ${r.caught_up}개 먼저 처리</span>` : ""}</div>
    ${r.fuse?.changed ? html`<div class="small muted">검색 질문: ${r.fuse.query}</div>` : ""}
    ${r.duplicate ? html`<div class="small muted">처음 보낸 답:</div>${r.reply ? html`<div class="pre">${r.reply.text}</div>` : ""}` : replyHtml(r)}`;
  await loadSessions(r.session_id);
}

async function loadSessions(pick) {
  const r = await api("/api/omni/sessions");
  $("#v-session").innerHTML = r.sessions.length ? html`${r.sessions.map(s => html`<option value="${s.id}">${s.customer} · ${s.channels.map(label).join(" → ")} · 장면 ${s.scenes} · #${s.id}</option>`)}`
    : html`<option value="">세션 없음</option>`;
  if (pick) $("#v-session").value = pick;
  if ($("#v-session").value) await show();
}

async function show() {
  const s = await api(`/api/omni/sessions/${$("#v-session").value}`);
  const st = s.stats;
  $("#v-out").innerHTML = html`<div class="small">주소 ${s.identities.map(i => `${label(i.channel)} ${i.address}`).join(" · ")}</div>
    <div class="small muted">받음 ${(st["in:processed"] || 0) + (st["in:received"] || 0) + (st["in:failed"] || 0)} · 중복 ${st["in:duplicate"] || 0} · 늦게 도착 ${st.late || 0} · 보냄 ${st["out:sent"] || 0}</div>
    <div class="table-wrap"><table><tr><th>시각</th><th>채널</th><th></th><th>글</th><th>상태</th></tr>
    ${html.join(s.messages.map(m => html`<tr><td class="small nowrap">${m.at.slice(11, 19)}</td><td><span class="badge">${label(m.channel)}</span></td><td>${m.direction === "in" ? "고객" : "답"}</td>
      <td class="small">${m.text || html`<span class="muted">(${m.kind})</span>`}${m.meta?.late ? html` <span class="badge warn">늦게 도착</span>` : ""}${m.meta?.buttons?.length ? html` <span class="muted">[${m.meta.buttons.join(" | ")}]</span>` : ""}</td>
      <td><span class="badge ${(STATUS[m.status] || [""])[0]}">${(STATUS[m.status] || ["", m.status])[1]}</span>${m.attempts > 1 ? html` <span class="small muted">${m.attempts}회</span>` : ""}</td></tr>`), "")}</table></div>
    ${s.scenes.length ? html`<div class="thumbs">${s.scenes.map(sc => html`<figure><img src="/api/omni/frames/${s.id}/${sc.frame}" alt="${sc.caption || "장면"}" loading="lazy"><figcaption>${sc.t}초 ${sc.code ? html`<b>${sc.code}</b>` : ""} ${sc.caption}</figcaption></figure>`)}</div>` : ""}`;
}

$("#s-send").onclick = e => busy(e.target, () => send(false)).catch(err => ui.error($("#s-out"), err));
$("#s-again").onclick = e => busy(e.target, () => send(true)).catch(err => ui.error($("#s-out"), err));
$("#v-load").onclick = e => busy(e.target, show).catch(err => ui.error($("#v-out"), err));
$("#v-del").onclick = async () => {
  if (!$("#v-session").value || !(await ui.confirm("이 세션의 메시지 · 장면을 모두 지울까요? 이 고객의 마지막 세션이면 채널 주소 연결도 지웁니다."))) return;
  api(`/api/omni/sessions/${$("#v-session").value}`, { method: "DELETE" }).then(() => { $("#v-out").innerHTML = ""; return loadSessions(); }).catch(err => toast(err.message, "err"));
};
$("#h-run").onclick = e => busy(e.target, () => api(`/api/omni/sessions/${$("#v-session").value}/handoff`, { method: "POST", body: { to_channel: $("#h-to").value, ...llmRef() } })).then(b => {
  $("#h-out").innerHTML = html`<div class="pre">${b.greeting}</div>
    <div class="small"><b>요약</b> ${b.summary} <span class="muted">(${b.by === "llm" ? "LLM · 기록과 맞춤" : "규칙"})</span></div>
    ${b.facts ? html`<div class="pre small">${b.facts}</div>` : ""}
    <div class="grid cols-2 small"><div><b>미해결 질문</b><ul>${html.join(b.open_questions.map(q => html`<li>${q}</li>`), "") || html`<li class="muted">없음</li>`}</ul></div>
      <div><b>다음 할 일</b><ul>${html.join(b.next_steps.map(q => html`<li>${q}</li>`), "") || html`<li class="muted">없음</li>`}</ul></div></div>`;
}).catch(err => ui.error($("#h-out"), err));

$("#d-run").onclick = e => busy(e.target, () => api("/api/omni/drill", { method: "POST", body: { n: +$("#d-n").value, dup_rate: +$("#d-dup").value, shuffle: +$("#d-shuffle").value,
  fail_rate: +$("#d-fail").value } })).then(r => {
  $("#d-out").innerHTML = html`<div class="row small"><span class="badge ${r.exactly_once ? "ok" : "err"}">${r.exactly_once ? "한 번만 처리 · 답" : "중복 처리 · 답 있음"}</span>
      <span class="badge ${r.in_order ? "ok" : "err"}">${r.in_order ? "순서 지킴" : "순서 어긋남"}</span></div>
    <div class="table-wrap"><table><tr><th>고유 메시지</th><th>받은 횟수</th><th>중복으로 거름</th><th>처리</th><th>답</th><th>재시도</th><th>끝내 실패</th><th>늦게 도착</th></tr>
      <tr><td>${r.messages}</td><td>${r.received}</td><td>${r.duplicates}</td><td>${r.processed_unique}</td><td>${r.replies}</td><td>${r.retries}</td><td>${r.failed}</td><td>${r.late}</td></tr></table></div>`;
}).catch(err => ui.error($("#d-out"), err));

api("/api/omni/channels").then(r => {
  CH = r.channels;
  const opts = html`${Object.entries(CH).map(([k, v]) => html`<option value="${k}">${v.label} (${v.address})</option>`)}`;
  $("#s-channel").innerHTML = opts;
  $("#h-to").innerHTML = opts;
  $("#h-to").value = "voice";
  return loadSessions();
}).catch(err => ui.error($("#v-out"), err));
setupCollectionPickers({ col: $("#s-col") }).catch(e => ui.error($("#s-out"), e));
