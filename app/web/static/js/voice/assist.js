// voice/assist.html 화면 스크립트 — 상담원 보조: 고객 말마다 근거 · 추천 답 · 확인할 질문, 채택 · 고쳐서 씀 · 무시(VC6), 통화 요약 · 검증 · 티켓(VC7)
const FB = { adopted: "채택", edited: "고쳐서 씀", ignored: "무시" };
const FIELD = { inquiry: "문의", product_model: "제품", codes: "코드", diagnosis: "진단", actions: "안내한 조치", resolved: "해결", promise: "약속", next: "다음 할 일" };
let CALL = null, CFG = null;
const llmBody = () => ({ provider: $("#a-provider").value || null, model: $("#a-model").value.trim() || null });

function addLine(role, text, extra = "") {
  $("#a-turns").insertAdjacentHTML("beforeend", html`<div><b>${role === "customer" ? "고객" : "상담원"}</b> ${text} ${extra}</div>`);
}

async function suggest(n) {
  const box = document.createElement("div");
  box.className = "card p-2 stack";
  box.innerHTML = html`<div class="small muted">고객 턴 ${n} · 찾는 중…</div>`;
  $("#a-sugg").prepend(box);
  const resp = await fetch(`/api/voice/calls/${CALL.id}/respond`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ turn: n, ...llmBody() }) });
  if (!resp.ok) { box.innerHTML = html`<span class="badge err">${(await resp.json()).detail || "실패"}</span>`; return; }
  await readLines(resp, ev => {
    if (ev.type === "triage") box.innerHTML = html`<div class="row small">${ev.intent ? html`<span class="badge">${ev.intent}</span>` : ""}${ev.urgency !== "normal" ? html`<span class="badge err">${ev.urgency}</span>` : ""}
      ${ev.codes.length ? html`<span class="badge">코드 ${ev.codes.join(", ")}</span>` : ""}<span class="badge ${EMO(ev.emotion.score)}">감정 ${ev.emotion.score}</span>${ev.emotion.escalate ? html`<span class="badge err">이관 권장 · ${ev.emotion.reasons.join(", ")}</span>` : ""}</div>`;
    else if (ev.type === "evidence") box.insertAdjacentHTML("beforeend", html`<div class="small">근거 ${ev.ms}ms<ol>${html.join(ev.sources.map(s => html`<li>${s.filename}${s.heading ? ` · ${s.heading}` : ""} — ${(s.text || "").slice(0, 110)}</li>`), "")}</ol></div>
      ${ev.questions.length ? html`<div class="small"><b>확인할 것</b><ul>${html.join(ev.questions.map(q => html`<li>${q}</li>`), "")}</ul></div>` : ""}`);
    else if (ev.type === "error") toast(ev.message, "err");
    else if (ev.type === "suggestion") {
      if (!ev.reply) return box.insertAdjacentHTML("beforeend", html`<div class="small muted">추천 답 없음(모델 없음 · 근거 없음) — 근거를 보고 답하세요.</div>`);
      box.insertAdjacentHTML("beforeend", html`<div class="stack"><div class="small muted">추천 답 · ${ev.reply_ms}ms${ev.verify ? ` · 근거 일치 ${ev.verify.supported_ratio ?? "-"}` : ""}</div>
        <textarea rows="3" data-reply>${ev.reply}</textarea>
        <div class="row">${html.join(Object.entries(FB).map(([k, v]) => html`<button class="btn sm${k === "adopted" ? " primary" : ""}" data-fb="${k}">${v}</button>`), " ")}</div></div>`);
      $$("[data-fb]", box).forEach(b => b.onclick = () => feedback(ev.n, b.dataset.fb, box, ev.reply));
    }
  });
}

function feedback(n, action, box, original) {
  const text = $("[data-reply]", box).value;
  const act = action === "adopted" && text !== original ? "edited" : action;  // 고친 뒤 '채택'을 누르면 고쳐서 쓴 것
  api(`/api/voice/calls/${CALL.id}/suggestions/${n}/feedback`, { method: "POST", body: { action: act, text: act === "edited" ? text : "" } })
    .then(r => {
      $$("[data-fb]", box).forEach(b => { b.disabled = true; });
      box.insertAdjacentHTML("beforeend", html`<span class="badge ok">${FB[act]}</span>`);
      if (act !== "ignored") addLine("agent", act === "edited" ? text : original);
      showAdoption(r.adoption);
    }).catch(err => toast(err.message, "err"));
}

function showAdoption(a) {
  $("#a-adopt").textContent = a.rated ? `채택 ${Math.round(a.adopted * 100)}% · 고쳐서 씀 ${Math.round(a.edited * 100)}% · 무시 ${Math.round(a.ignored * 100)}% (평가 ${a.rated}/${a.n})` : "";
}

function onEvents(evs) {
  for (const ev of evs) {
    if (ev.type === "partial") $("#a-partial").textContent = `… ${ev.text}`;
    else if (ev.type === "final") { $("#a-partial").textContent = ""; addLine("customer", ev.text); suggest(ev.turn); }
    else if (ev.type === "error") toast(ev.message, "err");
  }
}

