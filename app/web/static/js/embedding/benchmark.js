let lastTrend = null;  // 테마가 바뀌면 다시 그릴 추세 데이터
let datasets = [];
let current = null; // 화면에 표시 중인 결과 { res, runId }
const histSelected = new Set();

async function loadDatasets(select) {
  datasets = await api("/api/datasets");
  $("#b-dataset").innerHTML = html.join(datasets.map(d => html`<option value="${d.name}">${d.title} [${d.type}${d.builtin ? "" : " · 사용자"}] (${d.size}${d.corpus_size ? html` / 문서 ${d.corpus_size}` : ""})</option>`), "");
  if (select) $("#b-dataset").value = select;
  showDesc();
}
function showDesc() {
  const d = datasets.find(x => x.name === $("#b-dataset").value);
  $("#b-ds-desc").textContent = d?.description || "";
}

function metricCols(type) {
  return type === "retrieval" ? ["ndcg@10", "mrr@10", "recall@1", "recall@3", "recall@5", "recall@10"] : ["spearman", "pearson"];
}

function renderResult(res, runId) {
  const type = res.dataset.type;
  const cols = metricCols(type);
  const ok = res.results.filter(r => r.status === "ok");
  const best = Object.fromEntries(cols.map(c => [c, Math.max(...ok.map(r => r.metrics[c]))]));
  const fastest = Math.max(...ok.map(r => r.texts_per_second || 0));
  const groups = [...new Set(ok.flatMap(r => Object.keys(r.by_group || {})))];
  const primary = res.primary_metric;
  const fmt = v => (type === "retrieval" ? pct(v) : v.toFixed(4));
  const hasCi = ok.some(r => r.ci);
  // 대표 지표 칸 아래에 95% 구간, 1위가 아닌 모델은 1위와의 짝지은 비교
  const ciCell = (r, c) => (c === primary && r.ci?.[c] ? html`<div class="small muted nowrap">${fmt(r.ci[c][0])}–${fmt(r.ci[c][1])}</div>` : "");
  const vsCell = r => {
    const v = r.vs_best;
    if (!v) return html`<td class="small muted">${hasCi && ok.length > 1 ? "기준" : ""}</td>`;
    const d = type === "retrieval" ? `${(v.diff * 100).toFixed(1)}%p` : v.diff.toFixed(4);
    return html`<td class="small nowrap" title="1위(${v.against}) 대비 ${primary} 차이의 95% 구간 ${html.join(v.ci, " ~ ")} · p=${v.p}">${d} ${v.significant ? html`<span class="badge err">유의한 차이</span>` : html`<span class="badge">차이 불확실</span>`}</td>`;
  };

  current = { res, runId };
  let out = html`<div class="card"><div class="row between"><h2>결과 · ${res.dataset.title || res.dataset.name}</h2>
    <div class="row"><span class="small muted">${res.truncate_dim ? html`truncate_dim=${res.truncate_dim} · ` : ""}${res.sweep_dims?.length ? "차원 스윕 · " : ""}총 ${res.total_seconds}s${runId ? html` · run #${runId}` : ""}</span>
      <button class="btn sm" onclick="exportReport(this)" title="표와 차트를 한 파일로 저장 (브라우저로 열기)">HTML 리포트</button>
      <button class="btn sm" onclick="exportJson()" title="원본 결과 데이터">JSON</button>
      ${runId ? html`<button class="btn sm danger" onclick="deleteRun(${runId}, true)">이 결과 삭제</button>` : ""}</div></div>
    <div class="table-wrap"><table><tr><th>#</th><th>모델</th>${html.join(cols.map(c => html`<th class="num">${c}</th>`), "")}${hasCi && ok.length > 1 ? html`<th>1위 대비</th>` : ""}<th class="num">차원</th><th class="num">texts/s</th><th class="num">인코딩</th><th class="num">로드</th></tr>
    ${html.join(res.results.map((r, i) => r.status !== "ok"
      ? html`<tr><td>-</td><td class="mono">${r.hf_id}</td><td colspan="${cols.length + 4 + (hasCi && ok.length > 1 ? 1 : 0)}"><div class="errbox">${r.error}</div></td></tr>`
      : html`<tr><td>${i + 1}</td><td class="mono">${r.hf_id}${r.warnings?.length ? html` <span class="badge warn" title="${html.join(r.warnings, "\n")}">경고</span>` : ""}</td>
        ${html.join(cols.map(c => html`<td class="num ${r.metrics[c] === best[c] && ok.length > 1 ? "best" : ""}">${fmt(r.metrics[c])}${ciCell(r, c)}</td>`), "")}
        ${hasCi && ok.length > 1 ? vsCell(r) : ""}<td class="num">${r.dim}</td><td class="num ${r.texts_per_second === fastest && ok.length > 1 ? "best" : ""}">${r.texts_per_second ?? "-"}</td>
        <td class="num">${r.encode_seconds}s</td><td class="num">${r.load_seconds ? r.load_seconds + "s" : "-"}</td></tr>`), "")}
    </table></div>
    <p class="small muted">${type === "retrieval" ? "검색 지표는 % 단위. " : ""}굵은 초록색 = 최고값.${hasCi ? html` ${primary} 아래 숫자는 95% 신뢰구간(${type === "retrieval" ? "질문" : "문장쌍"}을 ${res.bootstrap?.n || 1000}번 다시 뽑아 계산)입니다. '차이 불확실'은 같은 ${type === "retrieval" ? "질문" : "문장쌍"}에 대한 짝지은 비교에서 1위와의 차이가 우연일 수 있다는 뜻으로, 평가 데이터를 늘려야 순위를 믿을 수 있습니다.` : ""}</p></div>
    <div id="b-charts"></div>`;

  if (groups.length) {
    out += html`<div class="card mt-4"><h2>언어/그룹별 ${primary}</h2><div class="table-wrap"><table>
      <tr><th>모델</th>${html.join(groups.map(g => html`<th class="num">${g} <span class="muted">(n=${ok[0].by_group[g]?.n ?? "?"})</span></th>`), "")}</tr>
      ${html.join(ok.map(r => html`<tr><td class="mono">${r.hf_id}</td>${html.join(groups.map(g => {
        const v = r.by_group[g]?.[primary]; const b = Math.max(...ok.map(x => x.by_group[g]?.[primary] ?? -1));
        return html`<td class="num ${v === b && ok.length > 1 ? "best" : ""}">${pct(v)}</td>`; }), "")}</tr>`), "")}
    </table></div></div>`;
  }

  if (type === "retrieval" && ok.length) {
    const queries = ok[0].per_query.map(q => q.id);
    out += html`<div class="card mt-4"><h2>쿼리별 첫 정답 순위</h2>
      <p class="small muted">숫자 = 첫 번째 정답 문서의 순위 (1이 최상). 초록 칸 = 1위, 빨간 칸(굵게) = Top-3 밖. 칸에 마우스를 올리면 Top-5 문서가 보입니다.</p><div class="table-wrap"><table>
      <tr><th>쿼리</th>${html.join(ok.map(r => html`<th class="num" title="${r.hf_id}">${r.hf_id.split("/").pop()}</th>`), "")}</tr>
      ${html.join(queries.map((qid, qi) => html`<tr><td class="small"><span class="badge muted">${ok[0].per_query[qi].lang || ""}</span> ${ok[0].per_query[qi].text}</td>
        ${html.join(ok.map(r => { const pq = r.per_query[qi]; const rank = pq.rank_of_first_relevant;
          const cls = rank === 1 ? "rank-good" : rank == null || rank > 3 ? "rank-bad" : "";
          return html`<td class="num ${cls}" title="Top5: ${html.join(pq.top.map(t => html`${t.id}${t.relevant ? "✓" : ""} ${t.score}`), ", ")}" style="${cls === "rank-bad" ? "font-weight:700" : ""}">${rank ?? "-"}</td>`; }), "")}</tr>`), "")}
      </table></div></div>`;
  }
  if (type === "sts" && ok.length) {
    out += html`<div class="card mt-4"><h2>문장쌍별 코사인 유사도</h2><div class="table-wrap"><table>
      <tr><th>문장 1</th><th>문장 2</th><th class="num">정답</th>${html.join(ok.map(r => html`<th class="num">${r.hf_id.split("/").pop()}</th>`), "")}</tr>
      ${html.join(ok[0].per_pair.map((p, i) => html`<tr><td class="small">${p.s1}</td><td class="small">${p.s2}</td><td class="num">${p.gold}</td>
        ${html.join(ok.map(r => html`<td class="num">${r.per_pair[i].cosine.toFixed(3)}</td>`), "")}</tr>`), "")}
      </table></div></div>`;
  }
  $("#b-result").innerHTML = out;
  renderCharts(res);
}

// 레이더의 STS 축: 가장 최근 STS 데이터셋의 실행들을 최신순으로 합쳐 모델별 최신 Spearman 을 가져온다
async function latestStsScores() {
  const stsNames = new Set(datasets.filter(d => d.type === "sts").map(d => d.name));
  const runs = (await api("/api/runs?kind=benchmark&limit=100")).filter(r => stsNames.has(r.params?.dataset));
  if (!runs.length) return null;
  const name = runs[0].params.dataset;
  const scores = {};
  let title = name;
  for (const run of runs.filter(r => r.params.dataset === name).slice(0, 10)) {
    const detail = await api(`/api/runs/${run.id}`);
    title = detail.result.dataset.title || name;
    detail.result.results.filter(r => r.status === "ok").forEach(r => { if (!(r.hf_id in scores)) scores[r.hf_id] = r.metrics.spearman; });
  }
  return { scores, title };
}

async function renderCharts(res) {
  const root = $("#b-charts");
  if (!root || typeof BenchCharts === "undefined") return;
  if (typeof Chart === "undefined") {
    root.innerHTML = html`<div class="warnbox mt-4">차트 라이브러리(Chart.js CDN)를 불러오지 못했습니다. 인터넷 연결을 확인하세요. 결과 표는 그대로 사용할 수 있습니다.</div>`;
    return;
  }
  try {
    const sts = res.dataset.type === "retrieval" ? await latestStsScores() : null;
    await BenchCharts.render(root, res, { stsScores: sts?.scores ?? null, stsTitle: sts?.title ?? "" });
  } catch (e) {
    root.innerHTML = html`<div class="errbox">차트를 그리지 못했습니다: ${e.message}</div>`;
  }
}

const historyDataset = () => ($("#h-only-ds").checked ? $("#b-dataset").value : "");
let historyRuns = [];

async function loadHistory() {
  const ds = historyDataset();
  historyRuns = await api(`/api/runs?kind=benchmark&limit=100${ds ? `&dataset=${encodeURIComponent(ds)}` : ""}`);
  [...histSelected].forEach(id => { if (!historyRuns.some(r => r.id === id)) histSelected.delete(id); });
  $("#h-del-all").textContent = ds ? "이 데이터셋 이력 전체 삭제" : "벤치마크 이력 전체 삭제";
  $("#h-del-all").disabled = historyRuns.length === 0;
  $("#b-history").innerHTML = historyRuns.length ? html`<div class="table-wrap"><table><tr><th><input type="checkbox" id="h-sel-all" aria-label="전체 선택"></th><th>#</th><th>제목</th><th>모델</th><th>옵션</th><th>시간</th><th></th></tr>${html.join(historyRuns.map(r => html`
    <tr><td><input type="checkbox" class="h-sel" value="${r.id}" ${histSelected.has(r.id) ? "checked" : ""} aria-label="#${r.id} 선택"></td>
    <td>${r.id}</td><td>${r.title}</td><td class="small mono">${html.join(r.model_hf_ids, "<br>")}</td>
    <td class="small muted">${r.params?.truncate_dim ? html`차원 ${r.params.truncate_dim}` : ""}${r.params?.sweep_dims?.length ? "차원 스윕" : ""}</td>
    <td class="nowrap small">${fmtDate(r.created_at)}</td>
    <td class="right nowrap"><button class="btn sm" onclick="showRun(${r.id})">보기</button><button class="btn sm danger" onclick="deleteRun(${r.id})">삭제</button></td></tr>`), "")}</table></div>`
    : html`<div class="empty">아직 없음</div>`;
  updateHistSelection();
}
function updateHistSelection() {
  $("#h-sel-count").textContent = `${histSelected.size}개 선택`;
  $("#h-del-sel").disabled = histSelected.size === 0;
  const all = $("#h-sel-all");
  if (all) { all.checked = historyRuns.length > 0 && historyRuns.every(r => histSelected.has(r.id)); all.indeterminate = histSelected.size > 0 && !all.checked; }
}
async function refreshHistory() { await Promise.all([loadHistory(), loadTrend()]); }

