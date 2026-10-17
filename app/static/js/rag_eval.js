// 컬렉션 상세 ⑤ 평가: 평가 세트 만들기·검토 (rag.js 의 col · load 를 함께 쓴다)
let evSets = [];
let evTimer = null;
const EV_METHOD = { llm: "LLM 생성", sentence: "문장 추출", manual: "직접 입력", import: "가져오기" };
const EV_TYPE = { fact: "사실 확인", paraphrase: "다른 표현", situation: "상황 설명형", sentence: "문장 그대로", manual: "직접 입력" };
const EV_HINT = {
  llm: "청크 세트에서 문서마다 골고루 지문을 골라, 지문마다 고른 유형별로 질문 하나와 근거 문장을 만듭니다. 정답은 문서와 근거 문장으로 기록하므로 다른 청크 세트·인덱스 평가에도 그대로 씁니다. 만든 뒤 검토해서 이상한 질문은 지우세요.",
  sentence: "지문의 문장 하나를 그대로 질문으로 씁니다. 단어가 그대로 겹쳐 매우 쉬운 세트라서 파이프라인이 동작하는지 점검하는 용도입니다. 모델 비교에는 LLM 생성이나 실제 질문을 쓰세요.",
  manual: "실제 사용자 질문과 정답 문서를 적습니다. 가장 믿을 만한 평가 세트입니다. 근거 문장을 적으면 '근거를 담은 청크를 찾았는지'도 평가합니다.",
  import: "다른 곳에서 만든 평가 세트나 내보내기한 파일을 가져옵니다. doc_ids 는 이 컬렉션의 문서 id 여야 합니다.",
};

function evMethodChanged() {
  const m = $("#e-method").value;
  $("#e-gen").hidden = !["llm", "sentence"].includes(m);
  $("#e-llm").hidden = m !== "llm";
  $("#e-manual").hidden = m !== "manual";
  $("#e-import").hidden = m !== "import";
  $("#e-hint").textContent = EV_HINT[m];
}
$("#e-method").addEventListener("change", evMethodChanged);

async function evLlmStatus() {
  const s = await api("/api/llm/status");
  $("#e-llm-status").innerHTML = s.default.error
    ? `<span class="badge warn">LLM 미설정</span> ${esc(s.default.error)}`
    : `<span class="badge ok">사용 가능</span> 기본: ${s.default.provider === "openai" ? "OpenAI 호환" : "Claude"} · <span class="mono">${esc(s.default.model)}</span>${s.default.base_url ? ` · ${esc(s.default.base_url)}` : ""}`;
}

function evRenderForm() {
  const ready = col.chunk_sets.filter(c => c.status === "ready");
  const cur = $("#e-cs").value;
  $("#e-cs").innerHTML = ready.map(c => `<option value="${c.id}">#${c.id} ${esc(c.name)} (${c.n_chunks})</option>`).join("") || '<option value="">준비된 청크 세트 없음</option>';
  if (cur && ready.some(c => String(c.id) === cur)) $("#e-cs").value = cur;
}

async function evLoad() {
  evSets = await api(`/api/collections/${COLLECTION_ID}/eval-sets`);
  $("#e-rows").innerHTML = evSets.map(s => `<tr>
    <td>${s.id}</td><td><b>${esc(s.name)}</b>${s.stats?.generation?.failed ? ` <span class="badge warn" title="${esc((s.stats.generation.errors || []).join("\n"))}">실패 ${s.stats.generation.failed}</span>` : ""}</td>
    <td class="small">${EV_METHOD[s.method] || s.method}${s.config?.llm ? `<div class="mono muted">${esc(s.config.llm.model)}</div>` : ""}</td>
    <td class="num">${s.n_items}</td><td class="num">${s.stats?.lexical_overlap ?? "-"}</td>
    <td>${statusBadge(s.status, s.error)}</td>
    <td class="right nowrap">${s.status === "ready" ? `<button class="btn sm" onclick="evView(${s.id})">검토</button><a class="btn sm" href="/api/eval-sets/${s.id}/export">내보내기</a>` : ""}<button class="btn sm danger" onclick="evDelete(${s.id})">삭제</button></td></tr>`).join("")
    || '<tr><td colspan="7" class="empty">평가 세트가 없습니다</td></tr>';
  clearTimeout(evTimer);
  if (evSets.some(s => s.status === "building")) evTimer = setTimeout(evLoad, 1500);
  if (typeof evRenderRunner === "function") evRenderRunner();
}

