// 평가 · 관측 E7: A/B 실험 목록 · 만들기 · 질문 보내기 · 기록 재생 · 보고서(판정) · 멈추기
const ENH = { none: "끔", rewrite: "질의 재작성", hyde: "HyDE", multi: "다중 질의" };
let current = null, rerankers = [];

const ratio = v => (v == null ? "-" : `${Math.round(v * 1000) / 10}%`);
const ms = v => (v == null ? "-" : v >= 10000 ? `${(v / 1000).toFixed(1)}s` : `${Math.round(v)}ms`);
const money = v => (v == null ? "-" : v === 0 ? "0" : `$${Number(v).toFixed(v < 0.01 ? 6 : 4)}`);
// 보고서의 줄: [키, 이름, 값 형식, 차이 형식, 높을수록 좋은가]
const ROWS = [
  ["liked", "좋아요율", ratio, d => `${(d * 100).toFixed(1)}%p`, true],
  ["supported", "근거 일치", ratio, d => `${(d * 100).toFixed(1)}%p`, true],
  ["relevant", "질문 관련성", ratio, d => `${(d * 100).toFixed(1)}%p`, true],
  ["refused", "거절률", ratio, d => `${(d * 100).toFixed(1)}%p`, false],
  ["latency_ms", "지연 평균", ms, d => `${Math.round(d)}ms`, false],
  ["p95_ms", "지연 p95", ms, null, false],
  ["cost", "비용 (평균)", money, d => `${d < 0 ? "−" : ""}${money(Math.abs(d))}`, false],
  ["tokens", "토큰 (평균)", v => (v == null ? "-" : fmtNum(Math.round(v))), null, false],
];

// ── 목록 ───────────────────────────────────────────────────────────────────
async function loadList() {
  const box = $("#x-list");
  let rows;
  try { rows = await api("/api/evalops/experiments"); } catch (e) { return ui.error(box, e); }
  if (!rows.length) return ui.empty(box, "아직 실험이 없습니다. 아래 '새 실험 만들기'에서 두 설정을 정하세요.");
  box.innerHTML = html`<div class="table-wrap"><table><tr><th>#</th><th>이름</th><th>A / B</th><th class="num">B 비율</th><th class="num">요청</th><th>상태</th><th>만든 때</th><th></th></tr>
    ${rows.map(x => html`<tr${current?.id === x.id ? html` class="best"` : ""}><td class="mono">#${x.id}</td><td>${x.name}</td><td class="small">${x.arms.A} / ${x.arms.B}</td>
      <td class="num">${Math.round(x.split * 100)}%</td><td class="num">${fmtNum(x.n)}</td>
      <td>${x.status === "running" ? html`<span class="badge ok">진행 중</span>` : html`<span class="badge muted">멈춤</span>`}</td>
      <td class="small">${fmtDate(x.created_at)}</td><td><button class="btn sm" data-open="${x.id}">보기</button></td></tr>`)}</table></div>`;
}
$("#x-list").addEventListener("click", e => { const b = e.target.closest("[data-open]"); if (b) openExp(+b.dataset.open); });
$("#x-reload").onclick = () => { loadList(); if (current) openExp(current.id); };

