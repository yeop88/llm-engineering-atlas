// voice/eval.html 화면 스크립트 — 인식 평가(VC1) · 읽기 규칙(VC4) · 불만 감지 평가(VC5) · 통화 기록 지연 보고(VC3 · VC6 · VC7)
const VARIANT = { plain: "사전 없음", prompt: "앞 문맥", "prompt+restore": "앞 문맥 + 표기 복원" };
const pct = v => (v == null ? "-" : `${(v * 100).toFixed(1)}%`);

async function loadSets() {
  const r = await api("/api/voice/stt/sets");
  $("#t-set").innerHTML = html`${r.sets.map(s => html`<option>${s.name}</option>`)}`;
  $("#t-sets").innerHTML = r.sets.length ? html`<div class="small">${html.join(r.sets.map(s => html`<span class="badge">${s.name} · ${s.n}개</span>`), " ")}</div>` : html`<p class="small muted">음성 평가 세트가 없습니다.</p>`;
}

$("#t-add").onclick = e => {
  const fd = new FormData();
  fd.append("name", $("#t-name").value.trim());
  fd.append("refs", $("#t-refs").value);
  [...$("#t-files").files].forEach(f => fd.append("files", f));
  busy(e.target, () => api("/api/voice/stt/sets", { method: "POST", form: fd })).then(r => { toast(`${r.added}개 넣음 · 정답 없는 파일 ${r.skipped}개`); loadSets(); }).catch(err => toast(err.message, "err"));
};

$("#t-run").onclick = e => {
  const engines = [["#t-openai", "openai"], ["#t-local", "local"]].filter(([s]) => $(s).checked).map(([, v]) => v);
  runJobInto(e.target, "/api/voice/stt/eval", { set: $("#t-set").value, engines, collection_id: +$("#t-col").value || null }, $("#t-progress"), r => {
    $("#t-out").innerHTML = html`<div class="small muted">파일 ${r.n} · 사전 ${r.vocab.length}개 · run #${r.run_id}</div>
      <div class="table-wrap"><table><tr><th>엔진</th><th>사전</th><th>글자 오류율</th><th>용어 정확도</th><th>실시간 계수</th></tr>
      ${html.join(r.results.map(x => x.status === "ok" ? html`<tr><td>${x.engine}</td><td>${VARIANT[x.variant]}</td><td><b>${pct(x.cer)}</b></td><td>${pct(x.term_acc)} <span class="small muted">(${x.n_terms})</span></td><td>${x.rtf ?? "-"}</td></tr>`
        : html`<tr><td>${x.engine}</td><td>${VARIANT[x.variant]}</td><td colspan="3"><span class="badge err">${x.error}</span></td></tr>`), "")}</table></div>
      <p class="small muted">실시간 계수 = 인식 시간 / 소리 길이 — 1 보다 작아야 말하는 속도를 따라갑니다.</p>`;
  }).catch(err => ui.error($("#t-out"), err));
};

$("#t-one-run").onclick = e => {
  const f = $("#t-one").files[0];
  if (!f) return toast("파일을 고르세요", "err");
  const fd = new FormData();
  fd.append("file", f);
  if (+$("#t-col").value) fd.append("collection_id", $("#t-col").value);
  busy(e.target, () => api("/api/voice/stt/transcribe", { method: "POST", form: fd })).then(r => {
    $("#t-one-out").innerHTML = html`<div class="small">${r.engine} · 소리 ${r.seconds_audio}초 · 인식 ${r.seconds}초(실시간 계수 ${r.rtf})</div><div class="pre">${r.text}</div>
      ${r.fixes.length ? html`<div class="small">표기 복원: <b>${r.restored}</b> (${r.fixes.map(x => `${x.from}→${x.to}`).join(", ")})</div>` : ""}
      <div class="small muted">운율: ${r.prosody.db ?? "-"}dB · ${r.prosody.f0 ?? "-"}Hz · 초당 ${r.prosody.rate ?? "-"}글자</div>`;
  }).catch(err => ui.error($("#t-one-out"), err));
};