// 직접 입력: "질문 | 파일1, 파일2 | 근거"
function evParseManual() {
  const byName = Object.fromEntries(col.documents.map(d => [d.filename.toLowerCase(), d.id]));
  const items = [], errors = [];
  $("#e-lines").value.split("\n").map(s => s.trim()).filter(Boolean).forEach((line, i) => {
    const [q, files = "", ev = ""] = line.split("|").map(s => s.trim());
    const ids = files.split(",").map(f => f.trim().toLowerCase()).filter(Boolean).map(f => byName[f] ?? (/^\d+$/.test(f) ? +f : null));
    if (!q || !ids.length || ids.includes(null)) errors.push(`${i + 1}번째 줄: 질문과 이 컬렉션의 파일 이름이 필요합니다`);
    else items.push({ query: q, doc_ids: ids, evidence: ev });
  });
  return { items, errors };
}

$("#e-create").onclick = async e => {
  const m = $("#e-method").value;
  const name = $("#e-name").value.trim();
  if (m === "llm" || m === "sentence") {
    if (!$("#e-cs").value) return toast("청크 세트를 먼저 만드세요", "err");
    const styles = [...document.querySelectorAll('input[name="e-style"]:checked')].map(x => x.value);
    if (m === "llm" && !styles.length) return toast("질문 유형을 하나 이상 고르세요", "err");
    await busy(e.target, () => api(`/api/collections/${COLLECTION_ID}/eval-sets/generate`, { method: "POST", body: {
      method: m, name, chunk_set_id: +$("#e-cs").value, n_passages: +$("#e-n").value, min_chars: +$("#e-min").value,
      styles: m === "llm" ? styles : undefined, provider: $("#e-provider").value || null, model: $("#e-model").value.trim() || null, concurrency: +$("#e-conc").value,
    } }));
    toast("생성을 시작했습니다", "ok");
  } else if (m === "manual") {
    const { items, errors } = evParseManual();
    if (errors.length) return toast(errors.slice(0, 3).join("\n"), "err");
    if (!items.length) return toast("질문을 입력하세요", "err");
    await busy(e.target, () => api(`/api/collections/${COLLECTION_ID}/eval-sets`, { method: "POST", body: { name: name || "직접 입력", method: "manual", items } }));
    $("#e-lines").value = "";
  } else {
    const f = $("#e-file").files[0];
    if (!f) return toast("파일을 고르세요", "err");
    let data;
    try { data = JSON.parse(await f.text()); } catch { return toast("JSON 형식이 아닙니다", "err"); }
    const items = (data.items || data).map(it => ({ query: it.query, doc_ids: it.doc_ids, evidence: it.evidence || "", type: it.type || "manual" }));
    await busy(e.target, () => api(`/api/collections/${COLLECTION_ID}/eval-sets`, { method: "POST", body: { name: name || data.name || f.name, method: "import", items } }));
  }
  evLoad();
};

async function evDelete(id) {
  if (!confirm(`평가 세트 #${id} 를 삭제할까요?`)) return;
  await api(`/api/eval-sets/${id}`, { method: "DELETE" }); toast("삭제했습니다", "ok"); evLoad();
}