// ── 상세 · 보고서 ──────────────────────────────────────────────────────────
function armSummary(k, a) {
  const c = a.config || {};
  const rr = rerankers.find(r => r.id === c.reranker_id);
  return html`<div class="stack"><b>${k} · ${a.label || k}</b><div class="small">${c.mode}${c.index_id ? html` · 인덱스 #${c.index_id}` : ""}${c.chunk_set_id ? html` · 청크 세트 #${c.chunk_set_id}` : ""}
    · 리랭커 ${c.reranker_id ? (rr?.name ?? `#${c.reranker_id}`) : "없음"} · 검색 향상 ${ENH[c.enhance?.technique || "none"]}<br>
    LLM ${a.provider || "기본"}${a.model ? html` · <span class="mono">${a.model}</span>` : ""} · 근거 ${a.context_top} · 최대 토큰 ${a.max_tokens}</div></div>`;
}
function renderReport(r) {
  const A = r.arms.A, B = r.arms.B;
  const diffCell = (key, fmt, higherBetter) => {
    const d = r.diff[key];
    if (!d || !fmt) return "";
    const good = d.diff === 0 ? null : (d.diff > 0) === higherBetter;
    const tag = d.significant ? html`<span class="badge ${good ? "ok" : "err"}">유의</span>` : html`<span class="badge muted">불확실</span>`;
    return html`<span class="mono">${d.diff >= 0 ? "+" : "−"}${fmt(Math.abs(d.diff))}</span> <span class="small muted">[${fmt(d.ci[0])}, ${fmt(d.ci[1])}]</span> ${tag}`;
  };
  return html`<div class="${/낮음/.test(r.verdict) ? "errbox" : /높음|빠름/.test(r.verdict) ? "card" : "warnbox"}"><b>판정:</b> ${r.verdict}</div>
    <div class="table-wrap"><table><tr><th>지표</th><th class="num">A · ${A.label}</th><th class="num">B · ${B.label}</th><th>B − A (95% 구간)</th></tr>
      <tr><td>요청 (피드백)</td><td class="num">${fmtNum(A.n)} (${A.n_feedback})</td><td class="num">${fmtNum(B.n)} (${B.n_feedback})</td><td></td></tr>
      ${ROWS.map(([k, name, fmt, dfmt, hb]) => html`<tr><td>${name}</td><td class="num">${fmt(A[k])}</td><td class="num">${fmt(B[k])}</td><td>${diffCell(k, dfmt, hb)}</td></tr>`)}</table></div>
    <div class="small muted">팔이 달라 짝지을 수 없어 두 팔 평균 차이를 부트스트랩으로 봅니다. 근거 일치 · 질문 관련성은 거절한 답을 빼고 셉니다. 요청이 적으면 대부분 '불확실'입니다.</div>`;
}
async function openExp(id) {
  let x;
  try { x = await api(`/api/evalops/experiments/${id}`); } catch (e) { return toast(e.message, "err"); }
  current = x;
  $("#x-detail").hidden = false;
  $("#x-title").textContent = `#${x.id} ${x.name}`;
  $("#x-status").innerHTML = x.status === "running" ? html`<span class="badge ok">진행 중</span>` : html`<span class="badge muted">멈춤</span>`;
  $("#x-stop").hidden = x.status !== "running";
  $("#x-ask").disabled = $("#x-replay").disabled = x.status !== "running";
  const cfg = x.arm_config || {};
  $("#x-arms").innerHTML = html`${x.notes ? html`<div class="small muted pre">${x.notes}</div>` : ""}<div class="grid cols-2">${Object.keys(cfg).length ? ["A", "B"].map(k => armSummary(k, cfg[k] || {})) : ""}</div>
    <div class="small muted">B 로 보낼 비율 ${Math.round(x.split * 100)}%${x.collection_id ? html` · 컬렉션 <a href="/rag/collections/${x.collection_id}">#${x.collection_id}</a>` : ""}</div>`;
  $("#x-report").innerHTML = renderReport(x);
  const sets = x.collection_id ? await api(`/api/evalops/sets?collection_id=${x.collection_id}`).catch(() => []) : [];
  $("#x-set").innerHTML = html.or(html.join(sets.map(s => html`<option value="${s.id}">#${s.id} ${s.name} (${s.n_items}문항)</option>`)), html`<option value="">평가 세트 없음</option>`);
  loadList();
}
$("#x-stop").onclick = async e => {
  if (!(await ui.confirm("이 실험을 멈출까요? 더는 질문을 보낼 수 없고, 지금까지의 기록과 보고서는 남습니다.", { ok: "멈추기", danger: true }))) return;
  await busy(e.target, () => api(`/api/evalops/experiments/${current.id}/stop`, { method: "POST" }));
  openExp(current.id);
};
$("#x-ask").onclick = e => {
  const q = $("#x-q").value.trim();
  if (!q) return;
  return busy(e.target, async () => {
    const r = await api(`/api/evalops/experiments/${current.id}/ask`, { method: "POST", body: { question: q, key: $("#x-key").value.trim() } });
    const v = r.verify || {};
    $("#x-ask-out").innerHTML = html`<div class="card stack mt-2"><div class="row"><span class="badge">팔 ${r.arm} · ${r.label}</span>
        <span class="small muted">${ms(r.total_ms)} · 근거 일치 ${ratio(v.supported_ratio)} · 질문 관련성 ${ratio(v.relevant_ratio)}${v.refused ? " · 거절" : ""}</span>
        <a class="small" href="/evalops/traces?trace=${r.trace_id}">요청 #${r.trace_id}</a></div>
      <div class="answer pre">${r.answer}</div>
      <details><summary class="small">근거 ${r.sources.length}개</summary>${r.sources.map((s, i) => html`<div class="small"><span class="cite">${i + 1}</span> ${s.filename}${s.page ? html` p.${s.page}` : ""}</div>`)}</details></div>`;
    openExp(current.id);
  }).catch(() => {});
};
$("#x-replay").onclick = e => {
  if (!$("#x-set").value) return toast("이 컬렉션에 평가 세트가 없습니다.", "err");
  const body = { eval_set_id: +$("#x-set").value, max_queries: +$("#x-n").value || 20, seed: +$("#x-seed").value || 0 };
  return runJobInto(e.target, `/api/evalops/experiments/${current.id}/replay`, body, $("#x-progress"), r => {
    toast(`재생: A ${r.replayed.A} · B ${r.replayed.B}`, "ok");
    openExp(current.id);
  }).catch(() => {});
};

