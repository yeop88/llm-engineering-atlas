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
  { key: "full", label: "전체: 4→1→2→3→답변", enh: true, rr: true, ans: true },
  { key: "agent", label: "1→2→8a 에이전트", enh: false, rr: false, ans: true, mode: "agent" },
  // 6 라우팅: 쉬운 질문은 1→2→답변, 확신도가 낮은 질문만 전체 경로(+에이전트) — 맵의 '쉬운 질문 / 어려운 질문' 갈래 그대로
  { key: "routed", label: "6 라우팅: 쉬우면 1→2→답변, 어려우면 4→3→8a 에이전트", enh: true, rr: true, ans: true, route: "confidence", mode: "agent" },
];
let fLastEnh = "rewrite", fLastRr = "";

async function fLoad() {
  const cols = await api("/api/collections");
  $("#f-col").innerHTML = cols.map(c => `<option value="${c.id}">${esc(c.name)}</option>`).join("") || '<option value="">컬렉션 없음</option>';
  applyCtx($("#f-col"));
  const rr = (await getModels()).filter(m => m.kind === "reranker" && m.cached);
  $("#f-rr").innerHTML += rr.map(r => `<option value="${r.id}">${esc(r.name)}</option>`).join("");
  fLastRr = rr[0] ? String(rr[0].id) : "";
  $("#f-presets").innerHTML += F_PRESETS.map(p => `<button class="btn sm" data-p="${p.key}">${esc(p.label)}</button>`).join("");
  $$("[data-p]", $("#f-presets")).forEach(b => (b.onclick = () => fApply(F_PRESETS.find(p => p.key === b.dataset.p))));
  $("#f-pick").innerHTML = '<span class="muted">비교할 연결:</span>' + F_PRESETS.map((p, i) => `<label class="row m-0 gap-1"><input type="checkbox" value="${p.key}" ${["search", "rag", "full", "routed"].includes(p.key) ? "checked" : ""}> ${esc(p.label)}</label>`).join("");
  await fDetail();
}
async function fDetail() {
  if (!$("#f-col").value) return;
  fCol = await api(`/api/collections/${$("#f-col").value}`);
  const idx = fCol.indexes.filter(i => i.status === "ready");
  $("#f-idx").innerHTML = idx.map(i => `<option value="${i.id}">${esc(i.model_hf_id.split(/[\\/]/).pop())} · #${i.id}</option>`).join("") || '<option value="">준비된 인덱스 없음</option>';
  applyCtx($("#f-idx"));
  $("#f-cs").innerHTML = fCol.chunk_sets.filter(c => c.status === "ready").map(c => `<option value="${c.id}">${esc(c.name)}</option>`).join("");
  applyCtx($("#f-cs"));
  if (!idx.length) $("#f-mode").value = "bm25";
  fMode();
  const sets = (await api(`/api/collections/${fCol.id}/eval-sets`)).filter(s => s.status === "ready");
  $("#f-set").innerHTML = sets.map(s => `<option value="${s.id}">#${s.id} ${esc(s.name)} (${s.n_items}문항)</option>`).join("") || '<option value="">평가 세트 없음</option>';
  applyCtx($("#f-set"));
}
function fMode() { const b = $("#f-mode").value === "bm25"; $("#f-idx-wrap").hidden = b; $("#f-cs-wrap").hidden = !b; }
function fApply(p) {
  if ($("#f-enh").value !== "none") fLastEnh = $("#f-enh").value;
  if ($("#f-rr").value) fLastRr = $("#f-rr").value;
  $("#f-enh").value = p.enh ? fLastEnh : "none";
  $("#f-rr").value = p.rr ? fLastRr : "";
  $("#f-ans").value = p.ans ? "1" : "0";
  $("#f-route").value = p.route || "off";
  $("#f-ansmode").value = p.mode || "rag";
  toast(`${p.label}${p.rr && !fLastRr ? " — 받아 둔 리랭커가 없어 리랭킹은 꺼집니다" : ""}`);
}
$("#f-col").addEventListener("change", () => { fDetail(); });
$("#f-mode").addEventListener("change", fMode);

