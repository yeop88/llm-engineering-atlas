// 컬렉션 상세: 문서 · 청크 세트 · 벡터 인덱스 · 검색 비교
let col = null;      // /api/collections/{id}
let opts = null;     // /api/rag/options
let refreshTimer = null;

const DOMAIN_LABEL = { general: "일반", internal: "사내 문서", legal: "법률", support: "고객·AS 문의", product: "제품·매뉴얼", other: "기타" };
// 도메인별 추천 청킹 기본값
const DOMAIN_STRATEGY = {
  legal: { method: "legal", size: 800, overlap: 0 },
  support: { method: "recursive", size: 500, overlap: 50 },
  product: { method: "recursive", size: 600, overlap: 80 },
};
const METHOD_HINT = {
  recursive: "문단 → 줄 → 문장 → 단어 순으로 자연스러운 경계에서 자릅니다. 대부분의 문서에 무난한 기본값입니다.",
  fixed: "정해진 글자 수로 자르고 앞 청크와 겹치게 합니다. 구조가 없는 텍스트(로그, OCR 결과)에 단순하게 쓸 수 있습니다.",
  sentence: "Kiwi 형태소 분석기로 한국어 문장을 정확히 나눈 뒤 묶습니다. 문장이 중간에 잘리지 않습니다. 겹침은 문장 수로 지정합니다.",
  legal: "법령은 조문(제N조)·항(①②) 단위로, 판결문은 【주문】【이유】 같은 구획 단위로 나누고 각 청크에 소속 조문 제목을 붙입니다.",
  page: "PDF 쪽 또는 HWP 구역 단위로 나눕니다. 너무 길면 재귀 분할합니다. 쪽 번호 인용이 중요한 문서에 씁니다.",
};

const jobBar = j => j ? `<div class="progress" style="margin-top:4px"><div style="width:${pct(j.progress)}%"></div></div><div class="small muted">${esc(j.message)}</div>` : "";
const statusBadge = (s, err) => ({ ready: '<span class="badge ok">준비됨</span>', building: '<span class="badge warn">구축 중</span>', pending: '<span class="badge warn">대기</span>', error: `<span class="badge err" title="${esc(err)}">오류</span>` })[s] || esc(s);

async function load() {
  [col, opts] = await Promise.all([api(`/api/collections/${COLLECTION_ID}`), opts ? Promise.resolve(opts) : api("/api/rag/options")]);
  $("#c-title").textContent = col.name;
  $("#c-sub").textContent = `${DOMAIN_LABEL[col.domain] || col.domain}${col.description ? " · " + col.description : ""}`;
  $("#c-summary").innerHTML = `문서 ${col.documents.length} · 청크 세트 ${col.chunk_sets.length} · 인덱스 ${col.indexes.length}`;
  renderDocs(); renderChunkSets(); renderIndexes(); renderIndexForm(); renderConfigs();
  clearTimeout(refreshTimer);
  if (col.chunk_sets.some(c => c.job || c.status === "pending") || col.indexes.some(i => i.job || ["pending", "building"].includes(i.status))) {
    refreshTimer = setTimeout(load, 1500);
  }
}

