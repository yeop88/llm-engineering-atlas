// rl/rl.html 화면 스크립트 (템플릿에서 옮김 — 화면 JS 는 static/js/<영역>/<화면>.js)
let colId = null, sampleRes = null;
setupCollectionPickers({ col: $("#c-col"), idx: $("#c-idx"), set: $("#c-set"), onDetail: d => (colId = d.id) });
const cfg = () => ({ mode: "dense", index_id: +$("#c-idx").value });
const model = () => $("#c-model").value.trim() || null;
const PART = { support: "근거 있는 문장", evidence_cited: "정답 근거 인용", invalid_citation: "없는 근거 인용", false_refusal: "근거 있는데 거절", honest_refusal: "정직한 거절", too_long: "너무 김", hallucination: "답 없는데 지어냄" };

(async () => {
  const w = await api("/api/rl/reward-weights");
  $("#w-out").innerHTML = `<div>보상 = ${Object.entries(w.weights).map(([k, v]) => `<span class="badge ${v < 0 ? "err" : "ok"}">${esc(PART[k] || k)} ${v > 0 ? "+" : ""}${v}</span>`).join(" ")}</div>
    <div class="muted mt-2">근거 있는 문장 = 문장 근거율(0~1) × 가중치. 정답 근거 인용 · 거절 판정은 평가 세트처럼 정답 근거 문장을 알 때만. ${w.max_chars}자를 넘으면 '너무 김'. 설명 가능한 단순 합으로 둔 이유: 학습된 보상 모델은 판단 근거를 알기 어렵고, 점수만 올리는 답(보상 해킹)을 찾기도 어렵습니다.</div>`;
  loadPairs();
})();

$("#h-run").onclick = async e => {
  const q = $("#h-q").value.trim();
  if (!q) return toast("질문을 입력하세요", "err");
  sampleRes = await busy(e.target, () => api("/api/rl/sample", { method: "POST", body: { question: q, collection_id: colId, config: cfg(), n: 2, model: model() } }));
  const c = sampleRes.candidates;
  $("#h-out").innerHTML = `<div class="grid cols-2">${c.map((x, i) => `<div class="card stack"><div class="row between"><b>답 ${i + 1}</b><span class="small muted">온도 ${x.temperature} · 보상 ${x.reward}</span></div>
      <div class="small pre">${esc(x.text)}</div><div class="small muted">${Object.entries(x.parts).map(([k, v]) => `${esc(PART[k] || k)} ${v}`).join(" · ") || "-"}</div>
      <button class="btn" onclick="choose(${i})">이 답이 더 좋다</button></div>`).join("")}</div>`;
};
async function choose(i) {
  const c = sampleRes.candidates, j = 1 - i;
  await api("/api/rl/preferences", { method: "POST", body: { collection_id: colId, question: sampleRes.question, context: sampleRes.context, chosen: c[i].text, rejected: c[j].text,
    chosen_reward: c[i].reward, rejected_reward: c[j].reward, meta: { model: sampleRes.llm.model, agrees_with_reward: c[i].reward >= c[j].reward } } });
  toast(c[i].reward >= c[j].reward ? "저장했습니다 (보상과 같은 판단)" : "저장했습니다 — 보상과 다른 판단입니다. 보상 기준을 다시 볼 만합니다", "ok");
  $("#h-out").innerHTML = ""; loadPairs();
}

$("#e-run").onclick = e => {
  if (!$("#c-set").value) return toast("평가 세트가 필요합니다", "err");
  const body = { eval_set_id: +$("#c-set").value, config: cfg(), n: +$("#e-n").value || 4, temperature: parseFloat($("#e-t").value) || 0.9,
    margin: parseFloat($("#e-m").value) || 0.3, collect: $("#e-collect").checked, max_queries: +$("#e-q").value || null, model: model() };
  runJobInto(e.target, "/api/rl/evaluate", body, $("#e-progress"), r => {
    $("#e-out").innerHTML = `<div class="table-wrap"><table><tr><th></th><th class="num">품질</th><th class="num">평균 보상</th><th class="num">질문당 시간</th></tr>
      <tr><td>평소 답 (온도 0.1)</td><td class="num">${pct(r.greedy.quality)}</td><td class="num">${r.greedy.reward}</td><td class="num">${r.greedy.seconds}s</td></tr>
      <tr><td><b>Best-of-${r.n}</b> (보상 최고)</td><td class="num">${pct(r.best_of_n.quality)} <span class="small">${vsBadge(r.quality_paired)}</span></td><td class="num">${r.best_of_n.reward} <span class="small">${vsBadge(r.reward_paired).replace("%p", "")}</span></td><td class="num">${r.best_of_n.seconds}s</td></tr></table></div>
      <div class="small muted">질문 ${r.n_queries}개 중 ${r.changed}개에서 평소 답이 아닌 후보가 뽑혔고, 선호 쌍 ${r.pairs_saved}개를 저장했습니다. 품질 = 정답 근거 인용(근거 문장이 없으면 문장 근거율). 보상 비교 칸의 값은 %p 가 아니라 보상 단위 차이입니다.${r.run_id ? ` · run #${r.run_id}` : ""}</div>`;
    loadPairs();
  });
};

async function loadPairs() {
  const r = await api("/api/rl/preferences?limit=50");
  $("#p-out").innerHTML = `<div class="small muted">자동 ${r.counts.auto || 0}개 · 사람 ${r.counts.human || 0}개</div>` + (r.items.length ? `<div class="table-wrap scroll-md"><table><tr><th>질문</th><th>좋은 답</th><th>나쁜 답</th><th class="num">보상</th><th></th></tr>
    ${r.items.map(p => `<tr><td class="small">${esc(p.question)} <span class="badge">${p.source === "human" ? "사람" : "자동"}</span></td><td class="small">${esc(p.chosen.slice(0, 140))}</td><td class="small muted">${esc(p.rejected.slice(0, 140))}</td>
      <td class="num small">${p.chosen_reward ?? "-"} / ${p.rejected_reward ?? "-"}</td><td><button class="btn sm danger" onclick="delPair(${p.id})">삭제</button></td></tr>`).join("")}</table></div>` : '<div class="empty">아직 없습니다</div>');
}
async function delPair(id) { await api(`/api/rl/preferences/${id}`, { method: "DELETE" }); loadPairs(); }
