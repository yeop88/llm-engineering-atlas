// 7b 양자화 테스트: 기술 카탈로그(선택) · 임베딩 조합 실험 · LLM 서버 명령 조합 · LLM 비교
let QOPT = null;
const fmtGB = v => (v >= 1 ? `${v.toFixed(2)} GB` : `${(v * 1024).toFixed(0)} MB`);
const vsTxt = d => (d ? `${d.diff >= 0 ? "+" : ""}${(d.diff * 100).toFixed(1)}%p ${d.significant ? '<span class="badge err">유의</span>' : '<span class="badge">불확실</span>'}` : "기준");
// 처음에 체크해 둘 기술: 무난한 비교 묶음(기준 + int8 + binary + 재점수 + 모델 int8)
const DEFAULT_ON = new Set(["float32", "int8", "binary", "binary_rescore", "w_fp32", "w_int8"]);

async function qLoad() {
  QOPT = await api("/api/quant/options");
  qCatalog();
  $("#v-ds").innerHTML = QOPT.datasets.map(d => `<option value="${esc(d.name)}">${esc(d.title || d.name)} (질문 ${d.size} · 문서 ${d.corpus_size})</option>`).join("");
  if (QOPT.datasets.some(d => d.name === "pub_ko_strategyqa")) $("#v-ds").value = "pub_ko_strategyqa";
  await fillModelSelect($("#v-models"), {});
  $("#c-file").innerHTML = QOPT.gguf_files.map(f => `<option value="${esc(f.path)}">${esc(f.name)} (${f.gb} GB)</option>`).join("") || '<option value="">.env 의 LLM_MODELS_DIR 에 GGUF 폴더를 지정하세요</option>';
  $("#c-k").innerHTML = $("#c-v").innerHTML = QOPT.kv_types.map(k => `<option>${k}</option>`).join("");
  const cols = await api("/api/collections");
  $("#l-col").innerHTML = cols.map(c => `<option value="${c.id}">${esc(c.name)}</option>`).join("") || '<option value="">컬렉션 없음</option>';
  await lDetail();
  const names = new Set(Object.keys(QOPT.model_urls || {}));
  try { (await api("/api/llm/models")).models.forEach(m => names.add(m)); } catch { /* 기본 서버가 꺼져 있으면 목록 없음 */ }
  $("#l-model-list").innerHTML = [...names].map(x => `<option value="${esc(x)}">`).join("");
  qCombo();
}

function qCatalog() {
  const groups = Object.entries(QOPT.groups);
  $("#t-cat").innerHTML = groups.map(([g, title]) => `<details ${g !== "llm" ? "open" : ""}><summary><b>${esc(title)}</b></summary>
    <div class="grid cols-2" style="margin-top:8px">${QOPT.techniques.filter(t => t.group === g).map(t => `<div class="card stack" style="padding:10px">
      <div class="row between" style="flex-wrap:nowrap"><label class="row" style="margin:0;gap:6px">${t.run && g !== "llm" ? `<input type="checkbox" class="t-pick" value="${t.key}" ${DEFAULT_ON.has(t.key) || t.key === "float32" || t.key === "w_fp32" ? "checked" : ""} ${t.key === "float32" || t.key === "w_fp32" ? "disabled" : ""}>` : ""}<b>${esc(t.name)}</b></label>
        <span>${t.bits != null ? `<span class="badge">${esc(String(t.bits))}비트</span> ` : ""}<span class="badge ${t.run ? "ok" : ""}">${t.run ? "실행" : "설명"}</span></span></div>
      <div class="small">${esc(t.principle)}</div>
      <div class="small muted">장점: ${esc(t.pros)} · 한계: ${esc(t.cons)}</div>
      <div class="small muted">언제: ${esc(t.when)}</div></div>`).join("")}</div></details>`).join("");
  $$(".t-pick").forEach(x => x.addEventListener("change", qCombo));
  $("#v-dims").addEventListener("input", qCombo);
}
const picked = group => [...$$(".t-pick:checked")].map(x => x.value).filter(k => QOPT.techniques.find(t => t.key === k)?.group === group);
const qDims = () => $("#v-dims").value.split(",").map(s => parseInt(s.trim(), 10)).filter(n => n > 0);
const usesMrl = () => $$(".t-pick:checked").some(x => x.value === "mrl");
function qCombo() {
  const w = ["w_fp32", ...picked("weight").filter(k => k !== "w_fp32")], p = ["float32", ...picked("vector").filter(k => k !== "float32")];
  const dims = usesMrl() ? qDims() : [];
  const n = w.length * (dims.length + 1) * p.length;
  $("#v-combo").textContent = `조합 ${n}개 = 가중치 ${w.length} × 차원 ${dims.length + 1}${usesMrl() && !dims.length ? " (MRL 을 골랐으면 차원을 적으세요)" : ""} × 벡터 정밀도 ${p.length} — 모델마다 가중치 변형 수만큼 인코딩합니다${p.includes("pq") ? ", PQ 는 코드북 학습이 있어 느립니다" : ""}.`;
}