// ── ① 문서 ──
function renderDocs() {
  $("#file-types").textContent = `(${opts.file_types.join(" ")} · 최대 ${opts.max_upload_mb}MB)`;
  $("#d-rows").innerHTML = col.documents.map(d => `<tr>
    <td><b>${esc(d.filename)}</b>${d.meta?.warning ? `<div class="warnbox small">${esc(d.meta.warning)}</div>` : ""}</td>
    <td class="small">${esc(d.title)}</td><td class="num">${fmtBytes(d.size_bytes)}</td><td class="num">${fmtNum(d.n_chars)}</td>
    <td class="num">${d.n_pages}${d.meta?.page_kind === "section" ? " 구역" : d.meta?.page_kind === "page" ? " 쪽" : ""}</td>
    <td class="small nowrap">${fmtDate(d.created_at)}</td>
    <td class="right nowrap"><button class="btn sm" onclick="viewDoc(${d.id})">본문</button><button class="btn sm danger" onclick="delDoc(${d.id}, '${esc(d.filename)}')">삭제</button></td></tr>`).join("")
    || '<tr><td colspan="7" class="empty">문서가 없습니다</td></tr>';
}
async function upload(files) {
  if (!files.length) return;
  const form = new FormData();
  [...files].forEach(f => form.append("files", f));
  $("#d-upload-result").innerHTML = `<div class="small muted">${files.length}개 파일 처리 중…</div>`;
  try {
    const r = await api(`/api/collections/${COLLECTION_ID}/documents`, { method: "POST", form });
    $("#d-upload-result").innerHTML = `<div class="small"><span class="badge ok">추가 ${r.added.length}</span> ${r.skipped.length ? `<span class="badge warn">건너뜀 ${r.skipped.length}</span>` : ""}</div>`
      + r.skipped.map(s => `<div class="warnbox small">${esc(s.filename)}: ${esc(s.reason)}</div>`).join("")
      + r.added.filter(a => a.warning).map(a => `<div class="warnbox small">${esc(a.filename)}: ${esc(a.warning)}</div>`).join("");
    if (r.added.length && col.chunk_sets.length) toast("문서가 바뀌었습니다. 청크 세트를 다시 만들어야 새 문서가 검색됩니다.");
    load();
  } catch (e) { $("#d-upload-result").innerHTML = `<div class="errbox">${esc(e.message)}</div>`; }
}
$("#d-files").addEventListener("change", e => { upload(e.target.files); e.target.value = ""; });
const dz = $("#dropzone");
["dragover", "dragenter"].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.style.borderColor = "var(--accent)"; }));
["dragleave", "drop"].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.style.borderColor = ""; }));
dz.addEventListener("drop", e => upload(e.dataTransfer.files));

async function viewDoc(id) {
  const d = await api(`/api/documents/${id}`);
  $("#dlg-title").textContent = d.filename;
  $("#dlg-body").innerHTML = `<div class="small muted" style="margin-bottom:8px">${esc(d.title)} · ${fmtNum(d.n_chars)}자${d.truncated ? " (앞부분만 표시)" : ""}</div><pre style="white-space:pre-wrap;max-height:70vh">${esc(d.text)}</pre>`;
  $("#dlg").showModal();
}
async function delDoc(id, name) {
  if (!confirm(`'${name}' 을(를) 삭제할까요? 이 문서의 청크와 모든 인덱스의 벡터도 함께 지워집니다.`)) return;
  await api(`/api/documents/${id}`, { method: "DELETE" }); toast("삭제했습니다", "ok"); load();
}

