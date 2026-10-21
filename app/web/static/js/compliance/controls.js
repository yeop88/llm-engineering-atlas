// compliance/controls.html 화면 스크립트 — 조항-통제 그래프(RC7) 만들기 · 보기, 개정 감시(현행 · 시행예정 판과 조항 비교) → 영향받는 통제 · 기능
const col = () => $("#g-col").value;

async function loadOverview() {
  const o = await api("/api/compliance/graph");
  if (!o.built) { ui.empty($("#g-overview"), "아직 그래프가 없습니다 — 규제 자료 컬렉션을 고르고 '그래프 다시 만들기'"); $("#g-stats").innerHTML = ""; return; }
  const s = o.stats;
  $("#g-stats").innerHTML = html`노드 ${fmtNum(s.nodes)} · 관계 ${fmtNum(s.edges)} — ${html.join(Object.entries(s.types).map(([k, v]) => html`<span class="badge">${k} ${fmtNum(v)}</span>`), " ")}`;
  $("#g-overview").innerHTML = html`<div class="table-wrap scroll-lg"><table><tr><th>통제</th><th>근거 조항</th><th>적용 기능</th></tr>
    ${html.join(o.controls.map(c => html`<tr><td class="small"><b>${c.name}</b> <span class="muted">${c.kind}</span>${c.implemented ? "" : html` <span class="badge warn">없음</span>`}</td>
      <td class="small">${c.articles.length ? c.articles.join(" · ") : html`<span class="muted">규칙에 걸린 조항 없음</span>`}</td>
      <td class="small">${c.features.join(" · ")}</td></tr>`), "")}</table></div>`;
}

function impactHtml(imp) {
  if (!imp) return "";
  return html`<div class="small">영향받는 통제 ${imp.controls.length}개 · 기능 ${imp.features.length}개${imp.features.length ? html` — ${imp.features.join(" · ")}` : ""}</div>
    ${imp.controls.length ? html`<ul class="small">${html.join(imp.controls.map(c => html`<li><b>${c.name}</b> ← ${c.articles.join(" · ")} <span class="muted">(${c.features.join(" · ")})</span></li>`), "")}</ul>` : ""}`;
}

function diffHtml(d, label) {
  if (!d) return "";
  const n = d.changed.length + d.added.length + d.removed.length;
  const list = (xs, cls, word) => xs.length ? html`<div class="small"><span class="badge ${cls}">${word} ${xs.length}</span> ${html.join(xs.map(x => html`<span title="${x.title}">${x.no}</span>`), " · ")}</div>` : "";
  return html`<div class="mt-2"><b>${label} ${d.enforced}</b> <span class="small muted">조항 ${n}개 다름</span>
    ${list(d.changed, "warn", "바뀜")}${list(d.added, "ok", "새로 생김")}${list(d.removed, "err", "없어짐")}${impactHtml(d.impact)}</div>`;
}

function renderRev(r) {
  $("#g-rev-out").innerHTML = html`${r.graph_built ? "" : html`<div class="small muted">그래프를 만들면 바뀐 조항마다 영향받는 통제 · 기능도 함께 보입니다.</div>`}
    ${html.join(r.laws.map(l => html`<div class="card stack mt-2"><div class="row"><b>${l.law}</b>
      <span class="small">자료의 판 ${l.have}${l.current ? ` · 현행 ${l.current}` : ""}${l.upcoming?.length ? ` · 시행예정 ${l.upcoming.join(", ")}` : ""}</span>
      ${l.error ? html`<span class="badge err">${l.error}</span>` : l.outdated ? html`<span class="badge warn">현행보다 오래됨</span>` : html`<span class="badge ok">현행</span>`}</div>
      ${diffHtml(l.current_diff, "현행")}${diffHtml(l.upcoming_diff, "시행예정")}</div>`), "")}`;
}

$("#g-build").onclick = async e => {
  if (!col()) return toast("규제 자료 컬렉션을 고르세요", "err");
  const r = await busy(e.target, () => api("/api/compliance/graph/build", { method: "POST", body: { collection_id: +col() } })).catch(err => toast(err.message, "err"));
  if (!r) return;
  toast(`그래프를 만들었습니다 — 노드 ${fmtNum(r.stats.nodes)} · 관계 ${fmtNum(r.stats.edges)}${r.missing_articles.length ? ` · 자료에 없는 조항 ${r.missing_articles.length}` : ""}`);
  loadOverview();
};
$("#g-rev").onclick = e => {
  if (!col()) return toast("규제 자료 컬렉션을 고르세요", "err");
  ui.loading($("#g-rev-out"), "판 목록 · 원문을 받는 중… (법령마다 몇 초)");
  busy(e.target, () => api(`/api/compliance/corpus/${col()}/revisions`)).then(renderRev).catch(err => ui.error($("#g-rev-out"), err));
};
$("#g-impact").onclick = e => {
  const keys = $("#g-keys").value.split("\n").map(s => s.trim()).filter(Boolean);
  if (!keys.length) return toast("조항을 입력하세요", "err");
  busy(e.target, () => api("/api/compliance/graph/impact", { method: "POST", body: { keys } }))
    .then(r => { $("#g-impact-out").innerHTML = html`${r.unmatched.length ? html`<div class="small"><span class="badge warn">그래프에 없음</span> ${r.unmatched.join(" · ")}</div>` : ""}${impactHtml(r)}`; })
    .catch(err => ui.error($("#g-impact-out"), err));
};

setupCollectionPickers({ col: $("#g-col") }).catch(() => {});
loadOverview().catch(e => ui.error($("#g-overview"), e));
