// 맵 · 연결 실행: 단계를 켜고 끄며 한 질문을 처리하고(단계별 상태 · 시간), 평가 세트로 연결 방식을 비교한다.
let fCol = null;
const F_STATUS = { run: "실행", off: "꺼짐", default: "기본 동작" };
// 단계 색은 단계(개체)를 따른다 — 어떤 연결 방식에서 어떤 단계가 빠져도 남은 단계의 색이 바뀌지 않게 고정 순서로 둔다.
const F_COLOR = { search_lab: 1, embedding: 2, rag: 3, rerank: 4, routing: 5, model: 6, answer: 7 };
// 막대 색만으로 읽지 않도록(밝은 화면에서 일부 색의 대비가 낮음) 막대 아래에 단계별 값을 글로도 적는다
const fmtMs = ms => (ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`);
const swatch = k => `<span class="swatch" style="background:var(--series-${F_COLOR[k]})"></span>`;

// 빠른 선택(부분 · 전체 연결). 향상 기법 · 리랭커는 '켬'일 때 위에서 고른 것을 쓰고, 고르지 않았으면 기본값을 넣는다.
const F_PRESETS = [
  { key: "search", label: "1→2 검색만", enh: false, rr: false, ans: false },
  { key: "rag", label: "1→2→답변", enh: false, rr: false, ans: true },
  { key: "enh", label: "4→1→2→답변", enh: true, rr: false, ans: true },
  { key: "full", label: "전체: 4→1→2→3→6→7·8→답변", enh: true, rr: true, ans: true },
];
let fLastEnh = "rewrite", fLastRr = "";

async function fLoad() {
  const cols = await api("/api/collections");
  $("#f-col").innerHTML = cols.map(c => `<option value="${c.id}">${esc(c.name)}</option>`).join("") || '<option value="">컬렉션 없음</option>';
  const saved = localGet("flow-col");
  if (saved && cols.some(c => String(c.id) === saved)) $("#f-col").value = saved;
  const rr = (await getModels()).filter(m => m.kind === "reranker" && m.cached);
  $("#f-rr").innerHTML += rr.map(r => `<option value="${r.id}">${esc(r.name)}</option>`).join("");
  fLastRr = rr[0] ? String(rr[0].id) : "";
  $("#f-presets").innerHTML += F_PRESETS.map(p => `<button class="btn sm" data-p="${p.key}">${esc(p.label)}</button>`).join("");
  $$("[data-p]", $("#f-presets")).forEach(b => (b.onclick = () => fApply(F_PRESETS.find(p => p.key === b.dataset.p))));
  $("#f-pick").innerHTML = '<span class="muted">비교할 연결:</span>' + F_PRESETS.map((p, i) => `<label class="row" style="margin:0;gap:4px"><input type="checkbox" value="${p.key}" ${i !== 2 ? "checked" : ""}> ${esc(p.label)}</label>`).join("");
  await fDetail();
}
async function fDetail() {
  if (!$("#f-col").value) return;
  fCol = await api(`/api/collections/${$("#f-col").value}`);
  const idx = fCol.indexes.filter(i => i.status === "ready");
  $("#f-idx").innerHTML = idx.map(i => `<option value="${i.id}">${esc(i.model_hf_id.split(/[\\/]/).pop())} · #${i.id}</option>`).join("") || '<option value="">준비된 인덱스 없음</option>';
  $("#f-cs").innerHTML = fCol.chunk_sets.filter(c => c.status === "ready").map(c => `<option value="${c.id}">${esc(c.name)}</option>`).join("");
  if (!idx.length) $("#f-mode").value = "bm25";
  fMode();
  const sets = (await api(`/api/collections/${fCol.id}/eval-sets`)).filter(s => s.status === "ready");
  $("#f-set").innerHTML = sets.map(s => `<option value="${s.id}">#${s.id} ${esc(s.name)} (${s.n_items}문항)</option>`).join("") || '<option value="">평가 세트 없음</option>';
}
function fMode() { const b = $("#f-mode").value === "bm25"; $("#f-idx-wrap").hidden = b; $("#f-cs-wrap").hidden = !b; }
function fApply(p) {
  if ($("#f-enh").value !== "none") fLastEnh = $("#f-enh").value;
  if ($("#f-rr").value) fLastRr = $("#f-rr").value;
  $("#f-enh").value = p.enh ? fLastEnh : "none";
  $("#f-rr").value = p.rr ? fLastRr : "";
  $("#f-ans").value = p.ans ? "1" : "0";
  toast(`${p.label}${p.rr && !fLastRr ? " — 받아 둔 리랭커가 없어 리랭킹은 꺼집니다" : ""}`);
}
$("#f-col").addEventListener("change", () => { localSet("flow-col", $("#f-col").value); fDetail(); });
$("#f-mode").addEventListener("change", fMode);