// ── 새 실험 ────────────────────────────────────────────────────────────────
function fillArms(d) {
  const idx = d.indexes.filter(i => i.status === "ready"), cs = d.chunk_sets.filter(c => c.status === "ready");
  for (const arm of ["a", "b"]) {
    $(`#n-${arm}-idx`).innerHTML = html.or(html.join(idx.map(i => html`<option value="${i.id}">${i.model_hf_id.split("/").pop()} · #${i.id}</option>`)), html`<option value="">준비된 인덱스 없음</option>`);
    $(`#n-${arm}-cs`).innerHTML = html.or(html.join(cs.map(c => html`<option value="${c.id}">${c.name}</option>`)), html`<option value="">청크 세트 없음</option>`);
    if (!idx.length) $(`#n-${arm}-mode`).value = "bm25";
    armMode(arm);
  }
}
function armMode(arm) {
  const b = $(`#n-${arm}-mode`).value === "bm25";
  $(`#n-${arm}-idx-wrap`).hidden = b; $(`#n-${arm}-cs-wrap`).hidden = !b;
}
$$("[data-mode]").forEach(sel => sel.addEventListener("change", () => armMode(sel.dataset.mode)));
function armBody(arm) {
  const v = s => $(`#n-${arm}-${s}`).value, bm25 = v("mode") === "bm25";
  return {
    label: v("label").trim(), provider: v("provider") || null, model: v("model").trim() || null,
    context_top: +v("top") || 5, max_tokens: +v("max") || 500,
    config: { mode: v("mode"), index_id: bm25 ? null : +v("idx") || null, chunk_set_id: bm25 ? +v("cs") || null : null, reranker_id: +v("rr") || null,
      enhance: v("enh") === "none" ? null : { technique: v("enh") } },
  };
}
$("#n-create").onclick = e => {
  const body = { name: $("#n-name").value.trim(), collection_id: +$("#n-col").value || null, split: +$("#n-split").value || 0.5, notes: $("#n-notes").value, a: armBody("a"), b: armBody("b") };
  if (!body.name) return toast("이름을 입력하세요.", "err");
  if (!body.collection_id) return toast("컬렉션이 없습니다.", "err");
  for (const [k, a] of [["A", body.a], ["B", body.b]]) {
    if (a.config.mode !== "bm25" && !a.config.index_id) return toast(`팔 ${k}: 벡터 인덱스가 없습니다. BM25 를 고르거나 인덱스를 만드세요.`, "err");
    if (a.config.mode === "bm25" && !a.config.chunk_set_id) return toast(`팔 ${k}: 청크 세트가 없습니다.`, "err");
  }
  return busy(e.target, async () => {
    const r = await api("/api/evalops/experiments", { method: "POST", body });
    toast(`실험 #${r.id} 를 만들었습니다.`, "ok");
    $("#n-card").open = false;
    await openExp(r.id);
    $("#x-detail").scrollIntoView({ behavior: "smooth", block: "start" });
  }).catch(() => {});
};

setupCollectionPickers({ col: $("#n-col"), onDetail: fillArms }).catch(e => toast(e.message, "err"));
(async () => {
  rerankers = (await getModels()).filter(m => m.kind === "reranker" && m.cached);
  $$("[data-rr]").forEach(sel => { sel.innerHTML += html.join(rerankers.map(r => html`<option value="${r.id}">${r.name}</option>`)); });
  await loadList();
  // 요청 기록 화면의 ?exp= 링크로 들어오면 그 실험을 바로 연다
  const want = new URLSearchParams(location.search).get("exp");
  if (want) openExp(+want);
})();
