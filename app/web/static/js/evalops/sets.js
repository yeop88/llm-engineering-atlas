// 평가 · 관측 E1 · E2: 평가 세트 판 · 문항 검토 · 회귀 세트 지정 · 기준선 · 회귀 실행 · 실행 이력
const REVIEW = { pending: ["", "검토 전"], ok: ["ok", "통과"], excluded: ["muted", "제외"] };
const METRICS = ["ndcg@10", "hit@1", "hit@5", "mrr@10"];
const ACTION = { review: "검토", add: "문항 추가", baseline: "기준선", regression: "회귀 지정" };
let sets = [], current = null, runs = [];

const num = v => (v == null ? "-" : Number(v).toFixed(3));
// 짝지은 차이: 값 · 95% 구간 · 유의 여부 — 하락만 경보 색(상승은 좋은 소식이라 ok)
function diffCell(d) {
  if (!d) return "-";
  const tag = d.significant ? (d.diff < 0 ? html`<span class="badge err">유의한 하락</span>` : html`<span class="badge ok">유의한 상승</span>`) : html`<span class="badge muted">불확실</span>`;
  return html`<span class="mono">${d.diff >= 0 ? "+" : ""}${num(d.diff)}</span> <span class="small muted">[${num(d.ci?.[0])}, ${num(d.ci?.[1])}]</span> ${tag}`;
}
const reviewBadges = r => html.join(Object.entries(REVIEW).map(([k, [cls, lab]]) => html`<span class="badge ${cls}">${lab} ${r?.[k] ?? 0}</span>`), " ");

function searchConfig() {
  const bm25 = $("#s-mode").value === "bm25";
  return { mode: $("#s-mode").value, index_id: bm25 ? null : +$("#s-idx").value || null, chunk_set_id: bm25 ? +$("#s-cs").value || null : null,
    reranker_id: +$("#s-rr").value || null, top_k: +$("#s-top").value || 10 };
}
function modeChanged() { const b = $("#s-mode").value === "bm25"; $("#s-idx-wrap").hidden = b; $("#s-cs-wrap").hidden = !b; }
$("#s-mode").addEventListener("change", modeChanged);

// ── 세트 목록 ──────────────────────────────────────────────────────────────
async function loadSets() {
  const box = $("#s-list");
  if (!$("#s-col").value) return ui.empty(box, "컬렉션이 없습니다. 먼저 컬렉션을 만들고 평가 세트를 만드세요.", { href: "/rag/collections", label: "컬렉션으로" });
  ui.loading(box);
  try {
    sets = await api(`/api/evalops/sets?collection_id=${$("#s-col").value}`);
  } catch (e) { return ui.error(box, e); }
  if (!sets.length) return ui.empty(box, "이 컬렉션에 준비된 평가 세트가 없습니다. 컬렉션 화면의 평가 탭에서 만들거나, 피드백 · 개선 루프에서 요청 기록을 후보로 보내세요.", { href: `/rag/collections/${$("#s-col").value}`, label: "컬렉션 열기" });
  box.innerHTML = html`<div class="table-wrap"><table><tr><th>세트</th><th class="num">문항</th><th class="num">판</th><th>검토</th><th>회귀</th><th>기준선</th><th></th></tr>
    ${sets.map(s => html`<tr${current?.id === s.id ? html` class="best"` : ""}>
      <td><b>#${s.id}</b> ${s.name} <span class="small muted">${s.method}</span></td>
      <td class="num">${fmtNum(s.n_items)}</td><td class="num">v${s.version}</td>
      <td class="small">${reviewBadges(s.review)}</td>
      <td><label class="row small m-0"><input type="checkbox" data-reg="${s.id}" ${s.regression ? "checked" : ""}> 회귀 세트</label></td>
      <td class="small">${s.baseline ? html`${s.baseline.label || "기준선"} · v${s.baseline.version} · ${fmtDate(s.baseline.at)}<br><span class="muted">nDCG@10 ${num(s.baseline.metrics?.["ndcg@10"])} · 문항 ${s.baseline.metrics?.n ?? "-"}</span>` : html`<span class="muted">없음</span>`}</td>
      <td><button class="btn sm" data-open="${s.id}">문항 · 기준선</button></td></tr>`)}</table></div>`;
}
$("#s-list").addEventListener("change", async e => {
  const cb = e.target.closest("[data-reg]");
  if (!cb) return;
  try {
    await api(`/api/evalops/sets/${cb.dataset.reg}/regression`, { method: "POST", body: { on: cb.checked } });
    toast(cb.checked ? "회귀 세트로 지정했습니다." : "회귀 세트에서 뺐습니다.", "ok");
    await loadSets();
  } catch (err) { cb.checked = !cb.checked; toast(err.message, "err"); }
});
$("#s-list").addEventListener("click", e => { const b = e.target.closest("[data-open]"); if (b) openSet(+b.dataset.open); });
$("#s-reload").onclick = () => loadSets();

