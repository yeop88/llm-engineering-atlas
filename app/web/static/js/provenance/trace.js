// provenance/trace.html 화면 스크립트 — 요청 하나의 계보(PV1~PV7) · 주장 나누기
const LV = { strong: ["ok", "근거 강함"], weak: ["warn", "근거 약함"], none: ["err", "근거 없음"], uncited: ["warn", "인용 안 함"] };
const pct = v => (v == null ? "-" : `${Math.round(v * 100)}%`);

function claimsHtml(a) {
  return html`<div class="row small"><span>주장 ${a.n}</span><span>근거 강함 <b>${pct(a.strong)}</b></span><span>약함 ${pct(a.weak)}</span><span>없음 ${pct(a.none)}</span>
      <span>인용 안 함 ${pct(a.uncited)}</span><span>빠진 표시 ${a.marks_missing}</span><span>인용 정확도 ${pct(a.cite_precision)}</span><span>원본까지 추적 ${pct(a.traceable)}</span></div>
    <div class="table-wrap"><table><tr><th>문장</th><th>주장</th><th>인용</th><th>가장 겹치는 근거</th><th>겹침</th><th>판정</th><th>근거에 없는 표시</th></tr>
    ${html.join(a.claims.map(c => html`<tr><td>${c.sentence_idx + 1}</td><td class="small">${c.claim}</td><td>${c.cites.map(x => `[${x}]`).join(" ") || "-"}</td>
      <td>${c.best_source ? `[${c.best_source}]` : "-"}${c.cites.length && !c.cite_matches_best ? html` <span class="badge warn">인용과 다름</span>` : ""}</td><td>${c.overlap}</td>
      <td><span class="badge ${LV[c.level][0]}">${LV[c.level][1]}</span></td><td class="mono small">${c.marks_missing.join(" ") || "-"}</td></tr>`), "")}</table></div>`;
}

$("#t-run").onclick = e => busy(e.target, () => api(`/api/provenance/trace/${$("#t-pick").value}`)).then(r => {
  const t = r.trace;
  $("#t-out").innerHTML = html`<div class="small muted">#${t.id} · ${t.at} · ${t.kind} · ${t.model} · 해시 ${t.hash}</div>
    <div class="small"><b>질문</b> ${t.question}</div><div class="pre small">${t.answer}</div>
    ${claimsHtml(r.claims)}
    <h3>근거 → 원본</h3>
    <div class="table-wrap"><table><tr><th>#</th><th>청크</th><th>청크 세트</th><th>문서</th><th>판</th><th>컬렉션</th></tr>
    ${html.join(r.sources.map(s => s.found ? html`<tr><td>[${s.n}]</td>
      <td class="small">${s.chunk ? html`#${s.chunk.id} · ${s.chunk.page != null ? `쪽 ${s.chunk.page} · ` : ""}${s.chunk.start}~${s.chunk.end}자<div class="muted">${s.chunk.text.slice(0, 120)}</div>` : "-"}</td>
      <td class="small">${s.chunk_set ? html`${s.chunk_set.name}<div class="muted mono">${JSON.stringify(s.chunk_set.strategy)}</div>` : "-"}</td>
      <td class="small">${s.document.filename}<div class="muted mono">${s.document.sha256.slice(0, 12)} · ${s.document.ingested_at}</div></td>
      <td class="small">${s.versions.length}개 판${s.stale ? html` <span class="badge warn">옛 판 근거</span>` : html` <span class="badge ok">지금 판</span>`}</td>
      <td class="small">${s.collection ? s.collection.name : "-"}</td></tr>` : html`<tr><td>[${s.n}]</td><td colspan="5" class="muted">${s.filename || ""} — 지워졌거나 찾을 수 없음</td></tr>`), "")}</table></div>`;
}).catch(err => ui.error($("#t-out"), err));

$("#a-run").onclick = e => busy(e.target, () => api("/api/provenance/analyze", { method: "POST", body: { answer: $("#a-answer").value,
  sources: $("#a-src").value.split("\n").filter(Boolean).map(text => ({ text })) } })).then(a => { $("#a-out").innerHTML = claimsHtml(a); }).catch(err => ui.error($("#a-out"), err));

api("/api/provenance/traces").then(r => {
  $("#t-pick").innerHTML = r.traces.length ? html`${r.traces.map(t => html`<option value="${t.id}">#${t.id} ${t.at.slice(5, 16)} · ${t.kind} · ${t.question}</option>`)}` : html`<option value="">요청 기록 없음</option>`;
  // 평가 화면의 '기록 #n' 링크(?trace=n)로 오면 그 기록을 바로 따라간다
  const want = new URLSearchParams(location.search).get("trace");
  if (want) {
    if (![...$("#t-pick").options].some(o => o.value === want)) $("#t-pick").insertAdjacentHTML("afterbegin", html`<option value="${want}">#${want}</option>`);
    $("#t-pick").value = want;
    $("#t-run").click();
  }
}).catch(err => ui.error($("#t-out"), err));