$("#r-run").onclick = e => busy(e.target, () => api("/api/voice/tts/preview", { method: "POST", body: { text: $("#r-text").value } })).then(r => {
  $("#r-out").innerHTML = html`<div class="table-wrap"><table><tr><th>문장</th><th>읽는 글</th><th></th></tr>
    ${html.join(r.sentences.map((s, i) => html`<tr><td class="small">${s.text}</td><td class="small"><b>${s.spoken}</b></td><td><button class="btn sm" data-play="${i}">듣기</button></td></tr>`), "")}</table></div>
    <p class="small muted">합성: ${r.tts ? "TTS_URL" : "브라우저 음성(ko-KR)"}</p>`;
  $$("[data-play]").forEach(b => b.onclick = () => {
    const s = r.sentences[+b.dataset.play];
    if (s.audio) new Audio(`/api/voice/tts/${s.audio}`).play();
    else if (window.speechSynthesis) { const u = new SpeechSynthesisUtterance(s.spoken); u.lang = "ko-KR"; speechSynthesis.speak(u); }
  });
}).catch(err => ui.error($("#r-out"), err));

$("#m-run").onclick = e => busy(e.target, () => api("/api/voice/emotion/score", { method: "POST", body: { text: $("#m-text").value } })).then(a => {
  $("#m-out").innerHTML = html`<div class="row small"><b>점수 ${a.score}</b> · 말투 ${a.tone} ${a.cues.length ? html`· 단서 ${a.cues.join(", ")}` : ""}
    ${a.escalate ? html`<span class="badge err">이관 · ${a.reasons.join(", ")}</span>` : html`<span class="badge ok">자동 응답 계속</span>`}</div>`;
}).catch(err => ui.error($("#m-out"), err));

$("#m-eval").onclick = e => busy(e.target, () => api("/api/voice/emotion/eval", { method: "POST" })).then(r => {
  const c = r.confusion;
  $("#m-out").innerHTML = html`<div class="small">문장 ${r.n} · 이관 정밀도 <b>${r.precision}</b> · 재현율 <b>${r.recall}</b> · 정확도 ${r.accuracy} (TP ${c.tp} · FP ${c.fp} · FN ${c.fn} · TN ${c.tn}) · run #${r.run_id}</div>
    ${r.errors.length ? html`<ul class="small">${html.join(r.errors.map(x => html`<li>${x.gold ? "놓침" : "잘못 이관"} · ${x.text} (${x.score})</li>`), "")}</ul>` : ""}
    <p class="small muted">글만으로 잰 값입니다(목소리 점수 · 두 턴 이어짐 · 반복 규칙은 통화 기록에서).</p>`;
}).catch(err => ui.error($("#m-out"), err));

$("#p-run").onclick = e => busy(e.target, () => api("/api/voice/report")).then(r => {
  const L = r.latency, a = r.adoption;
  $("#p-out").innerHTML = html`<div class="small muted">통화 ${r.calls} · 자동 답 턴 ${L.n} · 예산 ${r.budget_ms}ms</div>
    <div class="table-wrap"><table><tr><th>단계</th><th>턴</th><th>p50</th><th>p95</th><th>예산 넘음</th></tr>
    ${html.join(Object.values(L.stages).map(s => html`<tr><td>${s.label}</td><td>${s.n}</td><td>${s.p50 ?? "-"}ms</td><td>${s.p95 ?? "-"}ms</td><td>${s.over}</td></tr>`), "")}
    <tr><th>첫 소리까지</th><td>${L.n}</td><td><b>${L.first_audio.p50 ?? "-"}ms</b></td><td><b>${L.first_audio.p95 ?? "-"}ms</b></td><td>예산 안 ${pct(L.within)}</td></tr></table></div>
    <div class="row small">${html.join(Object.entries(r.modes).map(([k, v]) => html`<span class="badge">${k} ${v}</span>`), " ")}
      <span class="badge">끼어들기 ${r.barge_in.n}/${r.barge_in.of}</span><span class="badge">이관 ${r.escalations}</span>
      <span class="badge">추천 채택 ${pct(a.adopted)} · 고쳐서 ${pct(a.edited)} (평가 ${a.rated})</span><span class="badge">요약 검증 ${r.summary_ok.ok}/${r.summary_ok.n}</span>
      <span class="badge">인식 실시간 계수 ${r.stt_rtf ?? "-"}</span></div>`;
}).catch(err => ui.error($("#p-out"), err));

(async () => {
  await setupCollectionPickers({ col: $("#t-col") });
  await loadSets();
  $("#p-run").click();
})().catch(e => ui.error($("#t-sets"), e));
