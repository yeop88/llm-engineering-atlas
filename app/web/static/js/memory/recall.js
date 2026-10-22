// memory/recall.html 화면 스크립트 — 점수 조합 기억 검색 · 핵심 기억 블록 · 맥락(ME3 · ME6), 통합 · 망각 미리 보기 · 실행(ME5)
const owner = () => $("#r-owner").value;

$("#r-run").onclick = e => busy(e.target, () => api("/api/memory/recall", { method: "POST", body: { owner: owner(), question: $("#r-q").value, k: +$("#r-k").value || 6,
  w_sim: +$("#r-ws").value, w_rec: +$("#r-wr").value, w_imp: +$("#r-wi").value } })).then(r => {
  $("#r-out").innerHTML = html`<div class="small">${r.past ? html`<span class="badge warn">과거 질문 — 무효가 된 이력까지</span>` : html`<span class="badge">지금 맞는 기억만</span>`}
    · 핵심 ${r.chars.core}자 · 관련 ${r.chars.recall}자</div>
    <div class="table-wrap"><table><tr><th>#</th><th>기억</th><th>맞았던 때</th><th>점수</th><th>비슷함 · 최근 · 중요도</th><th>연결</th></tr>
    ${html.join(r.items.map(i => html`<tr${i.current ? "" : html` class="muted"`}><td>${i.id}</td><td class="small">${i.text}</td><td class="small">${i.valid}</td><td><b>${i.score}</b></td>
      <td class="small">${i.parts ? `${i.parts.sim} · ${i.parts.rec} · ${i.parts.imp}` : "-"}</td><td class="small">${i.via || ""}</td></tr>`), "")}</table></div>
    <h3>맥락에 넣는 글</h3><pre class="small pre">${r.text}</pre>`;
}).catch(err => ui.error($("#r-out"), err));

function consolidate(dry) {
  return api("/api/memory/consolidate", { method: "POST", body: { owner: owner(), min_events: +$("#c-min").value || 3, older_days: +$("#c-days").value, forget_below: +$("#c-forget").value, dry_run: dry } })
    .then(r => {
      $("#c-out").innerHTML = html`<div class="small">${r.dry_run ? html`<span class="badge">미리 보기</span>` : html`<span class="badge warn">정리함</span>`} 요약 ${r.summaries.length} · 보관으로 ${r.archived.length} · 잊음 ${r.forgotten.length}</div>
        ${html.join(r.summaries.map(s => html`<div class="small"><b>${s.key}</b> ${s.text}</div>`), "")}
        ${r.forgotten.length ? html`<ul class="small">${html.join(r.forgotten.map(f => html`<li>#${f.id} ${f.text} <span class="muted">(${f.score})</span></li>`), "")}</ul>` : ""}`;
    });
}
$("#c-preview").onclick = e => busy(e.target, () => consolidate(true)).catch(err => ui.error($("#c-out"), err));
$("#c-apply").onclick = async e => {
  if (!(await ui.confirm("요약에 합친 사건은 보관으로 옮기고, 잊을 기억은 지웁니다. 계속할까요?"))) return;
  busy(e.target, () => consolidate(false)).catch(err => ui.error($("#c-out"), err));
};

(async () => {
  const r = await api("/api/memory/owners");
  $("#r-owner").innerHTML = html`${r.owners.map(o => html`<option value="${o.owner}">${o.owner} · 기억 ${o.items}</option>`)}`;
  if (!r.owners.length) ui.empty($("#r-out"), "기억이 없습니다 — 기억 쌓기 화면에서 먼저 넣으세요.");
})().catch(e => ui.error($("#r-out"), e));
