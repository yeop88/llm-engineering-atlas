// kg/explore.html 화면 스크립트 — 노드 찾기 · 이웃(K5), Cypher 엔진(Neo4j · FalkorDB) 옮기기 · Cypher · Text2Cypher(K6), 역량 질문 정확도(K1)
const LBL = { Statute: "법령", Article: "조문", Precedent: "판례", Issue: "쟁점", Community: "커뮤니티" };
const REL = { PART_OF: "속함", REFERS_TO: "참조", CITES: "인용", CITES_CASE: "판례 인용", CONCERNS: "다룸", IN_COMMUNITY: "구성원" };
const KIND = { lookup: "한 단계 조회", multi: "여러 단계", aggregate: "집계", negative: "없는 것 찾기" };
const g = () => $("#x-graph").value;
const eng = () => $("#x-engine").value;

async function loadGraphs() {
  const gs = await api("/api/kg/graphs");
  $("#x-graph").innerHTML = html.or(html.join(gs.map(s => html`<option value="${s.graph}">${s.graph}</option>`), ""), html`<option value="">그래프 없음 — 그래프 구축에서 만드세요</option>`);
  onGraph();
}
async function onGraph() {
  if (!g()) return;
  const s = await api(`/api/kg/graphs/${g()}/stats`).catch(() => null);
  $("#x-stats").innerHTML = s ? html`노드 ${fmtNum(s.nodes)} · 관계 ${fmtNum(s.edges)} · ${html.join(Object.entries(s.labels).map(([k, v]) => html`${LBL[k] || k} ${fmtNum(v)}`), " · ")}` : "";
}

function table(res) {
  if (!res) return "";
  if (!res.rows.length) return html`<div class="small muted">결과 없음</div>`;
  return html`<div class="table-wrap scroll-md"><table><tr>${html.join(res.columns.map(c => html`<th>${c}</th>`), "")}</tr>
    ${html.join(res.rows.map(r => html`<tr>${html.join(r.map(v => html`<td class="small">${typeof v === "object" ? JSON.stringify(v) : v}</td>`), "")}</tr>`), "")}</table></div>`;
}

async function find() {
  if (!g()) return;
  const q = encodeURIComponent($("#x-q").value.trim());
  const rows = await api(`/api/kg/graphs/${g()}/nodes?q=${q}&label=${$("#x-label").value}&limit=100`);
  $("#x-list").innerHTML = html.or(html.join(rows.map(n => html`<div class="row"><span class="badge">${LBL[n.label] || n.label}</span><a href="#" data-node="${n.id}">${n.name}</a>
    ${n.props?.external ? html`<span class="badge muted" title="자료에 본문이 없는 인용 대상">바깥</span>` : ""}</div>`), ""), html`<div class="small muted">없습니다.</div>`);
  $$("[data-node]").forEach(a => { a.onclick = ev => { ev.preventDefault(); openNode(+a.dataset.node); }; });
}

async function openNode(id) {
  const d = await api(`/api/kg/graphs/${g()}/nodes/${id}`);
  const n = d.node;
  const out = d.edges.filter(e => e.src === id), inn = d.edges.filter(e => e.dst === id);
  const row = (e, other, name, label) => html`<tr><td><span class="badge">${REL[e.type] || e.type}</span></td><td><span class="small muted">${LBL[label] || label}</span> <a href="#" data-node="${other}">${name}</a></td></tr>`;
  $("#x-node").innerHTML = html`<div><span class="badge">${LBL[n.label] || n.label}</span> <b>${n.name}</b>${n.document_id ? html` · <a href="/rag/collections">문서 #${n.document_id}</a>` : ""}</div>
    <div class="small muted mono">${Object.entries(n.props || {}).filter(([k]) => k !== "summary").map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(", ") : v}`).join(" · ")}</div>
    ${n.props?.summary ? html`<div class="small pre">${n.props.summary}</div>` : ""}
    <h3>나가는 관계 (${out.length})</h3><div class="table-wrap scroll-md"><table>${html.join(out.map(e => row(e, e.dst, e.dst_name, e.dst_label)), "")}</table></div>
    <h3>들어오는 관계 (${inn.length})</h3><div class="table-wrap scroll-md"><table>${html.join(inn.map(e => row(e, e.src, e.src_name, e.src_label)), "")}</table></div>`;
  $$("[data-node]", $("#x-node")).forEach(a => { a.onclick = ev => { ev.preventDefault(); openNode(+a.dataset.node); }; });
}

// 두 엔진 상태를 함께 보인다 — 같은 그래프 · 같은 질문으로 방언 · 속도를 비교하려고 엔진을 둘 둔다
const HOW = { neo4j: "docker compose --profile neo4j up -d, .env 의 NEO4J_URL · NEO4J_PASSWORD", falkordb: "docker compose --profile falkordb up -d, .env 의 FALKORDB_URL" };
async function neo() {
  const s = await api("/api/kg/engines");
  if (s.default) $("#x-engine").value = s.default;
  $("#x-neo").innerHTML = html`${html.join(s.engines.map(e => html`<div><b>${e.label}</b> ${e.ok ? html`<span class="badge ok">연결됨</span> <span class="mono">${e.url}</span>`
    : html`<span class="badge warn">연결 안 됨</span> <span class="muted">${e.detail || ""} — ${HOW[e.engine]}</span>`}</div>`), "")}
    <div class="muted">엔진마다 그래프 하나만 둡니다(옮길 때 이전 것을 지움).</div>`;
}

