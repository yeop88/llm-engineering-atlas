// lineage/graph.html 화면 스크립트 — 계보 관계를 관계 종류별로, 두 모델의 바뀐 점(LN2 · LN4)
const REL = { BELONGS_TO: "계열", MADE_BY: "제작사", HAS_ARCHITECTURE: "구조", SUPPORTS_MODALITY: "모달리티", LICENSED_UNDER: "라이선스",
  QUANTIZED_FROM: "양자화한 원본", DERIVED_FROM: "기반 모델", SUCCEEDS: "앞 세대" };

api("/api/lineage/graph").then(g => {
  const label = Object.fromEntries(g.nodes.map(n => [n.id, n.label]));
  const models = g.nodes.filter(n => n.type === "Model" && !n.base);
  if (!models.length) { ui.empty($("#g-out"), "읽은 모델이 없습니다 — '모델 계보' 화면에서 먼저 읽으세요."); return; }
  $("#g-out").innerHTML = html`<div class="table-wrap"><table><tr><th>모델</th>${Object.values(REL).map(r => html`<th>${r}</th>`)}</tr>
    ${html.join(models.map(m => html`<tr><td class="small">${m.label}</td>${Object.keys(REL).map(rel => html`<td class="small">${g.edges.filter(e => e.a === m.id && e.rel === rel).map(e => label[e.b]).join(" · ") || "-"}</td>`)}</tr>`), "")}</table></div>`;
  const opts = html`${models.map(m => html`<option value="${m.id}">${m.label}</option>`)}`;
  $("#c-a").innerHTML = opts;
  $("#c-b").innerHTML = opts;
  if (models.length > 1) $("#c-b").selectedIndex = 1;
}).catch(err => ui.error($("#g-out"), err));

$("#c-run").onclick = e => busy(e.target, () => api(`/api/lineage/compare?a=${encodeURIComponent($("#c-a").value)}&b=${encodeURIComponent($("#c-b").value)}`)).then(r => {
  $("#c-out").innerHTML = r.changes.length ? html`<div class="table-wrap"><table><tr><th>항목</th><th>A</th><th>B</th></tr>
    ${html.join(r.changes.map(c => html`<tr><td>${c.field}</td><td class="small">${JSON.stringify(c.a)}</td><td class="small">${JSON.stringify(c.b)}</td></tr>`), "")}</table></div>`
    : html`<div class="small muted">구조 · 맥락 · 모달리티 · 라이선스가 같습니다(같은 모델의 다른 비트일 수 있음).</div>`;
}).catch(err => ui.error($("#c-out"), err));