async function deleteRun(id, fromResult = false) {
  if (!(await ui.confirm(`벤치마크 결과 #${id} 을(를) 삭제할까요? 되돌릴 수 없습니다.`, { ok: "삭제", danger: true, title: "삭제" }))) return;
  await api(`/api/runs/${id}`, { method: "DELETE" });
  histSelected.delete(id);
  if (fromResult || current?.runId === id) { $("#b-result").innerHTML = ""; current = null; }
  toast("삭제했습니다", "ok");
  refreshHistory();
}

async function loadTrend() {
  const ds = $("#b-dataset").value;
  const d = datasets.find(x => x.name === ds);
  $("#trend-title").textContent = d?.title || ds;
  if (typeof Chart === "undefined") return;
  const data = await api(`/api/benchmarks/trend?dataset=${encodeURIComponent(ds)}`);
  const enough = data.runs >= 2 && data.series.length > 0;
  $("#trend-box").hidden = !enough;
  $("#trend-empty").hidden = enough;
  $("#trend-sub").textContent = `${data.runs}회 실행의 모델별 ${data.primary_metric || "대표 지표"}입니다. 라이브러리·모델 업데이트 후 성능이 바뀌었는지 확인할 때 씁니다.`
    + (data.skipped_truncated ? ` 차원을 줄여 실행한 ${data.skipped_truncated}건은 비교할 수 없어 제외했습니다.` : "");
  if (enough) { lastTrend = data; BenchCharts.renderTrend($("#ch-trend"), data); }
}