// ── 세트 상세: 문항 검토 · 기준선 · 이력 ─────────────────────────────────────
async function openSet(id) {
  try { current = await api(`/api/evalops/sets/${id}`); } catch (e) { return toast(e.message, "err"); }
  $("#d-card").hidden = false;
  $("#d-title").textContent = `#${current.id} ${current.name}`;
  $("#d-meta").textContent = `v${current.version} · 문항 ${current.n_items}${current.regression ? " · 회귀 세트" : ""}`;
  $("#d-baseline-out").innerHTML = current.baseline ? baselineInfo(current.baseline) : html`<div class="small muted">기준선이 없습니다 — 회귀를 재려면 먼저 만드세요.</div>`;
  renderItems();
  $("#d-history").innerHTML = html.or(html.join((current.history || []).slice().reverse().map(h => html`<div class="small">v${h.version} · ${fmtDate(h.at)} · ${ACTION[h.action] || h.action}
    ${h.item != null ? html` · 문항 ${h.item} ${REVIEW[h.from]?.[1] ?? h.from} → ${REVIEW[h.to]?.[1] ?? h.to}` : ""}${h.n ? html` · ${h.n}개 (${h.source})` : ""}${h.label ? html` · ${h.label}` : ""}${h.on != null ? html` · ${h.on ? "켬" : "끔"}` : ""}</div>`)), html`<div class="small muted">이력 없음</div>`);
  loadSets();
  $("#d-card").scrollIntoView({ behavior: "smooth", block: "start" });
}
function baselineInfo(b) {
  const m = b.metrics || {};
  return html`<div class="small">기준선 <b>${b.label || "(이름 없음)"}</b> · 판 v${b.version} · ${fmtDate(b.at)}${b.run_id ? html` · run #${b.run_id}` : ""}<br>
    ${html.join(METRICS.map(k => html`${k} <span class="mono">${num(m[k])}</span>`), " · ")}${m.ci ? html` <span class="muted">(nDCG@10 95% 구간 ${num(m.ci[0])} ~ ${num(m.ci[1])}, 문항 ${m.n})</span>` : ""}</div>`;
}
function renderItems() {
  const f = $("#d-filter").value;
  const items = current.items.filter(it => !f || (it.review || "pending") === f);
  const box = $("#d-items");
  if (!items.length) return ui.empty(box, "이 상태의 문항이 없습니다.");
  box.innerHTML = html`<div class="table-wrap scroll-lg"><table><tr><th>#</th><th>질문</th><th>유형</th><th>정답 문서</th><th>검토</th><th></th></tr>
    ${items.map(it => {
      const r = it.review || "pending";
      return html`<tr><td class="small mono">${it.id}</td>
        <td class="small">${it.query}${it.evidence ? html`<div class="muted">근거: ${String(it.evidence).slice(0, 120)}</div>` : ""}${it.review_note ? html`<div class="muted">메모: ${it.review_note}</div>` : ""}</td>
        <td class="small">${it.type || "-"}${it.source ? html`<div class="muted">${it.source}</div>` : ""}${it.answerable === false ? html` <span class="badge muted">답 없음</span>` : ""}</td>
        <td class="small">${(it.doc_ids || []).length ? html.join(it.doc_ids, ", ") : html`<span class="badge warn" title="정답 문서가 없으면 검색 지표에서 빠집니다">채워야 함</span>`}</td>
        <td><span class="badge ${REVIEW[r][0]}">${REVIEW[r][1]}</span></td>
        <td class="nowrap">${r !== "ok" ? html`<button class="btn sm" data-review="ok" data-item="${it.id}">통과</button>` : ""}
          ${r !== "excluded" ? html`<button class="btn sm" data-review="excluded" data-item="${it.id}">제외</button>` : ""}
          ${r !== "pending" ? html`<button class="btn sm" data-review="pending" data-item="${it.id}">되돌리기</button>` : ""}</td></tr>`;
    })}</table></div>`;
}
$("#d-filter").addEventListener("change", () => current && renderItems());
$("#d-items").addEventListener("click", async e => {
  const b = e.target.closest("[data-review]");
  if (!b) return;
  // 제외는 회귀에서 빠지므로 기준선과 비교되는 문항 수가 줄어든다 — 한 번 묻는다
  if (b.dataset.review === "excluded" && !(await ui.confirm("이 문항을 제외할까요? 회귀 평가에서 빠지고 판이 올라갑니다(언제든 되돌릴 수 있음).", { ok: "제외" }))) return;
  await busy(b, async () => {
    const r = await api(`/api/evalops/sets/${current.id}/review`, { method: "POST", body: { item_id: b.dataset.item, status: b.dataset.review, note: $("#d-note").value.trim() } });
    $("#d-note").value = "";
    toast(`문항 ${b.dataset.item}: ${REVIEW[b.dataset.review][1]} (v${r.version})`, "ok");
  });
  openSet(current.id);
});

$("#d-baseline").onclick = async e => {
  if (!current) return;
  const cfg = searchConfig();
  if (cfg.mode !== "bm25" && !cfg.index_id) return toast("벡터 인덱스가 없습니다. BM25 를 고르거나 인덱스를 만드세요.", "err");
  if (current.baseline && !(await ui.confirm(`이미 기준선(${current.baseline.label || fmtDate(current.baseline.at)})이 있습니다. 새 기준선으로 바꾸면 다음 회귀부터 새 기준과 비교합니다.`, { ok: "기준선 바꾸기", danger: true }))) return;
  await runJobInto(e.target, `/api/evalops/sets/${current.id}/baseline`, { config: cfg, label: $("#d-label").value.trim() }, $("#d-progress"), res => {
    toast(`기준선을 만들었습니다 (run #${res.run_id})`, "ok");
    openSet(current.id);
    loadRuns();
  });
};

