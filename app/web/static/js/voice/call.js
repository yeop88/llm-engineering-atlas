// voice/call.html 화면 스크립트 — 자동 응답 통화: 인식 · 끝점(VC1 · VC2) → 짧은 지연 답 스트리밍 · 문장 단위 재생(VC3 · VC4) · 감정 · 이관(VC5)
const MODE = { rag: "검색 답", cache: "캐시 답", escalate: "상담원 이관", safety: "안전 안내", not_found: "못 찾음 → 이관" };
let CALL = null, CFG = null, BUSY = false;

function turnHtml(t) {
  const who = t.role === "customer" ? "고객" : "상담(자동)";
  const emo = t.emotion ? html` <span class="badge ${EMO(t.emotion.score)}">감정 ${t.emotion.score}${t.emotion.cues?.length ? ` · ${t.emotion.cues.join(", ")}` : ""}</span>` : "";
  const fixes = t.fixes?.length ? html` <span class="small muted">표기 복원 ${t.fixes.map(f => `${f.from}→${f.to}`).join(", ")}</span>` : "";
  return html`<div class="card p-2 stack" id="turn-${t.key}"><div class="row small"><b>${who}</b>${emo}${t.mode ? html` <span class="badge">${MODE[t.mode] || t.mode}</span>` : ""}${fixes}</div>
    <div class="pre" data-text>${t.text || ""}</div><div data-extra class="small muted"></div></div>`;
}

function addTurn(t) { $("#c-turns").insertAdjacentHTML("beforeend", turnHtml(t)); return $(`#turn-${t.key}`); }

async function respond(n) {
  if (BUSY) return;
  BUSY = true;
  VoiceLine.newTurn();
  const box = addTurn({ key: `a${n}`, role: "agent", text: "" });
  try {
    const resp = await fetch(`/api/voice/calls/${CALL.id}/respond`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ turn: n, provider: $("#c-provider").value || null, model: $("#c-model").value.trim() || null }) });
    if (!resp.ok) { toast((await resp.json()).detail || "응답 실패", "err"); return; }
    await readLines(resp, ev => {
      if (ev.type === "sentence") {
        $("[data-text]", box).textContent += (ev.n ? " " : "") + ev.text;
        VoiceLine.say(ev);
      } else if (ev.type === "sources") {
        $("[data-extra]", box).textContent = `근거: ${ev.sources.map(s => s.filename + (s.heading ? ` · ${s.heading}` : "")).join(" / ")}`;
      } else if (ev.type === "error") toast(ev.message, "err");
      else if (ev.type === "done") {
        VoiceLine.setTurn(ev.turn);
        $("[data-extra]", box).insertAdjacentHTML("beforeend", html`<div>${MODE[ev.mode] || ev.mode} · ${ev.seconds}초${ev.verify ? ` · 근거 일치 ${ev.verify.supported_ratio ?? "-"}` : ""}${ev.escalate ? html` <span class="badge err">이관</span>` : ""}</div>${budgetHtml(ev.budget)}`);
        $("#c-last").innerHTML = budgetHtml(ev.budget);
      }
    });
  } finally { BUSY = false; }
}

function onEvents(evs) {
  for (const ev of evs) {
    if (ev.type === "partial") $("#c-partial").textContent = `… ${ev.text} (이어질 말 — 조금 더 기다림)`;
    else if (ev.type === "final") {
      $("#c-partial").textContent = "";
      addTurn({ key: `c${ev.turn}`, role: "customer", text: ev.text, emotion: ev.emotion, fixes: ev.fixes });
      respond(ev.turn);
    } else if (ev.type === "error") toast(ev.message, "err");
  }
}

function onBarge(info) {
  $("#c-partial").textContent = `끼어들기 — ${info.spoken_chars}자까지 읽고 멈춤`;
}

$("#c-start").onclick = e => busy(e.target, () => api("/api/voice/calls", { method: "POST", body: { collection_id: +$("#c-col").value, mode: "auto", product_model: $("#c-pm").value.trim() } }))
  .then(c => {
    CALL = c;
    $("#c-turns").innerHTML = "";
    $("#c-status").textContent = `통화 ${c.id}`;
    ["#c-mic", "#c-end", "#c-text", "#c-say"].forEach(s => { $(s).disabled = false; });
  }).catch(err => toast(err.message, "err"));

$("#c-mic").onclick = async e => {
  if (VoiceLine.stream) { VoiceLine.stop(); e.target.textContent = "마이크 켜기"; return; }
  try { await VoiceLine.start(CALL.id, CFG.params, onEvents, onBarge); e.target.textContent = "마이크 끄기"; }
  catch (err) { toast(`마이크를 쓸 수 없습니다: ${err.message}`, "err"); }
};

$("#c-say").onclick = e => busy(e.target, () => api(`/api/voice/calls/${CALL.id}/say`, { method: "POST", body: { text: $("#c-text").value } }))
  .then(r => { const t = r.turn; addTurn({ key: `c${t.n}`, role: "customer", text: t.text, emotion: t.emotion, fixes: t.stt?.fixes }); return respond(t.n); })
  .catch(err => toast(err.message, "err"));

$("#c-end").onclick = e => busy(e.target, () => api(`/api/voice/calls/${CALL.id}/end`, { method: "POST", body: { summarize: false } }))
  .then(() => { VoiceLine.stop(); ["#c-mic", "#c-end", "#c-text", "#c-say"].forEach(s => { $(s).disabled = true; }); $("#c-status").textContent = "통화 끝 — 요약은 상담원 보조 화면에서"; })
  .catch(err => toast(err.message, "err"));

(async () => {
  CFG = await api("/api/voice/config");
  $("#c-engines").textContent = `인식 ${CFG.stt.default}${CFG.stt.openai ? " (STT_URL)" : ` (로컬 ${CFG.stt.local})`} · 합성 ${CFG.tts ? "TTS_URL" : "브라우저 음성"} · 전사 저장 ${CFG.store_raw ? "원문" : "개인정보 가림"} · 보관 ${CFG.retention_days}일`;
  $("#c-budget").innerHTML = html`예산 ${CFG.budget_ms}ms: ${html.join(Object.entries(CFG.budget).map(([k, v]) => html`<span class="badge">${CFG.labels[k]} ${v}ms</span>`), " ")}`;
  await setupCollectionPickers({ col: $("#c-col") });
})().catch(e => ui.error($("#c-turns"), e));