// ── ② 청크 세트 ──
function strategyFromForm() {
  return { method: $("#s-method").value, size: +$("#s-size").value, overlap: +$("#s-overlap").value, overlap_sentences: +$("#s-osent").value, min_chars: +$("#s-min").value, include_title: $("#s-title").checked };
}
function initStrategyForm() {
  $("#s-method").innerHTML = Object.entries(opts.chunk_methods).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("");
  const d = { ...opts.chunk_defaults, ...(DOMAIN_STRATEGY[col.domain] || {}) };
  $("#s-method").value = d.method; $("#s-size").value = d.size; $("#s-overlap").value = d.overlap;
  $("#s-osent").value = d.overlap_sentences; $("#s-min").value = d.min_chars; $("#s-title").checked = d.include_title;
  updateHint();
}
function updateHint() {
  const m = $("#s-method").value;
  $("#s-hint").textContent = METHOD_HINT[m];
  $("#s-osent-wrap").hidden = m !== "sentence";
}
$("#s-method").addEventListener("change", updateHint);
$("#s-preview").onclick = async e => {
  const r = await busy(e.target, () => api(`/api/collections/${COLLECTION_ID}/chunk-preview?limit=12`, { method: "POST", body: strategyFromForm() }));
  const st = r.stats;
  const maxH = Math.max(...Object.values(st.hist || { x: 1 }));
  $("#s-preview-out").innerHTML = `<h3>미리보기 · 청크 ${fmtNum(st.count)}개</h3>
    <div class="small muted">평균 ${st.avg}자 · 중앙값 ${st.median} · p95 ${st.p95} · 최소 ${st.min} · 최대 ${st.max}</div>
    <div style="margin:10px 0">${Object.entries(st.hist || {}).map(([k, n]) => `<div class="row small" style="flex-wrap:nowrap;gap:8px"><span class="mono" style="width:90px">${k}</span>
      <div style="flex:1;background:var(--code);border-radius:4px"><div class="bar" style="width:${Math.max(2, n / maxH * 100)}%"></div></div><span class="mono" style="width:40px;text-align:right">${n}</span></div>`).join("")}</div>
    <div class="stack" style="max-height:420px;overflow:auto">${r.samples.map(s => `<div class="rank-item"><div class="small muted">${esc(s.document)}${s.page ? ` · ${s.page}쪽` : ""}${s.heading ? ` · <b>${esc(s.heading)}</b>` : ""} · ${s.chars}자</div>
      <div class="small" style="white-space:pre-wrap">${esc(s.text.slice(0, 400))}${s.text.length > 400 ? "…" : ""}</div></div>`).join("")}</div>`;
};
$("#s-create").onclick = async e => {
  await busy(e.target, () => api(`/api/collections/${COLLECTION_ID}/chunk-sets`, { method: "POST", body: { name: $("#s-name").value, strategy: strategyFromForm() } }));
  $("#s-name").value = ""; toast("청크 세트를 만드는 중입니다", "ok"); load();
};
function strategyLabel(s) {
  const m = { recursive: "재귀", fixed: "고정", sentence: "문장", legal: "법률 구조", page: "페이지" }[s.method] || s.method;
  return `${m} · ${s.size}자${s.method === "sentence" ? ` · 겹침 ${s.overlap_sentences}문장` : ` · 겹침 ${s.overlap}`}${s.include_title ? " · 제목 포함" : ""}`;
}
function renderChunkSets() {
  if (!$("#s-method").options.length) initStrategyForm();
  $("#cs-rows").innerHTML = col.chunk_sets.map(c => `<tr>
    <td>${c.id}</td><td><b>${esc(c.name)}</b><div class="small muted">${esc(strategyLabel(c.strategy))}</div></td>
    <td>${statusBadge(c.status, c.error)} ${c.stale ? '<span class="badge warn" title="이 청크 세트를 만든 뒤 문서가 추가·삭제되었습니다. 새 문서를 검색하려면 다시 만드세요.">문서 변경됨</span>' : ""}${jobBar(c.job)}${c.error ? `<div class="errbox small">${esc(c.error)}</div>` : ""}</td>
    <td class="num">${fmtNum(c.n_chunks)}</td><td class="num">${c.stats?.avg ?? "-"}</td><td class="num">${c.stats?.p95 ?? "-"}</td>
    <td class="small nowrap">${fmtDate(c.created_at)}</td>
    <td class="right nowrap">${c.status === "ready" ? `<button class="btn sm" onclick="viewChunks(${c.id}, 0)">청크 보기</button>` : ""}<button class="btn sm danger" onclick="delChunkSet(${c.id})">삭제</button></td></tr>`).join("")
    || '<tr><td colspan="8" class="empty">청크 세트가 없습니다. 위에서 전략을 골라 만드세요.</td></tr>';
}
async function viewChunks(id, offset) {
  const r = await api(`/api/chunk-sets/${id}/chunks?offset=${offset}&limit=30`);
  $("#dlg-title").textContent = `청크 세트 #${id} · ${offset + 1}–${Math.min(offset + 30, r.total)} / ${fmtNum(r.total)}`;
  $("#dlg-body").innerHTML = `<div class="stack" style="max-height:70vh;overflow:auto">${r.items.map(c => `<div class="rank-item">
      <div class="small muted">#${c.id} · ${esc(c.filename)}${c.page ? ` · ${c.page}쪽` : ""}${c.heading ? ` · <b>${esc(c.heading)}</b>` : ""} · ${c.chars}자</div>
      <div class="small" style="white-space:pre-wrap">${esc(c.text)}</div>
      <div class="small muted mono">BM25 토큰: ${esc(c.tokens.join(" "))}</div></div>`).join("")}</div>
    <div class="row" style="margin-top:10px">${offset > 0 ? `<button class="btn sm" onclick="viewChunks(${id}, ${offset - 30})">← 이전</button>` : ""}<span class="spacer"></span>${offset + 30 < r.total ? `<button class="btn sm" onclick="viewChunks(${id}, ${offset + 30})">다음 →</button>` : ""}</div>`;
  if (!$("#dlg").open) $("#dlg").showModal();
}
async function delChunkSet(id) {
  const n = col.indexes.filter(i => i.chunk_set_id === id).length;
  if (!confirm(`청크 세트 #${id} 를 삭제할까요?${n ? ` 이 청크 세트로 만든 인덱스 ${n}개(벡터 DB 데이터)도 함께 삭제됩니다.` : ""}`)) return;
  await api(`/api/chunk-sets/${id}`, { method: "DELETE" }); toast("삭제했습니다", "ok"); load();
}

