// search_lab/search_lab.html 화면 스크립트 (템플릿에서 옮김 — 화면 JS 는 static/js/<영역>/<화면>.js)
// 기법 이름은 서버(app/stages/search_lab/enhance.py TECHNIQUES)와 같게 둔다.
const TECHS = { none: "기법 없음 (기준선)", rewrite: "질의 재작성", hyde: "HyDE (가상 문서)", multi: "다중 질의" };
let detail = null;

$("#s-techs").innerHTML = html.join(Object.entries(TECHS).map(([k, v]) => html`<label class="row small m-0"><input type="checkbox" value="${k}" checked> ${v}</label>`), "");

async function loadCols() {
  const cols = await api("/api/collections");
  $("#s-col").innerHTML = html.or(html.join(cols.map(c => html`<option value="${c.id}">${c.name} (문서 ${c.n_documents})</option>`), ""), html`<option value="">컬렉션 없음</option>`);
  applyCtx($("#s-col"));
  await loadDetail();
}
async function loadDetail() {
  if (!$("#s-col").value) return;
  detail = await api(`/api/collections/${$("#s-col").value}`);
  const idx = detail.indexes.filter(i => i.status === "ready");
  const csName = id => detail.chunk_sets.find(c => c.id === id)?.name || `#${id}`;
  $("#s-idx").innerHTML = html.or(html.join(idx.map(i => html`<option value="${i.id}">${i.model_hf_id.split("/").pop()} · ${csName(i.chunk_set_id)}</option>`), ""), html`<option value="">준비된 인덱스 없음</option>`);
  applyCtx($("#s-idx"));
  $("#s-cs").innerHTML = html.join(detail.chunk_sets.filter(c => c.status === "ready").map(c => html`<option value="${c.id}">${c.name}</option>`), "");
  applyCtx($("#s-cs"));
  if (!idx.length) $("#s-mode").value = "bm25";
  modeChanged();
  const sets = (await api(`/api/collections/${detail.id}/eval-sets`)).filter(s => s.status === "ready");
  $("#e-set").innerHTML = html.or(html.join(sets.map(s => html`<option value="${s.id}">#${s.id} ${s.name} (${s.n_items}문항)</option>`), ""), html`<option value="">평가 세트 없음 (컬렉션 ⑤ 평가 탭에서 만드세요)</option>`);
  applyCtx($("#e-set"));
  $("#q-examples").innerHTML = "";
  // 문장 추출형 세트는 질문이 문서 문장 그대로라 향상 효과를 보기 어렵다 — 직접 · LLM 질문을 예시로 쓴다
  const ex = sets.find(s => s.method !== "sentence");
  if (ex) {
    const s = await api(`/api/eval-sets/${ex.id}`);
    $("#q-examples").innerHTML = '<span class="muted">예시:</span>' + s.items.slice(0, 6).map(it => html`<button class="btn sm" data-q="${it.query}">${it.query.slice(0, 40)}</button>`).join("");
    $$("[data-q]", $("#q-examples")).forEach(b => (b.onclick = () => { $("#q-text").value = b.dataset.q; }));
  }
}
function modeChanged() {
  const bm25 = $("#s-mode").value === "bm25";
  $("#s-idx-wrap").hidden = bm25; $("#s-cs-wrap").hidden = !bm25;
}
$("#s-col").addEventListener("change", () => { loadDetail(); });
$("#s-mode").addEventListener("change", modeChanged);

async function loadLlm() {
  const s = await api("/api/llm/status");
  $("#s-llm").innerHTML = s.default.error ? html`<span class="badge warn">LLM 미설정</span> 기준선만 동작합니다. <a href="/settings/llm">LLM 연결</a>에서 확인하세요.` : html`LLM 기본: <span class="mono">${s.default.model}</span>`;
  const rr = (await getModels()).filter(m => m.kind === "reranker" && m.cached);
  $("#s-rr").innerHTML += html.join(rr.map(r => html`<option value="${r.id}">${r.name}</option>`), "");
}

function configs() {
  const bm25 = $("#s-mode").value === "bm25";
  const base = { mode: $("#s-mode").value, index_id: bm25 ? null : +$("#s-idx").value || null, chunk_set_id: bm25 ? +$("#s-cs").value || null : null, reranker_id: +$("#s-rr").value || null };
  const techs = $$("#s-techs input:checked").map(x => x.value);
  return techs.map(t => ({
    ...base, label: TECHS[t],
    enhance: t === "none" ? null : { technique: t, keep_original: $("#s-keep").checked, n: +$("#s-n").value || 3, provider: $("#s-provider").value || null, model: $("#s-model").value.trim() || null },
  }));
}