function fConfig(p) {
  const bm25 = $("#f-mode").value === "bm25";
  const enh = p ? (p.enh ? ($("#f-enh").value !== "none" ? $("#f-enh").value : fLastEnh) : "none") : $("#f-enh").value;
  const rr = p ? (p.rr ? ($("#f-rr").value || fLastRr) : "") : $("#f-rr").value;
  return {
    label: p?.label || "",
    config: { mode: $("#f-mode").value, index_id: bm25 ? null : +$("#f-idx").value || null, chunk_set_id: bm25 ? +$("#f-cs").value || null : null,
      reranker_id: +rr || null, enhance: enh === "none" ? null : { technique: enh } },
    answer: p ? p.ans : $("#f-ans").value === "1",
    context_top: +$("#f-top").value || 5,
  };
}

function fTrace(steps) {
  return `<div class="trace">${steps.map((s, i) => `<div class="trace-step ${s.status}" title="${esc(s.detail)}">
      <div class="row between" style="flex-wrap:nowrap;gap:4px"><span>${swatch(s.key)}<span class="stage-no">${esc(s.no)}</span> <b>${esc(s.title)}</b></span>${i < steps.length - 1 ? '<span class="muted">→</span>' : ""}</div>
      <div class="muted">${esc(s.stage)} · ${F_STATUS[s.status]}</div>
      <div><span class="ms">${s.status === "run" ? `${s.ms}ms` : "—"}</span></div>
      <div class="muted" style="overflow-wrap:anywhere">${esc(s.detail.slice(0, 90))}</div></div>`).join("")}</div>`;
}

