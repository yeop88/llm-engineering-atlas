// kg/rag.html 화면 스크립트 — 그래프 하이브리드 검색 · 답변(K7), 벡터 vs 그래프 비교, 커뮤니티 요약 · 전체 질문(K8)
const LBL = { Article: "조문", Precedent: "판례", Issue: "쟁점" };
const g = () => $("#r-graph").value;
const llmBody = () => ({ provider: $("#r-provider").value || null, model: $("#r-model").value.trim() || null });
const rate = v => (v == null ? "-" : `${Math.round(v * 100)}%`);  // common.js 의 pct 는 소수 한 자리라 정수 % 로 따로

async function loadGraphs() {
  const gs = await api("/api/kg/graphs");
  $("#r-graph").innerHTML = html.or(html.join(gs.map(s => html`<option value="${s.graph}">${s.graph}</option>`), ""), html`<option value="">그래프 없음 — 그래프 구축에서 만드세요</option>`);
  await onGraph();
}
async function onGraph() {
  if (!g()) return;
  try {
    const s = await api(`/api/kg/graphs/${g()}/stats`);
    const sets = (await api(`/api/collections/${s.collection_id}/eval-sets`)).filter(x => x.status === "ready");
    $("#r-set").innerHTML = html.or(html.join(sets.map(x => html`<option value="${x.id}">#${x.id} ${x.name} (${x.n_items}문항)</option>`), ""), html`<option value="">평가 세트 없음</option>`);
  } catch (e) { toast(e.message, "err"); }
  loadComms();
}

function expandBox(ex) {
  return html`<div class="small">그래프 씨앗: ${html.or(html.join(ex.seeds.slice(0, 6), " · "), "찾은 문서가 그래프에 없음")} <span class="muted">(이웃 노드 ${ex.nodes} · 관계 ${ex.edges})</span></div>
    ${ex.docs.length ? html`<h3>그래프로 넓힌 문서</h3><div class="table-wrap"><table><tr><th>문서</th><th class="num">연결</th><th>무엇으로 이어졌나</th></tr>
      ${html.join(ex.docs.map(d => html`<tr><td class="small"><span class="badge">${LBL[d.label] || d.label}</span> ${d.node}</td><td class="num">${d.links}</td><td class="small">${html.join(d.via, " · ")}</td></tr>`), "")}</table></div>` : html`<div class="small muted">넓힐 문서가 없습니다.</div>`}
    ${ex.relations.length ? html`<details class="small"><summary>관계 요약 (${ex.relations.length})</summary>${html.join(ex.relations.map(r => html`<div>${r}</div>`), "")}</details>` : ""}`;
}

$("#r-expand").onclick = async e => {
  const q = $("#r-q").value.trim();
  if (!q || !g()) return toast("그래프와 질문이 필요합니다", "err");
  const r = await busy(e.target, () => api(`/api/kg/graphs/${g()}/expand`, { method: "POST", body: { question: q } }));
  $("#r-out").innerHTML = html`<h3>검색 결과</h3><div class="small">${html.join(r.results.slice(0, 8).map(x => html`<div>${x.rank}. ${x.filename}</div>`), "")}</div>${expandBox(r.expand)}`;
};
$("#r-answer").onclick = async e => {
  const q = $("#r-q").value.trim();
  if (!q || !g()) return toast("그래프와 질문이 필요합니다", "err");
  const r = await busy(e.target, () => api(`/api/kg/graphs/${g()}/answer`, { method: "POST", body: { question: q, ...llmBody() } }));
  const v = r.verify || {};
  $("#r-out").innerHTML = html`<div class="pre">${r.answer}</div>
    <div class="small muted">근거 일치 ${rate(v.supported_ratio)}${r.trace_id ? html` · <a href="/evalops/traces?trace=${r.trace_id}">요청 기록 #${r.trace_id}</a>` : ""}</div>${ui.aiNotice(r.notice, r.trace_id)}
    <details class="small"><summary>근거 ${(r.sources || []).length}개</summary>${html.join((r.sources || []).map((s, i) => html`<div>[${i + 1}] ${s.filename}</div>`), "")}</details>${expandBox(r.expand)}`;
};

function renderEval(r) {
  const row = (name, a) => (a.n ? html`<tr><td>${name} <span class="small muted">${a.n}문항</span></td>
    <td class="num">${rate(a.vector.hit)} → <b>${rate(a.graph.hit)}</b></td><td class="num">${rate(a.vector.all)} → <b>${rate(a.graph.all)}</b></td>
    <td class="num">${a.vector.mrr.toFixed(3)} → ${a.graph.mrr.toFixed(3)}</td><td class="num">${a.added_gold}</td><td class="num">${a.expand_ms}ms</td></tr>` : "");
  $("#r-eval-out").innerHTML = html`<div class="table-wrap"><table><tr><th>질문</th><th class="num">정답 하나라도 (hit@${r.k})</th><th class="num">정답 모두 (all@${r.k})</th><th class="num">MRR</th><th class="num">넓혀서 들어온 정답</th><th class="num">확장 시간</th></tr>
    ${row("전체", r.all)}${row("여러 문서 질문", r.multi)}${html.join(Object.entries(r.by_type).map(([t, a]) => row(t, a)), "")}</table></div>
    <div class="small muted">벡터 → 그래프 확장 · ${r.eval_set?.name || ""}${r.run_id ? ` · run #${r.run_id}` : ""}</div>`;
}
$("#r-eval").onclick = e => {
  if (!g() || !+$("#r-set").value) return toast("그래프와 평가 세트가 필요합니다", "err");
  return runJobInto(e.target, `/api/kg/graphs/${g()}/hybrid-eval`, { eval_set_id: +$("#r-set").value, only_multi: $("#r-multi").checked }, $("#r-eval-progress"), renderEval).catch(() => {});
};

async function loadComms() {
  const cs = await api(`/api/kg/graphs/${g()}/communities`).catch(() => []);
  $("#r-comm-out").innerHTML = cs.length ? html`<div class="stack scroll-lg">${html.join(cs.map(c => html`<details class="small"><summary><b>${c.key}</b> ${c.name} <span class="muted">(구성원 ${c.size})</span></summary><div class="pre">${c.summary}</div></details>`), "")}</div>`
    : html`<div class="small muted">아직 커뮤니티 요약이 없습니다.</div>`;
}
$("#r-comm").onclick = e => {
  if (!g()) return toast("그래프가 없습니다", "err");
  return runJobInto(e.target, `/api/kg/graphs/${g()}/communities`, { top: +$("#r-top").value || 12, ...llmBody() }, $("#r-comm-progress"), () => { toast("커뮤니티 요약을 만들었습니다"); loadComms(); }).catch(() => {});
};
$("#r-global").onclick = async e => {
  const q = $("#r-gq").value.trim();
  if (!q || !g()) return toast("그래프와 질문이 필요합니다", "err");
  const r = await busy(e.target, () => api(`/api/kg/graphs/${g()}/global`, { method: "POST", body: { question: q, ...llmBody() } }));
  $("#r-global-out").innerHTML = html`<div class="pre">${r.answer}</div><div class="small muted">쓴 요약: ${html.join((r.used || []).map(u => html`[C${u.n}] ${u.name}`), " · ")}${r.seconds ? ` · ${r.seconds}초` : ""}</div>`;
};

$("#r-graph").addEventListener("change", onGraph);
loadGraphs().catch(e => toast(e.message, "err"));