// ── ③ 인덱스 ──
async function renderIndexForm() {
  const ready = col.chunk_sets.filter(c => c.status === "ready");
  const keepCs = $("#i-cs").value;
  $("#i-cs").innerHTML = ready.map(c => `<option value="${c.id}">#${c.id} ${esc(c.name)} (${fmtNum(c.n_chunks)}개)</option>`).join("") || '<option value="">준비된 청크 세트 없음</option>';
  if (keepCs) $("#i-cs").value = keepCs;
  if (!$("#i-model").options.length) {
    await fillModelSelect($("#i-model"));
    $("#i-model").addEventListener("change", () => fillDims());
  }
  const keepStore = $("#i-store").value;
  $("#i-store").innerHTML = opts.stores.map(s => `<option value="${s.kind}" ${s.ok ? "" : "disabled"}>${esc(s.label)}${s.default ? " (기본)" : ""}${s.ok ? "" : " — " + (s.configured ? "연결 실패" : "설정 안 됨")}</option>`).join("");
  $("#i-store").value = keepStore || opts.default_store;
  fillDims();
}
function fillDims() {
  const o = $("#i-model").selectedOptions[0];
  const dims = (o?.dataset.dims || "").split(",").filter(Boolean).map(Number);
  const cur = $("#i-dim").value;
  $("#i-dim").innerHTML = '<option value="">전체 차원</option>' + dims.slice(1).map(d => `<option value="${d}">${d}</option>`).join("");
  if ([...$("#i-dim").options].some(x => x.value === cur)) $("#i-dim").value = cur;
}
$("#i-create").onclick = async e => {
  const body = { chunk_set_id: +$("#i-cs").value, model_id: +$("#i-model").value, store: $("#i-store").value, truncate_dim: $("#i-dim").value ? +$("#i-dim").value : null };
  if (!body.chunk_set_id) return toast("준비된 청크 세트가 필요합니다", "err");
  await busy(e.target, () => api("/api/indexes", { method: "POST", body }));
  toast("인덱스 구축을 시작했습니다 (처음 쓰는 모델은 다운로드부터 합니다)", "ok"); load();
};
function renderIndexes() {
  const csName = id => col.chunk_sets.find(c => c.id === id)?.name || `#${id}`;
  const storeLabel = k => opts.stores.find(s => s.kind === k)?.label || k;
  $("#i-rows").innerHTML = col.indexes.map(i => `<tr>
    <td>${i.id}</td><td class="mono small">${esc(i.model_hf_id)}</td><td class="small">${esc(csName(i.chunk_set_id))}</td><td class="small">${esc(storeLabel(i.store))}<div class="muted mono">${esc(i.store_collection)}</div></td>
    <td class="num">${i.dim || "-"}${i.truncate_dim ? " (MRL)" : ""}</td>
    <td>${statusBadge(i.status, i.error)}${jobBar(i.job)}${i.error ? `<div class="errbox small">${esc(i.error)}</div>` : ""}</td>
    <td class="num">${fmtNum(i.n_vectors)}</td><td class="num">${i.build_seconds ? i.build_seconds + "s" : "-"}</td>
    <td class="right nowrap">${i.job ? "" : `<button class="btn sm" onclick="rebuild(${i.id})">다시 구축</button>`}<button class="btn sm danger" onclick="delIndex(${i.id})">삭제</button></td></tr>`).join("")
    || '<tr><td colspan="9" class="empty">인덱스가 없습니다. 의미 검색을 하려면 하나 이상 만드세요 (BM25 검색은 인덱스 없이 됩니다).</td></tr>';
}
async function rebuild(id) { await api(`/api/indexes/${id}/rebuild`, { method: "POST" }); toast("다시 구축합니다", "ok"); load(); }
async function delIndex(id) {
  if (!confirm(`인덱스 #${id} 와 벡터 DB 의 데이터를 삭제할까요?`)) return;
  await api(`/api/indexes/${id}`, { method: "DELETE" }); toast("삭제했습니다", "ok"); load();
}

