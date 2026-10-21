// flywheel/review.html 화면 스크립트 — 검토 순서(FW3), 판정 · 평가 / 학습 분배와 누수 검사(FW4)
const CAT = { retrieval: "검색 실패", citation: "인용 실패", off_topic: "상관없는 답", over_refusal: "과도한 거절", policy: "정책", format: "형식 오류", risky: "확신도 낮음" };
const TO = { eval: ["ok", "평가 세트로"], train: ["ok", "학습 데이터로"], ignore: ["", "버림"], blocked: ["err", "막힘"] };

async function stats() {
  const s = await api("/api/flywheel/reviews/stats");
  $("#v-stats").innerHTML = html`최근 30일 검토 ${s.n}건 · 틀림 ${s.wrong}${s.wrong_rate != null ? ` (${pct(s.wrong_rate)}%)` : ""} · ${html.join(Object.entries(s.routed).map(([k, v]) => html`<span class="badge ${(TO[k] || [""])[0]}">${(TO[k] || ["", k])[1]} ${v}</span>`), " ")} · 학습 데이터 ${s.train_rows}줄`;
}

async function load() {
  const q = new URLSearchParams({ n: $("#v-n").value || 20 });
  if ($("#v-col").value) q.set("collection_id", $("#v-col").value);
  const rows = await api(`/api/flywheel/queue?${q}`);
  $("#v-queue").innerHTML = rows.length ? html.join(rows.map(r => html`<div class="card stack mt-2" data-trace="${r.trace_id}">
    <div class="row"><b>#${r.trace_id}</b> <span class="badge">${r.kind}</span> ${html.join(r.why.map(w => html`<span class="badge warn">${w}</span>`), " ")}</div>
    <div><b>질문</b> ${r.question}</div><details><summary class="small">답 · 근거 일치 ${r.verify.supported_ratio ?? "-"}${r.verify.refused ? " · 거절" : ""}</summary><div class="pre small">${r.answer}</div></details>
    <div class="row">
      <div class="field"><label for="v-l-${r.trace_id}">판정</label><select id="v-l-${r.trace_id}" data-label><option value="wrong">틀림</option><option value="correct">맞음</option></select></div>
      <div class="field"><label for="v-c-${r.trace_id}">유형</label><select id="v-c-${r.trace_id}" data-cat><option value="">-</option>${html.join(Object.entries(CAT).map(([k, v]) => html`<option value="${k}" ${r.categories.includes(k) ? "selected" : ""}>${v}</option>`), "")}</select></div>
      <div class="field"><label for="v-d-${r.trace_id}">보낼 곳</label><select id="v-d-${r.trace_id}" data-dest><option value="eval">평가 세트</option><option value="train">학습 데이터</option><option value="ignore">버림</option></select></div>
    </div>
    <fieldset class="small"><legend>정답 문서 (평가 · 학습)</legend>${r.sources.length ? html.join(r.sources.map(s => html`<label class="row m-0"><input type="checkbox" data-doc="${s.document_id}"> ${s.filename}</label>`), "")
      : html`<span class="muted">근거 없음 — 평가로 보내려면 정답 문서가 필요합니다</span>`}</fieldset>
    <div class="field"><label for="v-x-${r.trace_id}">고친 답 (학습으로 보낼 때)</label><textarea id="v-x-${r.trace_id}" rows="2" data-fix></textarea></div>
    <div><button class="btn sm primary" data-save>저장 · 보내기</button> <span data-result></span></div></div>`), "")
    : html`<div class="small muted">검토할 요청이 없습니다.</div>`;
  $$("[data-save]", $("#v-queue")).forEach(b => b.onclick = () => {
    const card = b.closest("[data-trace]");
    const body = { trace_id: +card.dataset.trace, label: $("[data-label]", card).value, category: $("[data-cat]", card).value, destination: $("[data-dest]", card).value,
      gold_doc_ids: $$("[data-doc]", card).filter(x => x.checked).map(x => +x.dataset.doc), corrected: $("[data-fix]", card).value };
    busy(b, () => api("/api/flywheel/reviews", { method: "POST", body })).then(r => {
      const t = TO[r.routed.to] || ["", r.routed.to];
      $("[data-result]", card).innerHTML = html`<span class="badge ${t[0]}">${t[1]}</span> <span class="small">${r.routed.reason || (r.routed.eval_set_id ? `평가 세트 #${r.routed.eval_set_id} (${r.routed.n_items}문항)` : r.routed.n_rows ? `${r.routed.n_rows}줄` : "")}</span>`;
      $("#v-routed").insertAdjacentHTML("afterbegin", String(html`<div class="small">#${body.trace_id} → <span class="badge ${t[0]}">${t[1]}</span> ${r.routed.reason || ""}</div>`));
      stats();
    }).catch(e => toast(e.message, "err"));
  });
}

(async () => {
  const cols = await api("/api/collections");
  $("#v-col").innerHTML = html`<option value="">모두</option>${cols.map(c => html`<option value="${c.id}">${c.name}</option>`)}`;
  await Promise.all([stats(), load()]);
})().catch(e => ui.error($("#v-queue"), e));
$("#v-load").onclick = e => busy(e.target, load).catch(err => ui.error($("#v-queue"), err));
