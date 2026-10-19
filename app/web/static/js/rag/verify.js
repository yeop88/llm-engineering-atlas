// rag/verify.html 화면 스크립트 (템플릿에서 옮김 — 화면 JS 는 static/js/<영역>/<화면>.js)
// queue: 판정할 문장들. collection_id 는 문장을 만든 작업 결과에서 가져온다 — 화면의 선택값에 기대면 라벨이 컬렉션 없이 저장되던 문제가 있었다
let queue = [], queueCol = null;
setupCollectionPickers({ col: $("#v-col"), idx: $("#v-idx"), set: $("#v-set"), key: "verify-col" });
const MNAME = { lexical: "글자 겹침", semantic: "의미 유사도", hybrid: "글자 또는 의미", llm: "LLM 판정" };

(async () => {
  const s = await api("/api/verify/settings");
  $("#s-out").innerHTML = `근거 일치: <b>${esc(MNAME[s.method] || s.method)}</b> · 의미 검증 모델 <span class="mono">${esc(s.model)}</span> · 의미 문턱 ${s.semantic_ok} (약함 ${s.semantic_weak}) · 글자 문턱 ${s.lexical_ok}<br>
    질문 관련성: ${s.relevance ? `<b>켬</b> · 질문-문장 유사도 기준 ${s.relevance_ok}` : "꺼짐 (ANSWER_RELEVANCE)"}`;
  loadCount();
})();

$("#v-run").onclick = e => {
  if (!$("#v-set").value) return toast("평가 세트가 필요합니다", "err");
  runJobInto(e.target, "/api/verify/sample", { eval_set_id: +$("#v-set").value, config: { mode: "dense", index_id: +$("#v-idx").value }, n_questions: +$("#v-n").value || 10,
    llm_judge: $("#v-llm").checked }, $("#v-progress"), r => { queue = r.items; queueCol = r.collection_id; showQueue(); toast(`판정할 문장 ${r.items.length}개`, "ok"); });
};

const pick = (i, key, v, label) => `<button class="btn sm" data-q="${i}" data-k="${key}" data-v="${v}" onclick="mark(${i}, '${key}', ${v})">${label}</button>`;
function showQueue() {
  $("#l-out").innerHTML = queue.length ? queue.map((x, i) => `<div class="card stack" style="padding:10px" id="q${i}">
      <div class="small muted">질문: ${esc(x.question)}</div>
      <div><b>${esc(x.sentence)}</b></div>
      <details><summary class="small">인용한 근거 보기</summary><pre class="small" style="white-space:pre-wrap;max-height:260px;overflow:auto">${esc(x.sources)}</pre></details>
      <div class="row small"><span style="width:76px">근거 일치</span>${pick(i, "label", true, "근거 있음")}${pick(i, "label", false, "근거 없음")}${pick(i, "label", null, "모르겠음")}</div>
      <div class="row small"><span style="width:76px">질문 관련성</span>${pick(i, "relevant", true, "관련 있음")}${pick(i, "relevant", false, "관련 없음")}${pick(i, "relevant", null, "모르겠음")}</div></div>`).join("")
    + `<div class="row"><span class="spacer"></span><button class="btn primary" onclick="saveMarks()">판정 저장</button></div>` : '<div class="empty">1 에서 판정할 문장을 만드세요</div>';
}
function mark(i, key, v) {
  queue[i][key] = v;
  // 고른 버튼만 강조 — 두 판정을 따로 하므로 카드 테두리 하나로는 상태를 보일 수 없다
  $$(`#q${i} button[data-k="${key}"]`).forEach(b => { const on = String(v) === b.dataset.v; b.classList.toggle("primary", on && v !== false); b.classList.toggle("danger", on && v === false); });
}
async function saveMarks() {
  const items = queue.filter(x => typeof x.label === "boolean" || typeof x.relevant === "boolean")
    .map(({ question, sentence, sources, label, relevant, scores }) => ({ question, sentence, sources, label: label ?? null, relevant: relevant ?? null, scores }));
  if (!items.length) return toast("판정한 문장이 없습니다", "err");
  await api("/api/verify/labels", { method: "POST", body: { collection_id: queueCol, items } });
  toast(`${items.length}개 저장`, "ok"); queue = []; showQueue(); loadCount();
}
async function loadCount() {
  const c = (await api("/api/verify/labels?limit=1")).counts;
  $("#l-count").textContent = `저장된 라벨: 근거 있음 ${c.supported} · 없음 ${c.unsupported} / 질문 관련 ${c.relevant} · 관련 없음 ${c.off_topic}`;
}

$("#a-run").onclick = async e => {
  const r = await busy(e.target, () => api("/api/verify/agreement"));
  if (!r.n && !r.n_relevance) { $("#a-out").innerHTML = '<div class="empty">라벨이 없습니다</div>'; return; }
  const row = (name, x, extra = "") => `<tr><td><b>${name}</b>${extra}</td><td class="num">${x.kappa}</td><td class="num">${pct(x.accuracy)}</td>
      <td class="num">${pct(x.precision)}</td><td class="num">${pct(x.recall)}</td><td class="num">${pct(x.f1)}</td><td class="num small">${x.fn} / ${x.fp}</td><td class="small">${x.threshold ?? "-"}</td></tr>`;
  const head = '<tr><th>방식</th><th class="num">카파</th><th class="num">정확도</th><th class="num">정밀도</th><th class="num">재현율</th><th class="num">F1</th><th class="num">놓침 / 잘못 통과</th><th>문턱</th></tr>';
  const rows = ["lexical", "semantic", "hybrid", "llm"].filter(k => r[k]);
  const best = rows.reduce((a, k) => (!a || r[k].kappa > r[a].kappa ? k : a), null);
  $("#a-out").innerHTML = (r.n ? `<h3>근거 일치 · 라벨 ${r.n}개 (근거 있음 ${pct(r.positive_rate)}%)</h3>
    <div class="table-wrap"><table>${head}${rows.map(k => row(MNAME[k], r[k], k === best ? ' <span class="badge ok">가장 일치</span>' : "")).join("")}</table></div>
    ${best && best !== "llm" ? `<pre class="small">ANSWER_VERIFY_METHOD=${best}${r[best].threshold ? `\nVERIFY_SEMANTIC_OK=${r[best].threshold}` : ""}</pre>` : ""}` : '<div class="small muted">근거 일치 라벨이 없습니다</div>')
    + (r.relevance ? `<h3>질문 관련성 · 라벨 ${r.n_relevance}개 (관련 있음 ${pct(r.relevant_rate)}%) · AUC ${r.relevance_auc ?? "-"}</h3>
    <div class="table-wrap"><table>${head}${row("질문-문장 유사도 (지금 기준)", r.relevance_current)}${row("질문-문장 유사도 (가장 일치하는 기준)", r.relevance)}</table></div>
    <pre class="small">VERIFY_RELEVANCE_OK=${r.relevance.threshold}</pre>` : "")
    + `<div class="small muted">카파 = 우연히 맞을 확률을 뺀 일치도(0.6 이상이면 꽤 일치). '놓침' = 사람은 그렇다는데 자동은 아니라고 함, '잘못 통과' = 사람은 아니라는데 자동은 그렇다고 함. AUC = 기준값과 무관하게 점수가 두 판정을 얼마나 잘 가르는지(0.5 = 무작위). 문턱은 같은 라벨로 훑어 고른 값이라 낙관적입니다 — 라벨이 늘면 다시 재세요.</div>`;
};