// ── ④ 검색 비교 ──
const CFG_KEY = `rag-cfg-${COLLECTION_ID}`;
let configs = null;
let rerankers = [];
function loadConfigs() {
  try { configs = JSON.parse(localStorage.getItem(CFG_KEY) || "null"); } catch { configs = null; }
  if (!Array.isArray(configs) || !configs.length) {
    const idx = col.indexes.find(i => i.status === "ready");
    const cs = col.chunk_sets.find(c => c.status === "ready");
    configs = idx
      ? [{ label: "하이브리드", mode: "hybrid", index_id: idx.id }, { label: "하이브리드 + 리랭커", mode: "hybrid", index_id: idx.id, reranker_id: rerankers[0]?.id ?? null }]
      : [{ label: "BM25", mode: "bm25", chunk_set_id: cs?.id ?? null }];
  }
}
function saveConfigs() { try { localStorage.setItem(CFG_KEY, JSON.stringify(configs)); } catch {} }
async function renderConfigs() {
  if (!rerankers.length) rerankers = (await getModels()).filter(m => m.kind === "reranker");
  if (!configs) loadConfigs();
  const readyIdx = col.indexes.filter(i => i.status === "ready");
  const readyCs = col.chunk_sets.filter(c => c.status === "ready");
  const sel = (v, x) => (String(v ?? "") === String(x) ? "selected" : "");
  $("#cfgs").innerHTML = configs.map((c, n) => `<div class="card stack" style="padding:12px" data-n="${n}">
    <div class="row between"><input data-k="label" value="${esc(c.label || "")}" placeholder="설정 ${n + 1}" style="font-weight:600;flex:1">
      ${configs.length > 1 ? `<button class="btn sm" data-del="${n}" title="이 설정 빼기">✕</button>` : ""}</div>
    <div class="row"><div class="field grow"><label>방식</label><select data-k="mode">
      <option value="hybrid" ${sel(c.mode, "hybrid")}>하이브리드 (의미+BM25)</option><option value="dense" ${sel(c.mode, "dense")}>의미 검색만</option><option value="bm25" ${sel(c.mode, "bm25")}>BM25 만</option></select></div></div>
    ${c.mode === "bm25"
      ? `<div><label>청크 세트</label><select data-k="chunk_set_id" data-num>${readyCs.map(x => `<option value="${x.id}" ${sel(c.chunk_set_id, x.id)}>#${x.id} ${esc(x.name)}</option>`).join("")}</select></div>`
      : `<div><label>벡터 인덱스</label><select data-k="index_id" data-num>${readyIdx.map(x => `<option value="${x.id}" ${sel(c.index_id, x.id)}>#${x.id} ${esc(x.model_hf_id.split("/").pop())} · ${x.store}${x.truncate_dim ? " · " + x.truncate_dim + "d" : ""}</option>`).join("") || '<option value="">준비된 인덱스 없음</option>'}</select></div>`}
    ${c.mode === "hybrid" ? `<div class="row"><div class="field grow"><label>합치기</label><select data-k="fusion"><option value="rrf" ${sel(c.fusion, "rrf")}>RRF (순위 기반, 권장)</option><option value="weighted" ${sel(c.fusion, "weighted")}>가중합</option></select></div>
      ${c.fusion === "weighted" ? `<div class="field" style="min-width:90px"><label>의미 가중치</label><input data-k="alpha" data-num type="number" step="0.1" min="0" max="1" value="${c.alpha ?? 0.5}"></div>` : ""}</div>` : ""}
    <div class="row"><div class="field grow"><label>리랭커</label><select data-k="reranker_id" data-num><option value="">사용 안 함</option>${rerankers.map(r => `<option value="${r.id}" ${sel(c.reranker_id, r.id)}>${esc(r.name)}${r.params ? ` (${esc(r.params)})` : ""}</option>`).join("")}</select></div>
      ${c.reranker_id ? `<div class="field" style="min-width:80px"><label>재정렬 후보</label><input data-k="rerank_top" data-num type="number" min="1" max="200" value="${c.rerank_top ?? 30}"></div>` : ""}</div>
    <div class="row"><div class="field"><label>결과 수</label><input data-k="top_k" data-num type="number" min="1" max="100" value="${c.top_k ?? 10}"></div>
      <div class="field"><label>검색 후보</label><input data-k="candidates" data-num type="number" min="1" max="500" value="${c.candidates ?? 50}"></div></div>
  </div>`).join("");
  $("#cfg-add").disabled = configs.length >= 4;
}
$("#cfgs").addEventListener("change", e => {
  const card = e.target.closest("[data-n]"); const k = e.target.dataset.k;
  if (!card || !k) return;
  const c = configs[+card.dataset.n];
  c[k] = e.target.dataset.num !== undefined ? (e.target.value === "" ? null : +e.target.value) : e.target.value;
  saveConfigs();
  if (["mode", "fusion", "reranker_id"].includes(k)) renderConfigs();
});
$("#cfgs").addEventListener("click", e => {
  const d = e.target.closest("[data-del]"); if (!d) return;
  configs.splice(+d.dataset.del, 1); saveConfigs(); renderConfigs();
});
$("#cfg-add").onclick = () => { configs.push({ ...configs[configs.length - 1], label: `설정 ${configs.length + 1}` }); saveConfigs(); renderConfigs(); };