async function lDetail() {
  if (!$("#l-col").value) return;
  const d = await api(`/api/collections/${$("#l-col").value}`);
  $("#l-idx").innerHTML = d.indexes.filter(i => i.status === "ready").map(i => `<option value="${i.id}">${esc(i.model_hf_id.split(/[\\/]/).pop())} · #${i.id}</option>`).join("") || '<option value="">인덱스 없음</option>';
  const sets = (await api(`/api/collections/${d.id}/eval-sets`)).filter(s => s.status === "ready");
  $("#l-set").innerHTML = sets.map(s => `<option value="${s.id}">#${s.id} ${esc(s.name)} (${s.n_items}문항)</option>`).join("") || '<option value="">평가 세트 없음</option>';
}
$("#l-col").addEventListener("change", lDetail);

async function runJob(btn, path, body, box, render) {
  const job = await busy(btn, () => api(path, { method: "POST", body }));
  box.hidden = false; btn.disabled = true;
  try {
    const done = await pollJob(job.id, j => { box.innerHTML = `<div class="progress"><div style="width:${pct(j.progress)}%"></div></div><div class="small muted">${esc(j.message)}</div>`; }, 1500);
    if (done.status !== "done") { box.innerHTML = `<div class="errbox">${esc(done.error || done.status)}</div>`; return; }
    box.hidden = true; render(done.result);
  } finally { btn.disabled = false; }
}

$("#v-run").onclick = e => {
  const ids = selectedIds($("#v-models"));
  if (!ids.length || ids.length > 3) return toast("임베딩 모델을 1~3개 고르세요", "err");
  const body = { dataset: $("#v-ds").value, model_ids: ids, weights: ["w_fp32", ...picked("weight").filter(k => k !== "w_fp32")],
    precisions: ["float32", ...picked("vector").filter(k => k !== "float32")], dims: usesMrl() ? qDims() : [],
    rescore_mult: +$("#v-mult").value || 4, pq_m: +$("#v-pqm").value || 32, max_queries: +$("#v-n").value || null };
  runJob(e.target, "/api/quant/vectors", body, $("#v-progress"), vRender);
};

