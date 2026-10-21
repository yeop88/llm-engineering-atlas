// 평가 · 관측 E6: 기준 기간(또는 평가 세트) 대비 최근 질문의 새로움 · 검색 확신도 · 거절률 변화
const num = (v, d = 3) => (v == null ? "-" : Number(v).toFixed(d));
const ratio = v => (v == null ? "-" : `${Math.round(v * 1000) / 10}%`);
function sig(d, rate = false) {
  if (!d) return "-";
  const f = rate ? x => `${x >= 0 ? "+" : ""}${(x * 100).toFixed(1)}%p` : x => `${x >= 0 ? "+" : ""}${num(x, 4)}`;
  return html`<span class="mono">${f(d.diff)}</span> <span class="small muted">[${f(d.ci?.[0] ?? 0)}, ${f(d.ci?.[1] ?? 0)}]</span> ${d.significant ? html`<span class="badge warn">유의</span>` : html`<span class="badge muted">불확실</span>`}`;
}

// 컬렉션: '전체'가 있어 작업 맥락에는 쓰지 않고 시작 값으로만 읽는다(전체를 고르면 다른 화면의 컬렉션이 지워지지 않게)
async function loadCols() {
  const cols = await api("/api/collections");
  $("#d-col").innerHTML = html`<option value="">전체 컬렉션</option>${cols.map(c => html`<option value="${c.id}">${c.name}</option>`)}`;
  const want = Ctx.get().col;
  if (want && cols.some(c => String(c.id) === want)) $("#d-col").value = want;
  await loadSets();
}
async function loadSets() {
  const cid = $("#d-col").value;
  const sets = cid ? await api(`/api/evalops/sets?collection_id=${cid}`) : [];
  $("#d-set").innerHTML = html`<option value="">쓰지 않음 (기준 기간의 요청)</option>${sets.map(s => html`<option value="${s.id}">#${s.id} ${s.name} (${s.n_items}문항)</option>`)}`;
  $("#d-set").disabled = !cid;
}
$("#d-col").addEventListener("change", loadSets);

$("#d-run").onclick = e => {
  const body = {
    collection_id: +$("#d-col").value || null, recent_days: +$("#d-recent").value || 7, base_days: +$("#d-base").value || 30,
    eval_set_id: +$("#d-set").value || null, novel_sim: +$("#d-sim").value || 0.6,
    recent_questions: $("#d-questions").value.split("\n").map(s => s.trim()).filter(Boolean),
  };
  return runJobInto(e.target, "/api/evalops/drift", body, $("#d-progress"), render).catch(() => {});
};

function render(r) {
  const rows = [
    ["새로운 질문 비율", ratio(r.novel.base_rate), ratio(r.novel.recent_rate), sig(r.novel, true), "가장 가까운 기준 질문과의 유사도가 기준값 미만인 질문의 비율. 기준 쪽은 자기 자신을 뺀 가장 가까운 질문으로 잼"],
    r.top1 && ["검색 1위 점수", num(r.top1.base_mean), num(r.top1.recent_mean), sig(r.top1), "자료가 낡거나 질문 모양이 바뀌면 떨어짐"],
    r.gap && ["검색 확신도 (1 · 2위 차)", num(r.gap.base_mean), num(r.gap.recent_mean), sig(r.gap), "작아지면 검색이 헷갈린다는 뜻"],
    r.refusal && ["거절률", ratio(r.refusal.base_rate), ratio(r.refusal.recent_rate), sig(r.refusal, true), "'근거에서 찾을 수 없습니다'가 늘면 자료에 없는 질문이 늘었다는 뜻"],
  ].filter(Boolean);
  $("#d-out").innerHTML = html`${r.alerts.length ? html.join(r.alerts.map(a => html`<div class="warnbox" role="alert">${a}</div>`)) : html`<div class="small"><span class="badge ok">경보 없음</span> 기준 대비 유의하게 나빠진 신호가 없습니다.</div>`}
    <div class="small muted">기준 ${fmtNum(r.n_base)}개 · 최근 ${fmtNum(r.n_recent)}개 · 새로운 질문 기준 유사도 ${r.novel_sim} · 질문 중심 이동 ${num(r.centroid_shift, 4)} (1 − 두 기간 평균 벡터의 코사인)
      · 가장 가까운 기준 질문과의 평균 유사도 ${num(r.nearest_sim.base_mean)} → ${num(r.nearest_sim.recent_mean)}${r.run_id ? html` · run #${r.run_id}` : ""}</div>
    <div class="table-wrap"><table><tr><th>신호</th><th class="num">기준</th><th class="num">최근</th><th>차이 (최근 − 기준, 95% 구간)</th><th>뜻</th></tr>
      ${rows.map(([k, a, b, d, why]) => html`<tr><td>${k}</td><td class="num">${a}</td><td class="num">${b}</td><td>${d}</td><td class="small muted">${why}</td></tr>`)}</table></div>
    ${!r.top1 ? html`<div class="small muted">검색 신호 · 거절률은 기준과 최근이 모두 요청 기록일 때만 비교합니다(평가 세트 · 직접 넣은 질문에는 신호가 없음).</div>` : ""}
    <h3>새로운 질문 묶음 <span class="small muted">서로 비슷한 것끼리 — 평가 세트가 따라가야 할 유형</span></h3>
    ${r.novel_groups.length ? html`<div class="table-wrap scroll-md"><table><tr><th>대표 질문</th><th class="num">수</th><th>예시</th><th></th></tr>
      ${r.novel_groups.map((g, i) => html`<tr><td class="small"><b>${g.representative}</b></td><td class="num">${g.n}</td><td class="small">${html.join(g.examples, "<br>")}</td>
        <td><button class="btn sm" data-send="${i}">평가 세트로</button></td></tr>`)}</table></div>
      <div class="row"><button class="btn" id="d-send-all">새 질문 모두 평가 세트로</button>
        <span class="small muted">위에서 고른 컬렉션의 '피드백 · 실패 후보' 세트에 정답 문서 없이(검토 전) 넣습니다 — 평가 세트 화면에서 정답을 붙여 통과시키면 기준이 됩니다.</span></div>` : html`<div class="small muted">새로운 질문이 없습니다.</div>`}
    <div class="small muted">${r.stat_note}</div>`;
  $$("[data-send]").forEach(b => { b.onclick = () => sendQuestions(b, r.novel_groups[+b.dataset.send].examples); });
  if ($("#d-send-all")) $("#d-send-all").onclick = e => sendQuestions(e.target, r.novel_groups.flatMap(g => g.examples));
}

async function sendQuestions(btn, questions) {
  const cid = +$("#d-col").value;
  if (!cid) return toast("보낼 컬렉션을 위에서 고르세요", "err");
  const r = await busy(btn, () => api("/api/evalops/questions/to-eval-set", { method: "POST", body: { collection_id: cid, questions, source: "drift" } }));
  toast(`${r.name} 에 ${r.added}개 추가${r.skipped ? ` (이미 있는 ${r.skipped}개 제외)` : ""}`);
  btn.disabled = true;
}

loadCols().catch(e => ui.error($("#d-out"), e));
