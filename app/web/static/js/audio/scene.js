// audio/scene.html 화면 스크립트 — 나누기 · 사건 · 화자(AU1~AU5), 구간 검색 · 요약(AU6 · AU7), 합성 장면 평가
let ITEMS = [];
const pct = v => (v == null ? "-" : `${Math.round(v * 100)}%`);

$("#a-run").onclick = e => busy(e.target, () => {
  const fd = new FormData();
  const f = $("#a-file").files[0];
  if (f) fd.append("file", f);
  else if ($("#a-scene").value) fd.append("scene_name", $("#a-scene").value);
  fd.append("transcribe", $("#a-stt").checked);
  fd.append("threshold", $("#a-th").value);
  return api("/api/audio/analyze", { method: "POST", form: fd });
}).then(r => {
  ITEMS = r.items;
  const sc = $("#a-scene").value;
  $("#a-play").hidden = !sc;
  if (sc) $("#a-play").src = `/api/audio/scenes/${encodeURIComponent(sc)}.wav`;
  $("#a-out").innerHTML = html`<div class="small muted">${r.seconds}초 녹음 · ${r.elapsed}초 분석 · 화자 ${r.speakers.length}명${r.stt_note ? ` · ${r.stt_note}` : ""}</div>
    <div class="table-wrap"><table><tr><th>구간</th><th>종류</th><th>화자</th></tr>
      ${html.join(r.segments.filter(s => s.type !== "silence").map(s => html`<tr><td>${s.start}~${s.end}초</td><td>${s.type}</td><td>${s.speaker || "-"}</td></tr>`), "")}</table></div>
    <h3>소리 사건</h3>
    ${r.events.length ? html`<ul class="small">${r.events.map(ev => html`<li>${ev.start}~${ev.end}초 ${ev.type}${ev.period_s ? ` · ${ev.period_s}초 간격 ${ev.count}번 · 고르기 ${ev.regularity}` : ""}${ev.type === "beep" ? ` · ${ev.count}번` : ""}</li>`)}</ul>` : html`<div class="small muted">없음</div>`}
    <h3>시간 순 요약</h3><pre class="pre small">${r.summary}</pre>`;
}).catch(err => ui.error($("#a-out"), err));

$("#s-run").onclick = e => {
  if (!ITEMS.length) { ui.error($("#s-out"), new Error("먼저 위에서 분석하세요")); return; }
  busy(e.target, () => api("/api/audio/search", { method: "POST", body: { items: ITEMS, q: $("#s-q").value.trim() } })).then(r => {
    $("#s-out").innerHTML = html`<ol class="small">${r.results.map(x => html`<li>${x.line} <span class="muted">(점수 ${x.score})</span></li>`)}</ol>`;
  }).catch(err => ui.error($("#s-out"), err));
};

$("#e-run").onclick = e => busy(e.target, () => api("/api/audio/evaluate", { method: "POST", body: { held_out: +$("#e-n").value } })).then(r => {
  const row = (name, a) => html`<tr><td>${name}</td><td>${a.n}</td><td><b>${pct(a.frame_acc)}</b></td><td>${pct(a.vad_acc)}</td><td>${pct(a.event_precision)} · ${pct(a.event_recall)}</td>
    <td>${pct(a.diar_purity)} · ${pct(a.diar_coverage)}</td><td>${a.speaker_count_err ?? "-"}</td></tr>`;
  $("#e-out").innerHTML = html`<div class="small muted">${r.seconds}초 · run #${r.run_id} — 검색 1위 적중 <b>${pct(r.search_hit)}</b></div>
    <div class="table-wrap"><table><tr><th>장면</th><th>수</th><th>프레임 종류 정확</th><th>크기만(기준선)</th><th>사건 정밀 · 재현</th><th>화자 순도 · 덮음</th><th>화자 수 오차</th></tr>
      ${row("예시 장면", r.preset)}${row("무작위(맞추지 않은)", r.held_out)}</table></div>
    <div class="table-wrap"><table><tr><th>질문</th><th>장면</th><th>1위</th><th>적중</th></tr>
      ${html.join(r.search.map(h => html`<tr><td>${h.q}</td><td class="small">${h.scene}</td><td class="small">${h.top}</td><td>${h.hit ? "예" : html`<span class="badge err">아니오</span>`}</td></tr>`), "")}</table></div>`;
}).catch(err => ui.error($("#e-out"), err));

api("/api/audio/preset").then(p => {
  $("#a-scene").innerHTML = html`<option value="">(녹음 파일 쓰기)</option>${p.scenes.map(s => html`<option>${s}</option>`)}`;
  $("#a-scene").value = p.scenes[0];
}).catch(err => ui.error($("#a-out"), err));