// 메모리(가로, 로그) - nDCG(세로) 그림. 색으로 조합을 구분하지 않는다(조합이 수십 개라 색으로는 구분이 안 됨) —
// 파레토 최적만 진하게 · 이름표, 나머지는 회색 점, 모든 점은 마우스를 올리면 조합 이름이 보이고 표에 같은 값이 있다.
function vChart(rows) {
  const ok = rows.filter(r => r.status === "ok");
  if (ok.length < 2) return "";
  const W = 640, H = 260, L = 48, R = 150, T = 20, B = 36;
  const lx = v => Math.log2(Math.max(v, 1));
  const xMin = Math.min(...ok.map(r => lx(r.bytes.ram))), xMax = Math.max(...ok.map(r => lx(r.bytes.ram)));
  const yMin = Math.max(0, Math.min(...ok.map(r => r.metrics["ndcg@10"])) - 0.02), yMax = Math.min(1, Math.max(...ok.map(r => r.metrics["ndcg@10"])) + 0.01);
  const X = v => L + (lx(v) - xMin) / (xMax - xMin || 1) * (W - L - R), Y = v => T + (1 - (v - yMin) / (yMax - yMin || 1)) * (H - T - B);
  const front = ok.filter(r => r.pareto).sort((a, b) => a.bytes.ram - b.bytes.ram);
  const ticks = [...new Set(ok.map(r => r.bytes.ram))].sort((a, b) => a - b);
  const tickTxt = b => (b >= 1024 ? `${(b / 1024).toFixed(b % 1024 ? 1 : 0)}KB` : `${b}B`);
  const yTicks = [0, 0.5, 1].map(f => yMin + f * (yMax - yMin));
  return `<svg viewBox="0 0 ${W} ${H}" width="100%" style="max-width:${W}px" role="img" aria-label="조합별 메모리-정확도">
    ${yTicks.map(v => `<line x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--border)"/><text x="${L - 6}" y="${Y(v) + 4}" text-anchor="end" font-size="11" fill="var(--muted)">${(v * 100).toFixed(1)}</text>`).join("")}
    ${ticks.filter((b, i) => i === 0 || X(b) - X(ticks[i - 1]) > 34).map(b => `<text x="${X(b)}" y="${H - B + 15}" text-anchor="middle" font-size="10" fill="var(--muted)">${tickTxt(b)}</text>`).join("")}
    <text x="${L - 6}" y="11" text-anchor="end" font-size="11" fill="var(--muted)">nDCG@10 ↑</text>
    <text x="${(L + W - R) / 2}" y="${H - 4}" text-anchor="middle" font-size="11" fill="var(--muted)">벡터당 메모리 (로그) →</text>
    <path d="${front.map((r, i) => `${i ? "L" : "M"}${X(r.bytes.ram).toFixed(1)},${Y(r.metrics["ndcg@10"]).toFixed(1)}`).join(" ")}" fill="none" stroke="var(--series-1)" stroke-width="2"/>
    ${ok.filter(r => !r.pareto).map(r => `<circle cx="${X(r.bytes.ram)}" cy="${Y(r.metrics["ndcg@10"])}" r="4" fill="var(--muted)" opacity=".55"><title>${esc(r.label)}: ${pct(r.metrics["ndcg@10"])} · ${r.bytes.ram}B</title></circle>`).join("")}
    ${front.map((r, i) => `<circle cx="${X(r.bytes.ram)}" cy="${Y(r.metrics["ndcg@10"])}" r="5" fill="var(--series-1)" stroke="var(--panel)" stroke-width="2"><title>${esc(r.label)}: ${pct(r.metrics["ndcg@10"])} · ${r.bytes.ram}B</title></circle>
      <text x="${X(r.bytes.ram) + 8}" y="${Y(r.metrics["ndcg@10"]) + (i % 2 ? 14 : -6)}" font-size="10" fill="var(--text)">${esc(r.label.length > 28 ? r.label.slice(0, 27) + "…" : r.label)}</text>`).join("")}
  </svg><div class="legend"><span><span class="swatch" style="background:var(--series-1)"></span>파레토 최적 (메모리 대비 정확도에서 다른 조합에 지지 않음)</span><span><span class="swatch" style="background:var(--muted)"></span>그 밖의 조합</span></div>`;
}

function vRender(r) {
  $("#v-out").innerHTML = r.results.map(m => m.status !== "ok" ? `<div class="errbox">${esc(m.hf_id)}: ${esc(m.error)}</div>` : `
    <h3>${esc(m.hf_id)} <span class="small muted">${m.dim}차원 · 문서 ${fmtNum(m.n_corpus)} · 질문 ${m.n_queries}</span></h3>
    ${vChart(m.rows)}
    <div class="table-wrap" style="max-height:520px"><table>
      <tr><th>조합</th><th class="num">nDCG@10 (95% 구간)</th><th>기준 대비</th><th class="num" title="기준 상위 10개 중 그대로 찾은 비율">기준 상위 10 유지</th>
        <th class="num">벡터당 메모리</th><th class="num" title="벡터 100만 개 · RAM / 디스크">100만 개</th><th class="num">질의당 검색</th><th class="num" title="이 가중치로 초당 인코딩한 글 수">인코딩</th></tr>
      ${m.rows.map(p => p.status !== "ok" ? `<tr><td class="small">${esc(p.weight)} ${esc(p.precision || "")}</td><td colspan="7"><div class="errbox">${esc(p.error)}</div></td></tr>` : `<tr>
        <td class="small"><b>${esc(p.label)}</b>${p.pareto ? ' <span class="badge ok">파레토</span>' : ""}${p.is_base ? ' <span class="badge">기준</span>' : ""}</td>
        <td class="num">${pct(p.metrics["ndcg@10"])} <span class="small muted">(${pct(p.ci[0])}–${pct(p.ci[1])})</span></td><td class="small nowrap">${vsTxt(p.vs_base)}</td><td class="num">${pct(p["overlap@10"])}</td>
        <td class="num">${p.bytes.ram} B <span class="small muted">(${(p.ram_ratio * 100).toFixed(1)}%)</span></td>
        <td class="num small">${fmtGB(p.gb_per_million.ram)} / ${fmtGB(p.gb_per_million.disk)}</td><td class="num small">${p.search_ms.toFixed(2)}ms</td><td class="num small">${p.encode_texts_per_s ?? "-"}/s</td></tr>`).join("")}
    </table></div>`).join("") + `<div class="small muted">질의당 검색 시간은 numpy 전수 비교 값이라 실제 벡터 DB 속도와 다릅니다(정밀도끼리 상대 비교용, PQ 는 코드북 학습 포함). 재점수 후보 = 상위 10 × ${r.options?.rescore_mult ?? "-"}.${r.run_id ? ` · run #${r.run_id}` : ""}</div>`;
}

$("#c-make").onclick = async e => {
  const alias = $("#c-alias").value.trim() || "gemma-quant";
  const r = await busy(e.target, () => api("/api/quant/llm-command", { method: "POST", body: { model_path: $("#c-file").value, alias, port: +$("#c-port").value || 8084, kv_k: $("#c-k").value, kv_v: $("#c-v").value } }));
  $("#c-out").innerHTML = `<div class="small muted">llama.cpp 폴더에서 실행 → .env 에 아래 줄을 넣고 앱을 다시 시작하면 모델 이름 <span class="mono">${esc(r.alias)}</span> 으로 비교 · 라우팅에 쓸 수 있습니다.</div>
    <pre class="small">${esc(r.command)}</pre><pre class="small">${esc(r.env_line)}</pre>`;
};

$("#l-run").onclick = e => {
  const models = $("#l-models").value.split(",").map(s => s.trim()).filter(Boolean);
  if (!models.length || models.length > 4) return toast("모델 이름을 1~4개 쉼표로 적으세요", "err");
  if (!$("#l-set").value || !$("#l-idx").value) return toast("인덱스와 평가 세트가 필요합니다", "err");
  runJob(e.target, "/api/quant/llm", { eval_set_id: +$("#l-set").value, config: { mode: "dense", index_id: +$("#l-idx").value }, models, max_queries: +$("#l-n").value || null }, $("#l-progress"), lRender);
};

function lRender(r) {
  const s = (x, k) => (x.summary?.[k] != null ? pct(x.summary[k]) : "-");
  $("#l-out").innerHTML = `<div class="table-wrap"><table>
    <tr><th>모델</th><th class="num">품질 (95% 구간)</th><th>기준 대비</th><th class="num">답변률</th><th class="num">근거 인용</th><th class="num">문장 근거율</th><th class="num">질문당 시간</th><th class="num" title="근거 · 질문을 읽는 속도 (llama-server 기록)">읽기 속도</th><th class="num" title="답을 쓰는 속도 (llama-server 기록)">생성 속도</th></tr>
    ${r.results.map(x => x.status !== "ok" ? `<tr><td>${esc(x.model)}</td><td colspan="8"><div class="errbox">${esc(x.error)}</div></td></tr>` : `<tr><td><b>${esc(x.model)}</b><div class="small muted">${esc(x.base_url)}</div></td>
      <td class="num">${pct(x.quality)} <span class="small muted">(${pct(x.quality_ci[0])}–${pct(x.quality_ci[1])})</span></td><td class="small nowrap">${vsTxt(x.vs_first)}</td>
      <td class="num">${s(x, "answer_rate")}</td><td class="num">${s(x, "evidence_cited")}</td><td class="num">${s(x, "sentence_support")}</td>
      <td class="num">${x.mean_seconds}s${x.prompt_seconds != null ? `<div class="small muted">읽기 ${x.prompt_seconds}s</div>` : ""}</td><td class="num">${x.prompt_per_second ?? "-"} tok/s</td><td class="num">${x.generation_per_second ?? x.tokens_per_second ?? "-"} tok/s</td></tr>`).join("")}
  </table></div><div class="small muted">품질 = 정답 근거를 인용한 비율(근거 문장이 없으면 문장 근거율). 질문 ${r.n_queries}개 · 모든 모델이 같은 근거를 받았고, 서버의 프롬프트 캐시는 끄고 쟀습니다(이전 실행이 남긴 캐시로 한 모델만 빨라 보이지 않게)${r.run_id ? ` · run #${r.run_id}` : ""}.</div>`;
}

qLoad();