function fConfig(p) {
  const bm25 = $("#f-mode").value === "bm25";
  const enh = p ? (p.enh ? ($("#f-enh").value !== "none" ? $("#f-enh").value : fLastEnh) : "none") : $("#f-enh").value;
  const rr = p ? (p.rr ? ($("#f-rr").value || fLastRr) : "") : $("#f-rr").value;
  const search = { mode: $("#f-mode").value, index_id: bm25 ? null : +$("#f-idx").value || null, chunk_set_id: bm25 ? +$("#f-cs").value || null : null };
  const answer = p ? p.ans : $("#f-ans").value === "1";
  // 답변 방식(8a 에이전트 · 8b Best-of-N)은 비싼 쪽 경로에만 붙인다 — 라우팅을 켜면 어려운 질문에만 쓰인다
  const mode = p ? p.mode || "rag" : $("#f-ansmode").value;
  const how = mode === "agent" ? { agent: { max_steps: 5, top_k: 4 } } : mode === "best" ? { best_of: 4 } : {};
  const comp = +$("#f-compress").value ? { compress: { keep: +$("#f-compress").value } } : {};
  const full = { config: { ...search, reranker_id: +rr || null, rerank_top: 10, enhance: enh === "none" ? null : { technique: enh } }, answer, context_top: +$("#f-top").value || 5, ...how, ...comp };
  const router = p ? p.route : $("#f-route").value !== "off" ? $("#f-route").value : null;
  if (!router) return { label: p?.label || "", ...full };
  // 라우팅을 켜면 위의 향상 · 리랭커 설정은 '어려운 질문용 전체 경로'가 되고, 기본 경로는 향상 · 리랭커 없이 간다
  // 학습 라우터는 'learned:<id>' 값으로 고른다(라우팅 화면에서 저장한 것)
  const learned = router.startsWith("learned:") ? { router: "learned", learned_id: +router.split(":")[1] } : { router };
  return { label: p?.label || "", config: search, answer, context_top: full.context_top, ...comp, routing: { ...learned, threshold: +$("#f-th").value || 0.05, hard: full } };
}

function fTrace(steps) {
  return `<div class="trace">${steps.map((s, i) => `<div class="trace-step ${s.status}" title="${esc(s.detail)}">
      <div class="row between nowrap-row gap-1"><span>${swatch(s.key)}<span class="stage-no">${esc(s.no)}</span> <b>${esc(s.title)}</b></span>${i < steps.length - 1 ? '<span class="muted">→</span>' : ""}</div>
      <div class="muted">${esc(s.stage)} · ${F_STATUS[s.status]}</div>
      <div><span class="ms">${s.status === "run" ? `${s.ms}ms` : "—"}</span></div>
      <div class="muted" style="overflow-wrap:anywhere">${esc(s.detail.slice(0, 90))}</div></div>`).join("")}</div>`;
}

$("#f-run").onclick = async e => {
  const q = $("#f-q").value.trim();
  if (!q) return toast("질문을 입력하세요", "err");
  const out = await busy(e.target, () => api("/api/flow/run", { method: "POST", body: { question: q, flow: fConfig() } }));
  const a = out.answer;
  $("#f-out").innerHTML = `<div class="stack mt-2">
    <div class="row between small"><b>처리 흐름</b><span class="muted">총 ${out.total_ms}ms${out.run_id ? ` · run #${out.run_id}` : ""}</span></div>
    ${fTrace(out.steps)}
    ${a ? `<div class="card stack"><b>답변</b><div class="pre">${esc(a.text)}</div>
      <div class="small muted">근거 있는 문장 ${a.supported_ratio != null ? `${(a.supported_ratio * 100).toFixed(0)}%` : "-"} · 인용 ${a.cited.length ? a.cited.map(n => `[${n}]`).join("") : "없음"}${a.invalid_citations.length ? ` · <span class="badge err">없는 근거 번호 ${a.invalid_citations.join(", ")}</span>` : ""}${a.refused ? ' · <span class="badge warn">근거에서 찾을 수 없음</span>' : ""}</div>${citeBox(a.citations)}</div>` : ""}
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
    const done = await pollJob(job.id, j => { box.innerHTML = ui.jobProgress(j); }, 1500);
    if (done.status !== "done") { ui.error(box, done.status === "cancelled" ? "취소했습니다." : (done.error || done.status)); return; }
    box.hidden = true; fRenderEval(done.result);
  } finally { e.target.disabled = false; }
};

