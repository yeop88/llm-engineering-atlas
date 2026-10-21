// kg/build.html 화면 스크립트 — 온톨로지(K2) 보기 · 그래프 구축(K3 추출 · K4 합치기 · K5 적재) · 구축 기록
const LBL = { Statute: "법령", Article: "조문", Precedent: "판례", Issue: "쟁점", Community: "커뮤니티" };
const REL = { PART_OF: "속함", REFERS_TO: "참조", CITES: "인용", CITES_CASE: "판례 인용", CONCERNS: "다룸", IN_COMMUNITY: "구성원" };

async function loadOnto() {
  const o = await api("/api/kg/ontology");
  $("#b-onto").innerHTML = html`<div class="small muted">${o.name} — ${o.note}</div>
    <div class="table-wrap"><table><tr><th>클래스</th><th>뜻</th><th>key</th></tr>
      ${html.join(Object.entries(o.classes).map(([k, v]) => html`<tr><td><b>${v.label}</b> <span class="mono small">${k}</span></td><td class="small">${v.desc}</td><td class="small">${v.key}</td></tr>`), "")}</table></div>
    <div class="table-wrap"><table><tr><th>관계</th><th>방향</th><th>뜻</th></tr>
      ${html.join(Object.entries(o.relations).map(([k, v]) => html`<tr><td><b>${v.label}</b> <span class="mono small">${k}</span></td><td class="small mono">${v.from} → ${v.to}</td><td class="small">${v.desc}</td></tr>`), "")}</table></div>
    <details class="small"><summary>규칙 · Text2Cypher 스키마 설명</summary><ul>${html.join(o.rules.map(r => html`<li>${r}</li>`), "")}</ul><pre class="pre small">${o.schema_text}</pre></details>`;
}

async function loadCols() {
  const cols = await api("/api/collections");
  $("#b-col").innerHTML = html.or(html.join(cols.map(c => html`<option value="${c.id}">${c.name}</option>`), ""), html`<option value="">컬렉션 없음</option>`);
  applyCtx($("#b-col"));
}

function counts(obj, names) {
  return html.join(Object.entries(obj || {}).map(([k, v]) => html`<span class="badge">${names[k] || k} ${fmtNum(v)}</span>`), " ");
}

function render(r) {
  const s = r.stats || {};
  const iss = r.issues || {};
  $("#b-out").innerHTML = html`<div class="row"><b>${r.graph}</b> · 노드 ${fmtNum(s.nodes)} · 관계 ${fmtNum(s.edges)}${r.seconds ? html` <span class="small muted">· 추출 ${r.seconds.extract}초 · 전체 ${r.seconds.total}초</span>` : ""}
      ${r.run_id ? html` <span class="small muted">run #${r.run_id}</span>` : ""}</div>
    <div>${counts(s.labels, LBL)}</div><div>${counts(s.types, REL)}</div>
    <div class="small">${r.n_rejected ? html`<span class="badge warn">걸러 냄 ${r.n_rejected}</span> 온톨로지 규칙에 맞지 않는 노드 · 관계` : html`<span class="badge ok">걸러 낸 것 없음</span>`}
      ${iss.asked ? html` · 쟁점: 판례 ${iss.asked}개에서 ${iss.with_issues}개가 쟁점을 냄, 이름 ${iss.raw}개 → 합친 뒤 ${iss.merged}개 (${iss.seconds}초)` : iss.reused ? html` · 앞선 쟁점 다시 씀(판례 ${iss.reused}개), 이름 ${iss.raw}개 → 합친 뒤 ${iss.merged}개` : html` · 쟁점 추출 안 함`}</div>
    ${r.rejected?.length ? html`<details class="small"><summary>걸러 낸 것 (앞 ${r.rejected.length})</summary>${html.join(r.rejected.map(x => html`<div>${x.what} — ${x.why}</div>`), "")}</details>` : ""}
    ${r.merges?.length ? html`<h3>합친 쟁점</h3><div class="table-wrap scroll-md"><table><tr><th>대표 이름</th><th>합친 다른 이름</th></tr>
      ${html.join(r.merges.map(m => html`<tr><td class="small"><b>${m.canonical}</b></td><td class="small">${html.join(m.aliases, " · ")}</td></tr>`), "")}</table></div>` : ""}
    <div class="small"><a href="/kg/explore">그래프 탐색 · Cypher</a> · <a href="/kg/rag">GraphRAG</a></div>`;
}

async function loadRuns() {
  const runs = await api("/api/kg/builds");
  if (!runs.length) return ui.empty($("#b-runs"), "아직 구축 기록이 없습니다.");
  $("#b-runs").innerHTML = html`<div class="table-wrap"><table><tr><th>#</th><th>시각</th><th>구축</th><th class="num">노드</th><th class="num">관계</th><th></th></tr>
    ${html.join(runs.map(r => html`<tr><td class="num">${r.id}</td><td class="small nowrap">${fmtDate(r.created_at)}</td><td class="small">${r.title}</td>
      <td class="num">${fmtNum(r.stats?.nodes)}</td><td class="num">${fmtNum(r.stats?.edges)}</td><td><button class="btn sm" data-run="${r.id}">보기</button></td></tr>`), "")}</table></div>`;
  $$("[data-run]").forEach(b => { b.onclick = async () => render(await api(`/api/kg/runs/${b.dataset.run}`)); });
}

$("#b-run").onclick = e => {
  const body = { collection_id: +$("#b-col").value, graph: $("#b-graph").value.trim(), issue_limit: +$("#b-issues").value || 0, reuse_issues: $("#b-reuse").checked,
    provider: $("#b-provider").value || null, model: $("#b-model").value.trim() || null };
  if (!body.collection_id) return toast("컬렉션을 고르세요", "err");
  return runJobInto(e.target, "/api/kg/build", body, $("#b-progress"), r => { render(r); loadRuns(); toast("그래프를 만들었습니다"); }).catch(() => {});
};

loadOnto().catch(e => ui.error($("#b-onto"), e));
loadCols().catch(e => toast(e.message, "err"));
loadRuns().catch(e => ui.error($("#b-runs"), e));