$("#q-run").onclick = async e => {
  const query = $("#q-text").value.trim();
  if (!query) return toast("질문을 입력하세요", "err");
  const cfgs = configs();
  if (!cfgs.length) return toast("기법을 하나 이상 고르세요", "err");
  const r = await busy(e.target, () => api(`/api/collections/${detail.id}/search`, { method: "POST", body: { query, configs: cfgs } }));
  // 기준선(기법 없음)의 상위 결과와 겹치는지 표시해, 기법이 결과를 실제로 바꿨는지 한눈에 보이게 한다
  const baseIds = new Set((r.results.find(o => !o.config.enhance)?.results || []).map(x => x.chunk_id));
  $("#q-out").innerHTML = html.join(r.results.map(o => {
    if (o.error) return html`<div class="card stack"><b>${o.config.label}</b><div class="errbox">${o.error}</div></div>`;
    const en = o.enhance;
    const vars = en ? html`<div class="small stack gap-1">${html.join(en.variants.map(v => html`<div><span class="badge">${v.name}${v.role === "document" ? " · 문서로 인코딩" : ""}</span> ${v.text}</div>`), "")}</div>
      <div class="small muted">LLM ${en.cached ? "캐시 사용" : html`${en.llm_seconds}s`} · 검색 ${en.variants.length}회</div>` : "";
    return html`<div class="card stack"><div class="row between"><b>${o.config.label}</b><span class="small muted">${o.total_ms}ms</span></div>${vars}
      <ol class="small m-0" style="padding-left:20px">${html.join(o.results.slice(0, 5).map(x => html`<li>${en && !baseIds.has(x.chunk_id) ? html`<span class="badge ok">새로 찾음</span> ` : ""}<b>${x.filename}</b>${x.page ? html` p.${x.page}` : ""} <span class="muted">${x.text.slice(0, 120)}</span></li>`), "") || html`<li>결과 없음</li>`}</ol></div>`;
  }), "");
};

$("#e-run").onclick = async e => {
  if (!$("#e-set").value) return toast("평가 세트가 없습니다", "err");
  const cfgs = configs();
  if (!cfgs.length) return toast("기법을 하나 이상 고르세요", "err");
  const job = await busy(e.target, () => api(`/api/eval-sets/${$("#e-set").value}/evaluate`, { method: "POST", body: { configs: cfgs, max_queries: +$("#e-n").value || null } }));
  const box = $("#e-progress"); box.hidden = false; e.target.disabled = true;
  try {
    const done = await pollJob(job.id, j => { box.innerHTML = ui.jobProgress(j); }, 1500);
    if (done.status !== "done") { ui.error(box, done.status === "cancelled" ? "취소했습니다." : (done.error || done.status)); return; }
    box.hidden = true; renderEval(done.result);
  } finally { e.target.disabled = false; }
};

function renderEval(r) {
  const ok = r.results.filter(x => x.status === "ok");
  // '차이 불확실'을 꼭 함께 보여 준다 — 질문이 적으면 몇 %p 차이도 우연일 수 있어, 숫자만 보고 기법을 고르지 않게.
  const vs = x => (x.vs_best ? html`${(x.vs_best.diff * 100).toFixed(1)}%p ${x.vs_best.significant ? html`<span class="badge err">유의한 차이</span>` : html`<span class="badge">차이 불확실</span>`}` : ok.length > 1 ? "1위" : "");
  $("#e-out").innerHTML = html`<div class="row between"><h3>결과 · ${r.eval_set?.name || ""}</h3><span class="small muted">질문 ${r.n_queries}개${r.seconds != null ? html` · ${r.seconds}s` : ""}${r.run_id ? html` · <a href="/history">run #${r.run_id}</a>` : ""}</span></div>
    <div class="table-wrap"><table>
      <tr><th>#</th><th>설정</th><th class="num">nDCG@10</th><th class="num">95% 구간</th><th class="num">Hit@1</th><th class="num">Hit@5</th><th class="num">Hit@10</th><th class="num">지연 평균/p95</th><th>1위 대비</th></tr>
      ${html.join(ok.map((x, i) => html`<tr><td>${i + 1}</td><td class="small"><b>${x.label}</b></td><td class="num mono">${pct(x.metrics["ndcg@10"])}</td>
        <td class="num small">${x.ci?.["ndcg@10"] ? html`${pct(x.ci["ndcg@10"][0])}–${pct(x.ci["ndcg@10"][1])}` : "-"}</td>
        <td class="num">${pct(x.metrics["hit@1"])}</td><td class="num">${pct(x.metrics["hit@5"])}</td><td class="num">${pct(x.metrics["hit@10"])}</td>
        <td class="num small nowrap">${x.latency_ms.mean} / ${x.latency_ms.p95}ms</td><td class="small nowrap">${vs(x)}</td></tr>`), "")}
      ${html.join(r.results.filter(x => x.status !== "ok").map(x => html`<tr><td>-</td><td class="small">${x.label}</td><td colspan="7"><div class="errbox">${x.error}</div></td></tr>`), "")}
    </table></div>
    <div class="small muted">검색 지표는 % 단위. 지연에는 LLM 변형 생성 시간이 포함됩니다(캐시된 질문은 0).</div>`;
}

loadCols(); loadLlm();