$("#x-graph").addEventListener("change", onGraph);
$("#x-find").onclick = () => find().catch(e => toast(e.message, "err"));
$("#x-q").addEventListener("keydown", e => { if (e.key === "Enter") $("#x-find").click(); });
$("#x-sync").onclick = async e => {
  if (!g()) return toast("그래프가 없습니다", "err");
  const r = await busy(e.target, () => api(`/api/kg/graphs/${g()}/sync?engine=${eng()}`, { method: "POST" }));
  toast(`${$("#x-engine").selectedOptions[0].text} 로 옮겼습니다 — 노드 ${fmtNum(r.nodes)} · 관계 ${fmtNum(r.edges)} · ${r.seconds}초`);
};
$("#x-run").onclick = async e => {
  const r = await busy(e.target, () => api("/api/kg/cypher", { method: "POST", body: { query: $("#x-cypher").value, engine: eng() } }));
  $("#x-out").innerHTML = table(r);
};
$("#x-ask-run").onclick = async e => {
  const q = $("#x-ask").value.trim();
  if (!q) return toast("질문을 입력하세요", "err");
  $("#x-status").textContent = "Cypher 를 쓰는 중…";
  const r = await busy(e.target, () => api("/api/kg/text2cypher", { method: "POST", body: { question: q, engine: eng(), provider: $("#x-provider").value || null, model: $("#x-model").value.trim() || null } }))
    .finally(() => { $("#x-status").textContent = ""; });
  $("#x-cypher").value = r.cypher;
  $("#x-out").innerHTML = html`<div class="small muted">시도 ${r.attempts.length}번 · ${r.seconds}초${r.attempts.length > 1 ? html` — ${html.join(r.attempts.slice(0, -1).map(a => html`<div class="mono">${a.cypher} → ${a.error || "빈 결과"}</div>`), "")}` : ""}</div>
    ${r.error ? html`<div class="errbox" role="alert">${r.error}</div>` : table(r.result)}`;
};

async function loadCq() {
  const p = await api("/api/kg/cq");
  $("#x-cq").innerHTML = html`${p.note}<details><summary>질문 ${p.questions.length}개</summary><div class="table-wrap"><table><tr><th>#</th><th>종류</th><th>질문</th><th>기대 Cypher</th></tr>
    ${html.join(p.questions.map(q => html`<tr><td class="small nowrap">${q.id}</td><td class="small">${KIND[q.kind] || q.kind}</td><td class="small">${q.question}</td><td class="small mono">${q.cypher}</td></tr>`), "")}</table></div></details>`;
}
function renderCq(r) {
  $("#x-cq-out").innerHTML = html`<div class="row"><b>정확 일치 ${Math.round(r.exact * 100)}%</b> <span class="small muted">· 같은 개체를 다른 속성으로 돌려준 것까지 ${r.lenient == null ? "-" : `${Math.round(r.lenient * 100)}%`} · 겹침(Jaccard) ${r.jaccard} · 오류로 끝남 ${r.errors} · 다시 쓴 질문 ${r.retried} · 평균 ${r.seconds}초 · ${r.engine || ""} · ${r.llm?.model || ""}${r.run_id ? ` · run #${r.run_id}` : ""}</span></div>
    <div class="small">${html.join(Object.entries(r.by_kind).map(([k, v]) => html`<span class="badge">${KIND[k] || k} ${Math.round(v * 100)}%</span>`), " ")}</div>
    <div class="table-wrap scroll-lg"><table><tr><th>#</th><th>질문</th><th>결과</th><th>만든 Cypher</th></tr>
    ${html.join(r.rows.map(x => html`<tr><td class="small nowrap">${x.id}</td><td class="small">${x.question}</td>
      <td>${x.exact ? html`<span class="badge ok">일치</span>` : x.lenient ? html`<span class="badge ok">같은 답(다른 속성)</span>` : x.error ? html`<span class="badge err">오류</span>` : html`<span class="badge warn">${x.jaccard}</span>`}</td>
      <td class="small mono">${x.cypher}${x.attempts > 1 ? html` <span class="badge">${x.attempts}번째</span>` : ""}</td></tr>`), "")}</table></div>`;
}
$("#x-cq-run").onclick = e => runJobInto(e.target, "/api/kg/cq/eval", { engine: eng(), provider: $("#x-provider").value || null, model: $("#x-model").value.trim() || null }, $("#x-cq-progress"), renderCq).catch(() => {});

loadGraphs().catch(e => toast(e.message, "err"));
neo().catch(() => {});
loadCq().catch(e => ui.error($("#x-cq"), e));