// 검토: 질문을 읽고 이상한 것은 체크 해제 후 저장
let evEditing = null;
async function evView(id) {
  evEditing = await api(`/api/eval-sets/${id}`);
  const s = evEditing;
  const g = s.stats.generation;
  $("#dlg-title").textContent = `평가 세트 #${s.id} · ${s.name}`;
  $("#dlg-body").innerHTML = `<div class="small muted" style="margin-bottom:8px">질문 ${s.n_items}개 · 문서 ${s.stats.documents}개 · 유형 ${Object.entries(s.stats.by_type || {}).map(([k, v]) => `${EV_TYPE[k] || k} ${v}`).join(", ")}
      ${g?.calls != null ? ` · LLM 호출 ${g.calls}회, 토큰 입력 ${fmtNum(g.input_tokens)} / 출력 ${fmtNum(g.output_tokens)}${g.empty ? `, 질문 없음 ${g.empty}` : ""}${g.evidence_fixed ? `, 근거 보정 ${g.evidence_fixed}` : ""}` : ""}</div>
    <div class="table-wrap" style="max-height:60vh"><table>
      <tr><th><input type="checkbox" checked onchange="document.querySelectorAll('.ev-keep').forEach(c => c.checked = this.checked)" aria-label="전체"></th><th>질문</th><th>유형</th><th>정답 문서</th><th>근거 문장</th><th class="num">겹침</th></tr>
      ${s.items.map((it, i) => `<tr><td><input type="checkbox" class="ev-keep" data-i="${i}" checked></td><td>${esc(it.query)}</td><td class="small nowrap">${EV_TYPE[it.type] || esc(it.type || "")}</td>
        <td class="small">${esc(it.filename || it.doc_ids.join(","))}</td><td class="small muted">${esc((it.evidence || "").slice(0, 120))}${it.evidence_exact === false ? ' <span class="badge warn" title="LLM 이 적은 근거가 원문과 달라 가장 비슷한 원문 문장으로 바꿨습니다">보정</span>' : ""}</td>
        <td class="num mono small">${it.lexical_overlap ?? "-"}</td></tr>`).join("")}
    </table></div>
    <div class="row" style="margin-top:10px"><span class="small muted">체크 해제한 질문을 빼고 저장합니다.</span><span class="spacer"></span><button class="btn primary" onclick="evSaveReview(this)">저장</button></div>`;
  $("#dlg").showModal();
}
async function evSaveReview(btn) {
  const keep = [...document.querySelectorAll(".ev-keep")].filter(c => c.checked).map(c => evEditing.items[+c.dataset.i]);
  if (!keep.length) return toast("질문이 하나 이상 있어야 합니다", "err");
  await busy(btn, () => api(`/api/eval-sets/${evEditing.id}`, { method: "PATCH", body: { items: keep.map(({ query, doc_ids, evidence, type }) => ({ query, doc_ids, evidence: evidence || "", type: type || "manual" })) } }));
  $("#dlg").close(); toast(`${keep.length}개로 저장했습니다`, "ok"); evLoad();
}

// rag.js 의 load() 가 다시 불릴 때(청크 세트·인덱스 변경) 평가 탭도 갱신
const _ragLoad = load;
load = async () => { await _ragLoad(); evRenderForm(); if (typeof evRenderRunner === "function") evRenderRunner(); };
(async () => {
  while (!col) await new Promise(r => setTimeout(r, 100));
  evMethodChanged(); evRenderForm(); evLlmStatus(); evLoad();
})();

// ── 조합 평가 ──
let evRerankers = [];
const EV_MODE = { dense: "의미", bm25: "BM25", hybrid: "하이브리드" };