$("#f-run").onclick = async e => {
  const q = $("#f-q").value.trim();
  if (!q) return toast("질문을 입력하세요", "err");
  const out = await busy(e.target, () => api("/api/flow/run", { method: "POST", body: { question: q, flow: fConfig() } }));
  const a = out.answer;
  $("#f-out").innerHTML = `<div class="stack" style="margin-top:8px">
    <div class="row between small"><b>처리 흐름</b><span class="muted">총 ${out.total_ms}ms${out.run_id ? ` · run #${out.run_id}` : ""}</span></div>
    ${fTrace(out.steps)}
    ${a ? `<div class="card stack"><b>답변</b><div style="white-space:pre-wrap">${esc(a.text)}</div>
      <div class="small muted">근거 있는 문장 ${a.supported_ratio != null ? `${(a.supported_ratio * 100).toFixed(0)}%` : "-"} · 인용 ${a.cited.length ? a.cited.map(n => `[${n}]`).join("") : "없음"}${a.invalid_citations.length ? ` · <span class="badge err">없는 근거 번호 ${a.invalid_citations.join(", ")}</span>` : ""}${a.refused ? ' · <span class="badge warn">근거에서 찾을 수 없음</span>' : ""}</div></div>` : ""}
    <div class="card stack"><b>근거 (상위 ${out.results.length})</b>${out.results.map(x => `<div class="small"><span class="badge">[${x.rank}]</span> <b>${esc(x.filename)}</b>${x.page ? ` p.${x.page}` : ""} <span class="muted">${esc(x.text.slice(0, 140))}</span></div>`).join("") || '<div class="empty">결과 없음</div>'}</div>
  </div>`;
};
$("#f-q").addEventListener("keydown", e => { if (e.key === "Enter") $("#f-run").click(); });

$("#f-eval").onclick = async e => {
  if (!$("#f-set").value) return toast("평가 세트가 없습니다", "err");
  const picked = $$("#f-pick input:checked").map(x => F_PRESETS.find(p => p.key === x.value));
  if (!picked.length) return toast("비교할 연결을 고르세요", "err");
  const body = { eval_set_id: +$("#f-set").value, flows: picked.map(fConfig), max_queries: +$("#f-n").value || null };
  const job = await busy(e.target, () => api("/api/flow/evaluate", { method: "POST", body }));
  const box = $("#f-progress"); box.hidden = false; e.target.disabled = true;
  try {
    const done = await pollJob(job.id, j => { box.innerHTML = `<div class="progress"><div style="width:${pct(j.progress)}%"></div></div><div class="small muted">${esc(j.message)}</div>`; }, 1500);
    if (done.status !== "done") { box.innerHTML = `<div class="errbox">${esc(done.error || done.status)}</div>`; return; }
    box.hidden = true; fRenderEval(done.result);
  } finally { e.target.disabled = false; }
};

function fRenderEval(r) {
  const ok = r.results.filter(x => x.status === "ok");
  const maxMs = Math.max(1, ...ok.map(x => x.steps.reduce((s, t) => s + t.mean_ms, 0)));
  const title = Object.fromEntries(r.steps.map(s => [s.key, `${s.no} ${s.title}`]));
  const used = r.steps.filter(s => ok.some(x => (x.steps.find(t => t.key === s.key)?.mean_ms || 0) > 0));
  const vs = x => (x.vs_first ? `${(x.vs_first.diff * 100).toFixed(1)}%p ${x.vs_first.significant ? '<span class="badge err">유의</span>' : '<span class="badge">불확실</span>'}` : "기준");
  const ans = (x, k) => (x.answer && x.answer[k] != null ? pct(x.answer[k]) : "-");
  $("#f-eval-out").innerHTML = `<div class="row between"><h3>결과 · ${esc(r.eval_set?.name || "")}</h3><span class="small muted">질문 ${r.n_queries}개${r.seconds != null ? ` · ${r.seconds}s` : ""}${r.run_id ? ` · run #${r.run_id}` : ""}</span></div>
    <div class="table-wrap"><table>
      <tr><th>연결</th><th class="num">nDCG@10</th><th class="num">Hit@1</th><th class="num">Hit@5</th><th>기준 대비</th><th class="num" title="'근거에서 찾을 수 없다'고 하지 않은 비율">답변률</th><th class="num" title="근거 문장을 담은 청크를 답변이 인용한 비율">근거 인용</th><th class="num" title="답변 문장 중 인용한 근거에 내용이 있는 비율">문장 근거율</th><th class="num">지연 평균/p95</th><th>단계별 평균 지연</th></tr>
      ${ok.map(x => `<tr><td class="small"><b>${esc(x.label)}</b></td><td class="num">${pct(x.metrics["ndcg@10"])}</td><td class="num">${pct(x.metrics["hit@1"])}</td><td class="num">${pct(x.metrics["hit@5"])}</td>
        <td class="small nowrap">${vs(x)}</td><td class="num">${ans(x, "answer_rate")}</td><td class="num">${ans(x, "evidence_cited")}</td><td class="num">${ans(x, "sentence_support")}</td>
        <td class="num small nowrap">${x.latency_ms.mean} / ${x.latency_ms.p95}ms</td>
        <td style="min-width:200px"><div class="stackbar" style="width:${Math.max(4, x.steps.reduce((s, t) => s + t.mean_ms, 0) / maxMs * 100)}%">${x.steps.filter(t => t.mean_ms > 0).map(t => `<span style="flex:${t.mean_ms};background:var(--series-${F_COLOR[t.key]})" title="${esc(title[t.key])}: ${t.mean_ms}ms"></span>`).join("")}</div>
          <div class="small muted" style="margin-top:2px">${x.steps.filter(t => t.mean_ms > 0).map(t => `${esc(title[t.key].split(" ").slice(1).join(" "))} ${fmtMs(t.mean_ms)}`).join(" · ")}</div></td></tr>`).join("")}
      ${r.results.filter(x => x.status !== "ok").map(x => `<tr><td class="small">${esc(x.label)}</td><td colspan="9"><div class="errbox">${esc(x.error)}</div></td></tr>`).join("")}
    </table></div>
    <div class="legend">${used.map(s => `<span>${swatch(s.key)}${esc(title[s.key])}</span>`).join("")}</div>
    <div class="small muted">검색 지표 · 답변 지표는 % 단위. 막대 길이 = 질문당 평균 처리 시간(가장 느린 연결 = 100%), 칸 = 단계별 시간(마우스를 올리면 값). '불확실'은 첫 연결과의 nDCG 차이가 우연일 수 있다는 뜻입니다.</div>`;
}

fLoad();