function fRenderEval(r) {
  const ok = r.results.filter(x => x.status === "ok");
  const maxMs = Math.max(1, ...ok.map(x => x.steps.reduce((s, t) => s + t.mean_ms, 0)));
  const title = Object.fromEntries(r.steps.map(s => [s.key, `${s.no} ${s.title}`]));
  const used = r.steps.filter(s => ok.some(x => (x.steps.find(t => t.key === s.key)?.mean_ms || 0) > 0));
  // 답변이 있으면 답변 품질로 비교한다 — 첫 검색이 같은 경로(RAG vs 에이전트)는 nDCG 차이가 늘 0 이라 차이를 숨겼다
  const vsOne = (d, name) => `${name} ${d.diff >= 0 ? "+" : ""}${(d.diff * 100).toFixed(1)}%p ${d.significant ? '<span class="badge err">유의</span>' : '<span class="badge">불확실</span>'}`;
  const vs = x => (x.vs_first_quality ? vsOne(x.vs_first_quality, "품질") : x.vs_first ? vsOne(x.vs_first, "nDCG") : "기준");
  const ans = (x, k) => (x.answer && x.answer[k] != null ? pct(x.answer[k]) : "-");
  $("#f-eval-out").innerHTML = `<div class="row between"><h3>결과 · ${esc(r.eval_set?.name || "")}</h3><span class="small muted">질문 ${r.n_queries}개${r.seconds != null ? ` · ${r.seconds}s` : ""}${r.run_id ? ` · run #${r.run_id}` : ""}</span></div>
    <div class="table-wrap"><table>
      <tr><th>연결</th><th class="num">nDCG@10</th><th class="num">Hit@1</th><th class="num">Hit@5</th><th>기준 대비</th><th class="num" title="'근거에서 찾을 수 없다'고 하지 않은 비율">답변률</th><th class="num" title="근거 문장을 담은 청크를 답변이 인용한 비율">근거 인용</th><th class="num" title="답변 문장 중 인용한 근거에 내용이 있는 비율">문장 근거율</th><th class="num" title="답변 문장 중 질문과 관련된 비율 — 근거에 있어도 질문과 상관없는 문장은 틀린 답">질문 관련</th><th class="num">지연 평균/p95</th><th>단계별 평균 지연</th></tr>
      ${ok.map(x => `<tr><td class="small"><b>${esc(x.label)}</b>${x.hard_rate != null ? `<div class="muted">어려움으로 보냄 ${pct(x.hard_rate)}%</div>` : ""}</td><td class="num">${pct(x.metrics["ndcg@10"])}</td><td class="num">${pct(x.metrics["hit@1"])}</td><td class="num">${pct(x.metrics["hit@5"])}</td>
        <td class="small nowrap">${vs(x)}</td><td class="num">${ans(x, "answer_rate")}${x.answer?.n_unanswerable ? `<div class="small muted" title="답 없는 질문을 올바르게 거절한 비율">답 없음 거절 ${ans(x, "correct_refusal")}</div>` : ""}</td><td class="num">${ans(x, "evidence_cited")}</td><td class="num">${ans(x, "sentence_support")}</td><td class="num">${ans(x, "relevant_ratio")}</td>
        <td class="num small nowrap">${x.latency_ms.mean} / ${x.latency_ms.p95}ms</td>
        <td style="min-width:200px"><div class="stackbar" style="width:${Math.max(4, x.steps.reduce((s, t) => s + t.mean_ms, 0) / maxMs * 100)}%">${x.steps.filter(t => t.mean_ms > 0).map(t => `<span style="flex:${t.mean_ms};background:var(--series-${F_COLOR[t.key]})" title="${esc(title[t.key])}: ${t.mean_ms}ms"></span>`).join("")}</div>
          <div class="small muted mt-1">${x.steps.filter(t => t.mean_ms > 0).map(t => `${esc(title[t.key].split(" ").slice(1).join(" "))} ${fmtMs(t.mean_ms)}`).join(" · ")}</div></td></tr>`).join("")}
      ${r.results.filter(x => x.status !== "ok").map(x => `<tr><td class="small">${esc(x.label)}</td><td colspan="10"><div class="errbox">${esc(x.error)}</div></td></tr>`).join("")}
    </table></div>
    <div class="legend">${used.map(s => `<span>${swatch(s.key)}${esc(title[s.key])}</span>`).join("")}</div>
    ${ok.filter(x => x.rows?.length).map(x => `<details><summary class="small">질문별 기록 · ${esc(x.label)}</summary><div class="table-wrap scroll-md"><table>
      <tr><th>질문</th><th class="num">품질</th><th class="num">시간</th><th>에이전트 행동</th><th>번호 검사</th><th>답변</th></tr>
      ${x.rows.map(q => `<tr><td class="small">${esc(q.query)}</td><td class="num">${q.quality != null ? pct(q.quality) : "-"}</td><td class="num small">${fmtMs(q.ms)}</td>
        <td class="small">${esc((q.actions || []).join(" → ")) || "-"}</td><td class="small">${esc((q.citations || []).map(c => `${c[0]}:${c[1]}`).join(", ")) || "-"}</td><td class="small">${esc(q.answer)}</td></tr>`).join("")}
    </table></div></details>`).join("")}
    <div class="small muted">검색 지표 · 답변 지표는 % 단위. 막대 길이 = 질문당 평균 처리 시간(가장 느린 연결 = 100%), 칸 = 단계별 시간(마우스를 올리면 값). 기준 대비 = 첫 연결과 짝지은 차이(답변이 있으면 답변 품질, 없으면 nDCG), '불확실'은 우연일 수 있다는 뜻입니다.</div>`;
}

fLoad();

// 저장된 학습 라우터를 라우팅 선택지에 붙인다 (없으면 그대로)
api("/api/routing/learned").then(ls => ls.forEach(m => $("#f-route")?.insertAdjacentHTML("beforeend", `<option value="learned:${m.id}">학습 라우터 #${m.id}</option>`))).catch(() => {});