// ── 내보내기 ──
function download(name, text, type) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type }));
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
const reportName = ext => `benchmark_${current.res.dataset.name}${current.runId ? `_run${current.runId}` : ""}.${ext}`;

function exportJson() {
  if (!current) return;
  download(reportName("json"), JSON.stringify({ run_id: current.runId, ...current.res }, null, 2), "application/json");
}

async function exportReport(btn) {
  if (!current) return;
  await busy(btn, async () => {
    let css = await (await fetch("/static/css/style.css")).text();
    // 차트 이미지는 지금 테마 색으로 그려지므로 리포트도 같은 테마로 고정한다
    const darkBlock = /@media \(prefers-color-scheme: dark\) \{\s*(:root \{[\s\S]*?\})\s*\}/.exec(css);
    if (darkBlock) css = css.replace(darkBlock[0], matchMedia("(prefers-color-scheme: dark)").matches ? darkBlock[1] : "");
    const sys = await api("/api/system");
    const clone = $("#b-result").cloneNode(true);
    const origCards = $$("#b-result .chart-card");
    $$(".chart-card", clone).forEach((card, i) => {
      const img = BenchCharts.cardToCanvas(origCards[i]);
      $$(".chart-box, .multiples, .picker, #sweep-mode, .png-btn, .tabs", card).forEach(el => el.remove());
      if (img) card.insertAdjacentHTML("beforeend", html`<img src="${img.toDataURL("image/png")}" alt="${card.querySelector("h3")?.textContent || ""}" style="width:100%;height:auto">`);
    });
    $$("button, input, script", clone).forEach(el => el.remove());
    $$("details", clone).forEach(d => d.setAttribute("open", ""));
    const r = current.res;
    const page = html`<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>벤치마크 리포트 · ${r.dataset.title || r.dataset.name}</title><style>${css}</style></head><body><main class="container">
<h1>벤치마크 리포트 · ${r.dataset.title || r.dataset.name}</h1>
<p class="lead">${current.runId ? html`run #${current.runId} · ` : ""}생성 ${new Date().toLocaleString("ko-KR")} · ${r.results.length}개 모델 · 총 ${r.total_seconds}s${r.truncate_dim ? html` · truncate_dim=${r.truncate_dim}` : ""}<br>
환경: Python ${sys.python} · ${sys.device}/${sys.dtype} · sentence-transformers ${sys.packages["sentence-transformers"]} · transformers ${sys.packages.transformers} · torch ${sys.packages.torch}</p>
${clone.innerHTML}
<p class="small muted" style="margin-top:24px">LLM Engineering Atlas 에서 생성한 리포트입니다. 차트는 생성 시점의 이미지입니다.</p>
</main></body></html>`;
    download(reportName("html"), String(page), "text/html");
  });
}

async function showRun(id) {
  const run = await api(`/api/runs/${id}`);
  renderResult(run.result, run.id);
  $("#b-result").scrollIntoView({ behavior: "smooth" });
}

$("#b-run").onclick = async e => {
  const model_ids = selectedIds($("#b-models"));
  if (!model_ids.length) return toast("모델을 선택하세요", "err");
  const body = { model_ids, dataset: $("#b-dataset").value, truncate_dim: $("#b-dim").value ? Number($("#b-dim").value) : null,
                 batch_size: $("#b-batch").value ? Number($("#b-batch").value) : null, unload_after: $("#b-unload").checked };
  if ($("#b-sweep").checked) {
    body.sweep_dims = $("#b-sweep-dims").value.split(",").map(s => parseInt(s, 10)).filter(n => n >= 8);
    body.truncate_dim = null;
    if (!body.sweep_dims.length) return toast("스윕할 차원을 입력하세요 (예: 768,512,256,128)", "err");
  }
  const job = await busy(e.target, () => api("/api/benchmarks", { method: "POST", body }));
  const box = $("#b-progress");
  box.hidden = false;
  e.target.disabled = true;
  try {
    const done = await pollJob(job.id, j => { box.innerHTML = ui.jobProgress(j); });
    if (done.status === "done") { renderResult(done.result, done.result.run_id); box.hidden = true; toast("벤치마크 완료", "ok"); }
    else ui.error(box, done.status === "cancelled" ? "취소했습니다." : (done.error || done.status));
  } finally {
    e.target.disabled = false;
    refreshHistory(); getModels(true).then(() => fillModelSelect($("#b-models")));
  }
};

$("#b-dataset").addEventListener("change", () => { showDesc(); histSelected.clear(); refreshHistory(); });
$("#h-only-ds").addEventListener("change", () => { histSelected.clear(); loadHistory(); });
$("#b-history").addEventListener("change", e => {
  if (e.target.id === "h-sel-all") {
    historyRuns.forEach(r => (e.target.checked ? histSelected.add(r.id) : histSelected.delete(r.id)));
    $$("#b-history .h-sel").forEach(cb => (cb.checked = e.target.checked));
  } else if (e.target.classList.contains("h-sel")) {
    const id = Number(e.target.value);
    e.target.checked ? histSelected.add(id) : histSelected.delete(id);
  } else return;
  updateHistSelection();
});
$("#h-del-sel").onclick = async e => {
  if (!(await ui.confirm(`선택한 ${histSelected.size}건의 벤치마크 결과를 삭제할까요? 되돌릴 수 없습니다.`, { ok: "삭제", danger: true, title: "삭제" }))) return;
  const ids = [...histSelected];
  const r = await busy(e.target, () => api("/api/runs/bulk-delete", { method: "POST", body: { ids } }));
  if (current && ids.includes(current.runId)) { $("#b-result").innerHTML = ""; current = null; }
  histSelected.clear(); toast(`${r.deleted}건 삭제`, "ok"); refreshHistory();
};
$("#h-del-all").onclick = async e => {
  const ds = historyDataset();
  const scope = ds ? `'${datasets.find(d => d.name === ds)?.title || ds}' 데이터셋의 벤치마크 이력을 모두` : "모든 벤치마크 이력을";
  if (!(await ui.confirm(`${scope} 삭제할까요? 되돌릴 수 없습니다.`, { ok: "삭제", danger: true, title: "삭제" }))) return;
  const r = await busy(e.target, () => api(`/api/runs?confirm=true&kind=benchmark${ds ? `&dataset=${encodeURIComponent(ds)}` : ""}`, { method: "DELETE" }));
  if (current?.runId) { $("#b-result").innerHTML = ""; current = null; }
  histSelected.clear(); toast(`${r.deleted}건 삭제`, "ok"); refreshHistory();
};

$("#b-sweep").addEventListener("change", e => {
  // 스윕은 전체 차원 기준이므로 단일 차원 선택과 함께 쓰지 않는다
  $("#b-sweep-dims").disabled = !e.target.checked;
  $("#b-dim").disabled = e.target.checked;
});
$("#b-models").addEventListener("change", () => { fillDimSelect($("#b-models"), $("#b-dim")); $("#b-count").textContent = `${selectedIds($("#b-models")).length}개 선택`; });
$("#b-upload").addEventListener("change", async e => {
  const f = e.target.files[0]; if (!f) return;
  const form = new FormData(); form.append("file", f);
  try { const r = await api("/api/datasets", { method: "POST", form }); toast(`데이터셋 '${r.name}' 업로드됨`, "ok"); loadDatasets(r.name); }
  catch (err) { toast(err.message, "err"); }
  e.target.value = "";
});
$("#b-del-ds").onclick = async () => {
  const name = $("#b-dataset").value;
  if (!(await ui.confirm(`데이터셋 '${name}' 을 삭제할까요?`, { ok: "삭제", danger: true, title: "삭제" }))) return;
  try { await api(`/api/datasets/${name}`, { method: "DELETE" }); toast("삭제됨", "ok"); loadDatasets(); } catch (err) { toast(err.message, "err"); }
};

// ── 공개 벤치마크 ──
async function loadPublic() {
  const rows = await api("/api/public-benchmarks");
  $("#pub-list").innerHTML = html`<table>${html.join(rows.map(c => html`<tr>
    <td><b>${c.title}</b> <span class="badge">${c.type}</span><div class="small muted">${c.description}</div><div class="small muted">${c.repo} · ${c.license}</div></td>
    <td class="small nowrap">${c.imported ? html`<span class="badge ok">가져옴</span> ${c.type === "sts" ? "문장쌍" : "질문"} ${c.imported.size}${c.imported.corpus_size ? html` / 문서 ${c.imported.corpus_size}` : ""}` : ""}</td>
    <td class="right nowrap">${c.imported ? html`<button class="btn sm" onclick="loadDatasets('${c.dataset}')">선택</button>` : ""}<button class="btn sm" onclick="importPublic(this, '${c.key}')">${c.imported ? "다시 가져오기" : "가져오기"}</button></td></tr>`), "")}</table>`;
}
async function importPublic(btn, key) {
  const body = { max_queries: +$("#pub-q").value || null, max_corpus: +$("#pub-c").value || null };
  const job = await busy(btn, () => api(`/api/public-benchmarks/${key}/import`, { method: "POST", body }));
  btn.disabled = true;
  try {
    const done = await pollJob(job.id, j => { btn.textContent = `${pct(j.progress)}%`; }, 700);
    if (done.status !== "done") return toast(done.error || done.status, "err");
    toast(`${done.result.title} — ${done.result.size}`, "ok");
    await loadDatasets(done.result.name); loadPublic();
  } finally { btn.disabled = false; }
}

(async () => {
  $("#pub-box").addEventListener("toggle", e => { if (e.target.open) loadPublic(); });
  await loadDatasets();
  await fillModelSelect($("#b-models"));
  fillDimSelect($("#b-models"), $("#b-dim"));
  refreshHistory();
  const runId = sessionStorage.getItem("run");  // 이력 화면에서 넘어온 경우
  if (runId) { sessionStorage.removeItem("run"); showRun(Number(runId)); }
})();

// 테마(◐ · OS)가 바뀌면 추세 차트도 새 색으로 (결과 차트는 lib/charts.js 가 직접 다시 그린다)
window.addEventListener("themechange", () => { if (lastTrend) BenchCharts.renderTrend($("#ch-trend"), lastTrend); });