// ── 회귀 실행 ──────────────────────────────────────────────────────────────
function renderResults(results, alerts) {
  if (!results?.length) return html`<div class="small muted">결과 없음</div>`;
  const items = Object.fromEntries((current?.items || []).map(it => [String(it.id), it.query]));
  return html`${alerts?.length ? html`<div class="errbox" role="alert">경보: ${html.join(alerts, ", ")} — 기준선보다 유의하게 나빠졌습니다.</div>` : html`<div class="small"><span class="badge ok">경보 없음</span></div>`}
    ${results.map(r => {
      if (r.error) return html`<div class="warnbox">#${r.eval_set.id} ${r.eval_set.name}: ${r.error}</div>`;
      const v = r.vs_baseline, m = r.metrics || {};
      const sameSet = current && current.id === r.eval_set.id;
      return html`<div class="card stack mt-2">
        <div class="row between"><b>#${r.eval_set.id} ${r.eval_set.name} <span class="small muted">v${r.eval_set.version}</span></b>
          ${v ? (v.alert ? html`<span class="badge err">경보 · 유의한 하락</span>` : v.improved ? html`<span class="badge ok">유의한 상승</span>` : html`<span class="badge muted">유의한 차이 없음</span>`) : html`<span class="badge muted">기준선 없음</span>`}</div>
        ${v && !v.same_version ? html`<div class="warnbox small">기준선은 v${v.baseline_version} 에서 만들었고 세트는 지금 v${r.eval_set.version} 입니다 — 짝지은 ${v.n_paired}문항만 비교했습니다.</div>` : ""}
        <div class="table-wrap"><table><tr><th>지표</th><th class="num">이번</th><th>기준선 대비 (같은 질문끼리 · 95% 구간)</th></tr>
          ${METRICS.filter(k => k in m).map(k => html`<tr><td>${k}</td><td class="num mono">${num(m[k])}</td><td>${v ? diffCell(v[k]) : "-"}</td></tr>`)}</table></div>
        ${v?.worst?.length ? html`<details><summary class="small">가장 많이 떨어진 문항 ${v.worst.length}개</summary><div class="table-wrap mt-2"><table><tr><th>#</th><th>질문</th><th>유형</th><th class="num">nDCG 차이</th></tr>
          ${v.worst.map(w => html`<tr><td class="mono small">${w.id}</td><td class="small">${sameSet ? items[String(w.id)] ?? "" : html`<span class="muted">세트를 열면 질문이 보입니다</span>`}</td><td class="small">${w.type || "-"}</td><td class="num mono">${num(w.diff)}</td></tr>`)}</table></div></details>` : ""}
        ${v?.by_type && Object.keys(v.by_type).length > 1 ? html`<div class="small muted">유형별 평균 차이: ${html.join(Object.entries(v.by_type).map(([t, x]) => html`${t} ${x.diff >= 0 ? "+" : ""}${num(x.diff)} (${x.n})`), " · ")}</div>` : ""}
        <div class="small muted">문항 ${m.n ?? "-"} · 짝지음 ${v?.n_paired ?? "-"} · 설정 ${r.config?.mode ?? ""}${r.config?.index_id ? html` · 인덱스 #${r.config.index_id}` : ""}${r.config?.reranker_id ? html` · 리랭커 #${r.config.reranker_id}` : ""}</div>
      </div>`;
    })}`;
}
$("#g-run").onclick = async e => {
  let setIds = [];
  if ($("#g-scope").value === "one") {
    if (!current) return toast("먼저 위 목록에서 세트를 여세요.", "err");
    setIds = [current.id];
  }
  const body = { set_ids: setIds, config: $("#g-changed").checked ? searchConfig() : null, update_baseline: $("#g-update").checked };
  if (body.update_baseline && !(await ui.confirm("재고 나서 기준선을 이번 결과로 바꿉니다. 나빠진 결과로 갱신하면 다음 회귀가 그 상태를 기준으로 삼습니다.", { ok: "실행 · 기준선 갱신", danger: true }))) return;
  await runJobInto(e.target, "/api/evalops/regression/run", body, $("#g-progress"), res => {
    $("#g-out").innerHTML = html`<div class="small muted">run #${res.run_id} · ${res.seconds}s</div>${renderResults(res.results, res.alerts)}`;
    loadRuns();
    if (body.update_baseline) loadSets();
  });
};