function highlight(text, tokens) {
  let html = esc(text);
  const toks = [...new Set(tokens)].filter(t => t.length >= 2).sort((a, b) => b.length - a.length).slice(0, 20);
  for (const t of toks) {
    const re = new RegExp(esc(t).replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi");
    html = html.replace(re, m => `<mark>${m}</mark>`);
  }
  return html;
}
function cfgSummary(c) {
  const idx = col.indexes.find(i => i.id === c.index_id);
  const rr = rerankers.find(r => r.id === c.reranker_id);
  const parts = [{ hybrid: `하이브리드(${c.fusion === "weighted" ? "가중합" : "RRF"})`, dense: "의미 검색", bm25: "BM25" }[c.mode]];
  if (c.mode !== "bm25" && idx) parts.push(`${idx.model_hf_id.split("/").pop()} · ${idx.store}`);
  if (rr) parts.push(`리랭커 ${rr.name}`);
  return parts.join(" · ");
}
$("#q-run").onclick = async e => {
  const query = $("#q").value.trim();
  if (!query) return toast("검색어를 입력하세요", "err");
  const body = { query, configs: configs.map(c => ({ ...c, index_id: c.mode === "bm25" ? null : c.index_id, chunk_set_id: c.mode === "bm25" ? c.chunk_set_id : null, reranker_id: c.reranker_id || null })) };
  $("#q-out").innerHTML = '<div class="empty">검색 중… (처음 쓰는 모델은 로드에 시간이 걸립니다)</div>';
  const r = await busy(e.target, () => api(`/api/collections/${COLLECTION_ID}/search`, { method: "POST", body }));
  $("#q-out").innerHTML = r.results.map((res, n) => {
    const c = res.config;
    if (res.error) return `<div class="card"><h3>${esc(c.label || `설정 ${n + 1}`)}</h3><div class="errbox">${esc(res.error)}</div></div>`;
    const t = res.timings_ms;
    const timing = Object.entries(t).map(([k, v]) => `${({ load: "모델 로드", embed: "질의 임베딩", vector_search: "벡터 검색", bm25: "BM25", rerank_load: "리랭커 로드", rerank: "리랭킹" })[k] || k} ${v}ms`).join(" · ");
    return `<div class="card"><h3>${esc(c.label || `설정 ${n + 1}`)}</h3>
      <div class="small muted">${esc(cfgSummary(c))}</div>
      <div class="small muted" style="margin:4px 0 8px">총 ${res.total_ms}ms — ${timing}</div>
      ${res.results.map(x => `<div class="rank-item">
        <div class="row between small" style="flex-wrap:nowrap"><span><span class="badge ${x.rank === 1 ? "ok" : "muted"}">#${x.rank}</span> <b>${esc(x.filename)}</b>${x.page ? ` · ${x.page}쪽` : ""}${x.heading ? ` · ${esc(x.heading)}` : ""}</span><b class="mono">${x.score.toFixed(3)}</b></div>
        <div class="small muted mono" style="margin:2px 0">${["dense", "bm25"].filter(k => x.ranks[k]).map(k => `${k === "dense" ? "의미" : "BM25"} #${x.ranks[k]} (${x.scores[k].toFixed(3)})`).join(" · ")}${x.ranks.before_rerank ? ` · 리랭크 전 #${x.ranks.before_rerank}` : ""}</div>
        <div class="small" style="white-space:pre-wrap">${highlight(x.text.length > 500 ? x.text.slice(0, 500) + "…" : x.text, res.query_tokens)}</div></div>`).join("") || '<div class="empty">결과 없음</div>'}
    </div>`;
  }).join("");
};
$("#q").addEventListener("keydown", e => { if (e.key === "Enter") $("#q-run").click(); });

load().then(initTabs);