async function evRenderRunner() {
  const ready = evSets.filter(s => s.status === "ready");
  const area = $("#ev-area");
  if (!ready.length) { area.innerHTML = ""; return; }
  if (!evRerankers.length) evRerankers = (await getModels()).filter(m => m.kind === "reranker");
  const idxs = col.indexes.filter(i => i.status === "ready");
  const csName = id => col.chunk_sets.find(c => c.id === id)?.name || `#${id}`;
  const keep = sel => [...area.querySelectorAll(sel + ":checked")].map(x => x.value);
  const prev = area.querySelector("#r-set") ? { set: $("#r-set").value, idx: keep(".r-idx"), modes: keep(".r-mode"), rr: keep(".r-rr"), max: $("#r-max").value, out: $("#r-out").innerHTML } : null;
  area.innerHTML = `<div class="card stack">
    <h2>조합 평가 <span class="small muted">청킹 × 임베딩 모델 × 검색 방식 × 리랭커</span></h2>
    <div class="row">
      <div class="field grow"><label>평가 세트</label><select id="r-set">${ready.map(s => `<option value="${s.id}">#${s.id} ${esc(s.name)} (${s.n_items}문항)</option>`).join("")}</select></div>
      <div class="field"><label>질문 수 제한</label><input id="r-max" type="number" min="1" placeholder="전체" style="width:90px"></div>
    </div>
    <div class="grid cols-3">
      <div><label>벡터 인덱스 (청크 세트 · 모델)</label>${idxs.map(i => `<label class="row small" style="margin:2px 0"><input type="checkbox" class="r-idx" value="${i.id}" checked> ${esc(csName(i.chunk_set_id))} · <span class="mono">${esc(i.model_hf_id.split("/").pop())}</span>${i.truncate_dim ? ` ${i.truncate_dim}d` : ""}</label>`).join("") || '<div class="small muted">준비된 인덱스가 없습니다 (BM25 만 가능)</div>'}</div>
      <div><label>검색 방식</label>${Object.entries(EV_MODE).map(([k, v]) => `<label class="row small" style="margin:2px 0"><input type="checkbox" class="r-mode" value="${k}" ${k !== "dense" ? "checked" : ""}> ${v}</label>`).join("")}
        <div class="small muted">BM25 는 고른 인덱스들의 청크 세트마다 한 번씩 (인덱스를 고르지 않으면 모든 청크 세트).</div></div>
      <div><label>리랭커 ('없음'은 항상 포함)</label>${evRerankers.map(r => `<label class="row small" style="margin:2px 0"><input type="checkbox" class="r-rr" value="${r.id}"> ${esc(r.name)}${r.cached ? "" : ' <span class="badge">미다운로드</span>'}</label>`).join("") || '<div class="small muted">카탈로그에 리랭커가 없습니다</div>'}</div>
    </div>
    <div class="row"><span class="small muted" id="r-count"></span><span class="spacer"></span><button class="btn primary" id="r-run">평가 실행</button></div>
    <div id="r-progress" hidden></div>
    <div id="r-history"></div>
  </div>
  <div id="r-out" style="margin-top:16px"></div>`;
  if (prev) {
    if (ready.some(s => String(s.id) === prev.set)) $("#r-set").value = prev.set;
    area.querySelectorAll(".r-idx").forEach(x => (x.checked = prev.idx.includes(x.value)));
    area.querySelectorAll(".r-mode").forEach(x => (x.checked = prev.modes.includes(x.value)));
    area.querySelectorAll(".r-rr").forEach(x => (x.checked = prev.rr.includes(x.value)));
    $("#r-max").value = prev.max;
    if (evLastResult) evRender(evLastResult);
  }
  area.querySelectorAll("input").forEach(x => x.addEventListener("change", evCount));
  $("#r-set").addEventListener("change", evHistory);
  $("#r-run").onclick = evRun;
  evCount(); evHistory();
}

function evConfigs() {
  const area = $("#ev-area");
  const idxIds = [...area.querySelectorAll(".r-idx:checked")].map(x => +x.value);
  const modes = [...area.querySelectorAll(".r-mode:checked")].map(x => x.value);
  const rrs = [null, ...[...area.querySelectorAll(".r-rr:checked")].map(x => +x.value)];
  const out = [];
  for (const id of idxIds) for (const m of modes.filter(m => m !== "bm25")) for (const rr of rrs) out.push({ index_id: id, mode: m, reranker_id: rr });
  if (modes.includes("bm25")) {
    const sets = idxIds.length ? [...new Set(idxIds.map(id => col.indexes.find(i => i.id === id).chunk_set_id))] : col.chunk_sets.filter(c => c.status === "ready").map(c => c.id);
    for (const cs of sets) for (const rr of rrs) out.push({ chunk_set_id: cs, mode: "bm25", reranker_id: rr });
  }
  return out;
}
function evCount() {
  const n = evConfigs().length;
  const set = evSets.find(s => String(s.id) === $("#r-set").value);
  const q = Math.min(set?.n_items || 0, +$("#r-max").value || Infinity);
  const slow = $("#ev-area").querySelector(".r-rr:checked") ? " · 리랭커는 질문마다 후보 30개를 다시 점수 매겨 느립니다" : "";
  $("#r-count").innerHTML = `${n}개 조합 × 질문 ${q}개 = 검색 ${fmtNum(n * q)}번${n > 32 ? ' <span class="badge err">최대 32개 조합</span>' : ""}${slow}`;
  $("#r-run").disabled = !n || n > 32;
}

async function evHistory() {
  const runs = await api(`/api/eval-sets/${$("#r-set").value}/runs`);
  $("#r-history").innerHTML = runs.length ? `<details><summary class="small">이전 평가 ${runs.length}회</summary><table>${runs.map(r => `<tr><td class="small nowrap">${fmtDate(r.created_at)}</td><td class="small">${r.n_configs}개 조합 · 1위 <b>${esc(r.best?.label || "-")}</b> ${r.best ? `nDCG@10 ${pct(r.best.metrics["ndcg@10"])}` : ""}</td><td class="right"><button class="btn sm" onclick="evShowRun(${r.id})">보기</button></td></tr>`).join("")}</table></details>` : "";
}
async function evShowRun(id) { const r = await api(`/api/runs/${id}`); evRender({ ...r.result, run_id: id }); }

async function evRun(e) {
  const body = { configs: evConfigs(), max_queries: +$("#r-max").value || null };
  const job = await busy(e.target, () => api(`/api/eval-sets/${$("#r-set").value}/evaluate`, { method: "POST", body }));
  const box = $("#r-progress");
  box.hidden = false; e.target.disabled = true;
  try {
    const done = await pollJob(job.id, j => { box.innerHTML = `<div class="progress"><div style="width:${pct(j.progress)}%"></div></div><div class="small muted">${esc(j.message)}</div>`; }, 1000);
    if (done.status !== "done") { box.innerHTML = `<div class="errbox">${esc(done.error || done.status)}</div>`; return; }
    box.hidden = true; evRender(done.result); evHistory();
  } finally { e.target.disabled = false; }
}

// 막대 + 95% 구간 (0~100%)
function ciBar(v, ci) {
  const whisker = ci ? `<div title="95% 구간 ${pct(ci[0])}–${pct(ci[1])}" style="position:absolute;top:6px;height:2px;left:${ci[0] * 100}%;width:${Math.max(0.5, (ci[1] - ci[0]) * 100)}%;background:var(--text)"></div>`
    + `<div style="position:absolute;top:3px;height:8px;width:2px;left:${ci[0] * 100}%;background:var(--text)"></div>`
    + `<div style="position:absolute;top:3px;height:8px;width:2px;left:calc(${ci[1] * 100}% - 2px);background:var(--text)"></div>` : "";
  return `<div style="position:relative;height:14px;background:var(--code);border-radius:4px;min-width:120px;flex:1"><div class="bar" style="position:absolute;top:0;bottom:0;left:0;width:${v * 100}%;border-radius:4px"></div>${whisker}</div>`;
}
function rankCell(r, title) {
  const style = r === 1 ? "background:color-mix(in srgb, var(--ok) 18%, transparent)" : r == null ? "color:var(--status-critical);font-weight:700" : r > 5 ? "color:var(--status-critical)" : "";
  return `<td class="num mono" style="${style}" title="${esc(title)}">${r ?? "✗"}</td>`;
}

let evLastResult = null;
function evRender(r) {
  evLastResult = r;
  const ok = r.results.filter(e => e.status === "ok");
  const types = [...new Set(ok.flatMap(e => Object.keys(e.by_type || {})))];
  const vs = e => (e.vs_best ? `${(e.vs_best.diff * 100).toFixed(1)}%p ${e.vs_best.significant ? '<span class="badge err">유의한 차이</span>' : '<span class="badge">차이 불확실</span>'}` : ok.length > 1 ? "기준" : "");
  $("#r-out").innerHTML = `<div class="card stack">
    <div class="row between"><h2>평가 결과 · ${esc(r.eval_set?.name || "")}</h2><span class="small muted">질문 ${r.n_queries}개 · ${r.results.length}개 조합${r.seconds != null ? ` · ${r.seconds}s` : ""}${r.run_id ? ` · run #${r.run_id}` : ""}</span></div>
    <div class="table-wrap"><table>
      <tr><th>#</th><th>설정</th><th>nDCG@10 (95% 구간)</th><th class="num">Hit@1</th><th class="num">Hit@5</th><th class="num">Hit@10</th><th class="num">MRR@10</th><th class="num" title="정답 문서가 상위 5개 문서 안에 든 비율">문서 R@5</th><th class="num">지연 평균/p95</th><th>1위 대비</th></tr>
      ${ok.map((e, i) => `<tr><td>${i + 1}</td><td class="small"><b>${esc(e.label)}</b></td>
        <td><div class="row" style="flex-wrap:nowrap;gap:8px"><span class="mono" style="width:44px">${pct(e.metrics["ndcg@10"])}</span>${ciBar(e.metrics["ndcg@10"], e.ci["ndcg@10"])}</div></td>
        <td class="num">${pct(e.metrics["hit@1"])}</td><td class="num">${pct(e.metrics["hit@5"])}</td><td class="num">${pct(e.metrics["hit@10"])}</td><td class="num">${pct(e.metrics["mrr@10"])}</td><td class="num">${pct(e.metrics["doc_recall@5"])}</td>
        <td class="num small nowrap">${e.latency_ms.mean} / ${e.latency_ms.p95}ms</td><td class="small nowrap">${vs(e)}</td></tr>`).join("")}
      ${r.results.filter(e => e.status !== "ok").map(e => `<tr><td>-</td><td class="small">${esc(e.label)}</td><td colspan="8"><div class="errbox">${esc(e.error)}</div></td></tr>`).join("")}
    </table></div>
    <div class="small muted">Hit@k = 근거 문장을 담은 청크(근거가 없으면 정답 문서의 청크)가 상위 k개 안에 든 비율, 검색 지표는 % 단위. 검은 선 = 질문을 1,000번 다시 뽑아 구한 95% 구간. '차이 불확실'은 같은 질문들로 짝지어 비교했을 때 1위와의 차이가 우연일 수 있다는 뜻입니다.</div>
    ${types.length > 1 ? `<h3>질문 유형별 nDCG@10</h3><div class="table-wrap"><table><tr><th>설정</th>${types.map(t => `<th class="num">${EV_TYPE[t] || esc(t)} (${ok[0].by_type[t]?.n ?? 0})</th>`).join("")}</tr>
      ${ok.map(e => `<tr><td class="small">${esc(e.label)}</td>${types.map(t => `<td class="num">${e.by_type[t] ? pct(e.by_type[t]["ndcg@10"]) : "-"}</td>`).join("")}</tr>`).join("")}</table></div>` : ""}
    <h3>질문별 정답 순위 <label class="small muted" style="font-weight:400"><input type="checkbox" id="r-diff" checked> 설정마다 결과가 다른 질문만</label></h3>
    <div class="table-wrap" style="max-height:480px"><table id="r-qtable"></table></div>
    <div class="small muted">숫자 = 정답 청크의 순위(열 번호 = 위 표의 순위), ✗ = 상위 10개 밖. 칸에 마우스를 올리면 그 설정의 1위 결과가 보입니다.</div>
  </div>`;
  const qtable = () => {
    const onlyDiff = $("#r-diff").checked;
    const rows = r.queries.filter(q => !onlyDiff || new Set(q.ranks.map(x => (x == null ? 99 : Math.min(x, 6)))).size > 1);
    $("#r-qtable").innerHTML = `<tr><th>질문</th><th>정답 문서</th>${ok.map((e, i) => `<th class="num" title="${esc(e.label)}">${i + 1}</th>`).join("")}</tr>`
      + rows.map(q => `<tr><td class="small">${esc(q.query)}${q.type ? ` <span class="badge">${EV_TYPE[q.type] || esc(q.type)}</span>` : ""}</td><td class="small muted">${esc(q.filename || "")}</td>
        ${q.ranks.map((x, i) => rankCell(x, `${ok[i].label}\n1위: ${q.top1[i]?.filename || "-"} — ${(q.top1[i]?.text || "").slice(0, 120)}`)).join("")}</tr>`).join("")
      || `<tr><td colspan="${ok.length + 2}" class="empty">모든 설정의 결과가 같습니다</td></tr>`;
  };
  $("#r-diff").addEventListener("change", qtable);
  qtable();
}