// ── 실행 이력 ──────────────────────────────────────────────────────────────
async function loadRuns() {
  const box = $("#h-list");
  try { runs = await api("/api/evalops/regression/runs"); } catch (e) { return ui.error(box, e); }
  if (!runs.length) return ui.empty(box, "아직 회귀 실행이 없습니다. 세트를 열어 기준선을 만든 뒤 회귀를 실행하세요.");
  box.innerHTML = html`<div class="table-wrap scroll-md"><table><tr><th>run</th><th>시각</th><th>내용</th><th>경보</th><th></th></tr>
    ${runs.map(r => html`<tr><td class="mono">#${r.id}</td><td class="small">${fmtDate(r.created_at)}</td><td class="small">${r.title}${r.params?.baseline ? html` <span class="badge">기준선</span>` : ""}${r.params?.reason && r.params.reason !== "manual" ? html` <span class="badge muted">${r.params.reason}</span>` : ""}</td>
      <td>${r.alerts?.length ? html`<span class="badge err">${html.join(r.alerts, ", ")}</span>` : r.params?.baseline ? "" : html`<span class="badge ok">없음</span>`}</td>
      <td>${r.results ? html`<button class="btn sm" data-run="${r.id}">결과</button>` : ""}</td></tr>`)}</table></div>`;
}
$("#h-list").addEventListener("click", e => {
  const b = e.target.closest("[data-run]");
  if (!b) return;
  const r = runs.find(x => x.id === +b.dataset.run);
  $("#h-detail").innerHTML = html`<h3 class="mt-2">run #${r.id} · ${fmtDate(r.created_at)}</h3>${renderResults(r.results, r.alerts)}`;
});
$("#h-reload").onclick = () => loadRuns();

// 시작: 컬렉션 → 인덱스 · 청크 세트(작업 맥락), 리랭커, 이력. 주소의 ?set= 이 있으면 그 세트를 바로 연다(피드백 화면의 링크)
(async () => {
  const d = await setupCollectionPickers({ col: $("#s-col"), idx: $("#s-idx"), cs: $("#s-cs"), onDetail: d => { if (!d.indexes.some(i => i.status === "ready")) $("#s-mode").value = "bm25"; modeChanged(); loadSets(); } }).catch(e => { ui.error($("#s-list"), e); return null; });
  if (!d) loadSets();
  const want = new URLSearchParams(location.search).get("set");
  if (want) openSet(+want);
})();
(async () => {
  const rr = (await getModels()).filter(m => m.kind === "reranker" && m.cached);
  $("#s-rr").innerHTML += html.join(rr.map(r => html`<option value="${r.id}">${r.name}</option>`), "");
})();
loadRuns();