const LIVE = ["#a-mic", "#a-cust", "#a-cust-say", "#a-agent", "#a-agent-say", "#s-end"];
$("#a-start").onclick = e => busy(e.target, () => api("/api/voice/calls", { method: "POST", body: { collection_id: +$("#a-col").value, mode: "assist", product_model: $("#a-pm").value.trim() } }))
  .then(c => { CALL = c; $("#a-turns").innerHTML = ""; $("#a-sugg").innerHTML = ""; $("#s-out").innerHTML = ""; $("#a-status").textContent = `통화 ${c.id}`; LIVE.forEach(s => { $(s).disabled = false; }); })
  .catch(err => toast(err.message, "err"));

$("#a-mic").onclick = async e => {
  if (VoiceLine.stream) { VoiceLine.stop(); e.target.textContent = "고객 마이크 켜기"; return; }
  try { await VoiceLine.start(CALL.id, CFG.params, onEvents, null); e.target.textContent = "마이크 끄기"; }
  catch (err) { toast(`마이크를 쓸 수 없습니다: ${err.message}`, "err"); }
};

$("#a-cust-say").onclick = e => busy(e.target, () => api(`/api/voice/calls/${CALL.id}/say`, { method: "POST", body: { text: $("#a-cust").value, role: "customer" } }))
  .then(r => { addLine("customer", r.turn.text); return suggest(r.turn.n); }).catch(err => toast(err.message, "err"));
$("#a-agent-say").onclick = e => busy(e.target, () => api(`/api/voice/calls/${CALL.id}/say`, { method: "POST", body: { text: $("#a-agent").value, role: "agent" } }))
  .then(r => { addLine("agent", r.turn.text); $("#a-agent").value = ""; }).catch(err => toast(err.message, "err"));

function summaryHtml(c) {
  const s = c.summary?.summary, v = c.summary?.verify;
  if (!s) return html`<p class="small muted">요약 없음</p>`;
  const bad = new Set((v?.checks || []).filter(x => !x.ok).map(x => `${x.field}|${x.value}`));
  const val = (k, x) => html`<span class="${bad.has(`${k}|${x}`) ? "badge warn" : ""}">${String(x)}</span>`;
  return html`<div class="table-wrap"><table>${html.join(Object.entries(FIELD).map(([k, label]) => html`<tr><th>${label}</th><td>${Array.isArray(s[k]) ? html.join(s[k].map(x => val(k, x)), " · ") : val(k, s[k] ?? "")}</td></tr>`), "")}</table></div>
    <div class="small">${s.by === "llm" ? "LLM 요약" : "규칙 요약"} · 검증 ${v.n - v.n_bad}/${v.n} ${v.ok ? html`<span class="badge ok">전사와 일치</span>` : html`<span class="badge warn">확인 필요 ${v.n_bad}</span>`}
    ${c.summary.ticket ? html` · 티켓 <span class="mono">${c.summary.ticket.id}</span>` : ""}</div>`;
}

$("#s-end").onclick = e => busy(e.target, () => api(`/api/voice/calls/${CALL.id}/end`, { method: "POST", body: { summarize: true, ticket: $("#s-ticket").checked || null, ...llmBody() } }))
  .then(c => { VoiceLine.stop(); LIVE.forEach(s => { $(s).disabled = true; }); $("#s-out").innerHTML = summaryHtml(c); loadCalls(); })
  .catch(err => ui.error($("#s-out"), err));

async function loadCalls() {
  const r = await api("/api/voice/calls?limit=15");
  $("#s-calls").innerHTML = r.calls.length ? html`<div class="table-wrap"><table><tr><th>통화</th><th>방식</th><th>상태</th><th>턴</th><th>시작</th><th></th></tr>
    ${html.join(r.calls.map(c => html`<tr><td class="mono small">${c.id}</td><td>${c.mode === "assist" ? "상담원 보조" : "자동 응답"}</td><td>${c.status}</td><td>${c.n_turns}</td><td class="small">${c.created_at.slice(0, 16).replace("T", " ")}</td>
      <td><button class="btn sm" data-show="${c.id}">요약</button> <button class="btn sm danger" data-del="${c.id}">삭제</button></td></tr>`), "")}</table></div>` : html`<p class="small muted">통화 기록 없음</p>`;
}

$("#s-calls").addEventListener("click", async e => {
  const s = e.target.closest("[data-show]"), d = e.target.closest("[data-del]");
  if (s) api(`/api/voice/calls/${s.dataset.show}`).then(c => { $("#s-out").innerHTML = summaryHtml(c); }).catch(err => toast(err.message, "err"));
  if (d && (await ui.confirm(`통화 ${d.dataset.del} 기록을 지울까요?`))) api(`/api/voice/calls/${d.dataset.del}`, { method: "DELETE" }).then(loadCalls).catch(err => toast(err.message, "err"));
});

(async () => {
  CFG = await api("/api/voice/config");
  await setupCollectionPickers({ col: $("#a-col") });
  await loadCalls();
})().catch(e => ui.error($("#s-calls"), e));
