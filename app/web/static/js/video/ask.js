// video/ask.html 화면 스크립트 — 색인 만들기(VD1~VD5 · VD7), 시간 질문(VD6 · VD8), 합성 영상 평가
let IDX = null, SEED = null;
const pct = v => (v == null ? "-" : `${Math.round(v * 100)}%`);
const llmRef = (p, m) => ({ provider: $(p).value || null, model: $(m).value.trim() || null });
const evLine = e => `${e.t}초 ${e.type}: ${e.subject ?? ""}${e.object ? ` ↔ ${e.object}` : ""}${e.source ? ` (${e.source})` : ""}`;

$("#i-run").onclick = e => busy(e.target, () => {
  const fd = new FormData();
  const f = $("#i-file").files[0];
  if (f) fd.append("file", f);
  else fd.append("seed", $("#i-seed").value);
  fd.append("fps", $("#i-fps").value);
  fd.append("describe", $("#i-desc").checked);
  if ($("#i-provider").value) fd.append("provider", $("#i-provider").value);
  if ($("#i-model").value.trim()) fd.append("model", $("#i-model").value.trim());
  return api("/api/video/index", { method: "POST", form: fd });
}).then(r => {
  IDX = r;
  SEED = $("#i-file").files[0] ? null : +$("#i-seed").value;
  $("#i-out").innerHTML = html`<div class="small muted">${r.info.duration}초 · 소리 ${r.info.audio ? "있음" : "없음"} · 컷 ${r.cuts.length} · 트랙 ${r.tracks.length} · 사건 ${r.events.length} · ${r.seconds}초</div>
    <div class="grid cols-2"><div><h3>사건(시간 순)</h3><pre class="pre small scroll-md">${r.log}</pre></div>
      <div><h3>장면 · 대표 프레임</h3><ul class="small">${r.keyframes.map(k => html`<li>장면 ${k.shot}: ${k.start}~${k.end}초${k.desc ? ` — ${k.desc.caption || ""}` : ""}</li>`)}</ul>
        <h3>트랙</h3><ul class="small">${r.tracks.map(t => html`<li>${t.name} #${t.id}: ${t.start}~${t.end}초</li>`)}</ul></div></div>`;
}).catch(err => ui.error($("#i-out"), err));

$("#a-run").onclick = e => {
  if (!IDX) { ui.error($("#a-out"), new Error("먼저 위에서 색인을 만드세요")); return; }
  busy(e.target, () => api("/api/video/ask", { method: "POST", body: { events: IDX.events, q: $("#a-q").value.trim(),
    llm: $("#a-llm").checked ? llmRef("#i-provider", "#i-model") : null } })).then(r => {
    const p = r.parsed || {};
    $("#a-out").innerHTML = html`<div>풀이: 대상 ${p.subject ?? "-"} · 사건 ${p.type ?? "-"} · 연산 ${p.op ?? "-"}${p.anchor ? ` · 기준 ${p.relation === "after" ? "다음" : "전"}(${p.anchor.type})` : ""}</div>
      <div class="mt-2">색인 계산: <b>${r.answer ?? "답 없음"}</b>${r.reason ? html` <span class="muted">(${r.reason})</span>` : ""}</div>
      ${r.evidence?.length ? html`<ul>${r.evidence.map(ev => html`<li>${evLine(ev)}</li>`)}</ul>` : ""}
      ${r.clips?.length ? html`<div class="muted">클립: ${r.clips.map(c => `${c[0]}~${c[1]}초`).join(", ")}</div>` : ""}
      ${r.llm ? html`<div class="mt-2">기록 전체를 LLM 에: <b>${r.llm.answer ?? "답 없음"}</b> <span class="muted">(${r.llm.seconds}초)</span></div>` : ""}`;
    const t = typeof r.answer === "number" && r.evidence?.length === 1 ? r.answer : null;
    $("#a-img").hidden = !(SEED != null && t != null);
    if (SEED != null && t != null) $("#a-img").src = `/api/video/sample/${SEED}/frame.png?t=${t}`;
  }).catch(err => ui.error($("#a-out"), err));
};

$("#e-run").onclick = e => runJobInto(e.target, "/api/video/evaluate", { n: +$("#e-n").value, compare_llm: $("#e-llm").checked, llm: llmRef("#i-provider", "#i-model") }, $("#e-progress"), r => {
  $("#e-out").innerHTML = html`<div class="small muted">영상 ${r.videos} · 질문 ${r.questions} · ${r.seconds}초 · run #${r.run_id}${r.model ? ` · ${r.model}` : ""}</div>
    <div class="small">컷 정밀 · 재현 ${pct(r.cuts.precision)} · ${pct(r.cuts.recall)} · 사건 ${pct(r.events.precision)} · ${pct(r.events.recall)}</div>
    <div class="table-wrap"><table><tr><th>질문 종류</th><th>수</th><th>색인 계산(찾은 색인)</th><th>색인 계산(정답 색인)</th><th>기록 전체를 LLM 에</th></tr>
      ${html.join(Object.entries(r.by_kind).map(([k, v]) => html`<tr><td>${k}</td><td>${v.n}</td><td><b>${pct(v.index)}</b></td><td>${pct(v.gold_index)}</td><td>${pct(v.llm)}</td></tr>`), "")}
      <tr><td><b>전체</b></td><td>${r.questions}</td><td><b>${pct(r.index)}</b></td><td>${pct(r.gold_index)}</td><td>${pct(r.llm)}</td></tr></table></div>`;
}).catch(err => ui.error($("#e-out"), err));
