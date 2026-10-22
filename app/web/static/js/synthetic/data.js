// synthetic/data.html 화면 스크립트 — 부족 분석(SD1 · SD2), 생성 · 거르기 · 검토(SD3~SD6), 학습 · 실제 평가(SD7 · SD8)
let TYPES = {};
const pct = v => (v == null ? "-" : `${Math.round(v * 100)}%`);
const llmRef = () => ({ provider: $("#b-provider").value || null, model: $("#b-model").value.trim() || null });
const base = () => ({ eval_set_id: +$("#g-set").value, split_seed: +$("#g-seed").value });

$("#g-run").onclick = e => busy(e.target, () => api("/api/synthetic/gap", { method: "POST", body: base() })).then(r => {
  $("#g-out").innerHTML = html`<div class="small muted">학습용 실제 ${r.train} · 시험용 실제 ${r.test}(생성 · 학습에 쓰지 않음)</div>
    <div class="table-wrap"><table><tr><th>유형</th><th>학습 수</th><th>교차 검증 재현율</th><th>부족</th><th>이유</th><th>전략</th></tr>
      ${html.join(r.gaps.map(g => html`<tr><td>${g.label}</td><td>${g.n}</td><td>${pct(g.recall)}</td><td>${g.short ? html`<span class="badge warn">예</span>` : "-"}</td>
        <td class="small">${g.why.join(" · ")}</td><td class="small">${g.strategy.join(" · ")}</td></tr>`), "")}</table></div>`;
}).catch(err => ui.error($("#g-out"), err));

function showBatch(m) {
  const rv = m.review || { items: {} };
  const ci = rv.error_ci ? ` · 오류율 95% 구간 ${pct(rv.error_ci[0])}~${pct(rv.error_ci[1])}` : "";
  $("#b-out").innerHTML = html`<div class="small">${m.name} · ${m.n}건 (만듦 ${m.generated} → 다양성 ${m.selected} → 거름 ${m.clean_report.out}) · 부족 유형 ${m.short.map(t => TYPES[t]).join(", ")}</div>
    <div class="small muted">뺀 것: 중복 ${m.clean_report.dup} · 평가 누수 ${m.clean_report.leak} · 개인정보 ${m.clean_report.pii} — 만든 방법 ${Object.entries(m.by_how).map(([k, v]) => `${k} ${v}`).join(" · ")}</div>
    <div class="small muted">다양성(거르기 전 → 후): 평균 쌍 유사도 ${m.diversity_raw.mean_sim} → ${m.diversity_clean.mean_sim} · 서로 다른 2-gram ${m.diversity_raw.distinct2} → ${m.diversity_clean.distinct2}</div>
    <h3>검토 표본 — ${m.review_status} (${rv.done || 0}/${Object.keys(rv.items).length}${ci})</h3>
    <div class="table-wrap"><table><tr><th>유형</th><th>질문</th><th>판정</th></tr>
      ${html.join(Object.entries(rv.items).map(([id, x]) => html`<tr><td>${TYPES[x.type]}</td><td class="small">${x.query}</td>
        <td class="nowrap-row"><button class="btn" data-rv="${id}" data-ok="1">쓸 만함</button> <button class="btn danger" data-rv="${id}" data-ok="0">아님</button>
        ${x.ok == null ? "" : html` <span class="badge ${x.ok ? "ok" : "err"}">${x.ok ? "쓸 만함" : "아님"}</span>`}</td></tr>`), "")}</table></div>`;
  $("#b-out").dataset.name = m.name;
}

$("#b-out").onclick = e => {
  const b = e.target.closest("[data-rv]");
  if (!b) return;
  const name = $("#b-out").dataset.name;
  api(`/api/synthetic/batches/${encodeURIComponent(name)}/review`, { method: "POST", body: { id: b.dataset.rv, ok: b.dataset.ok === "1" } })
    .then(() => api(`/api/synthetic/batches/${encodeURIComponent(name)}`)).then(showBatch).catch(err => ui.error($("#b-out"), err));
};

$("#b-run").onclick = e => runJobInto(e.target, "/api/synthetic/batches", { ...base(), name: $("#b-name").value.trim(), per_type: +$("#b-per").value,
  keep: +$("#b-keep").value, use_llm: $("#b-llm").checked, llm: llmRef() }, $("#b-progress"), m => { showBatch(m); refresh(); }).catch(err => ui.error($("#b-out"), err));

$("#b-load").onclick = e => busy(e.target, () => api(`/api/synthetic/batches/${encodeURIComponent($("#b-open").value)}`)).then(showBatch).catch(err => ui.error($("#b-out"), err));

$("#x-run").onclick = e => runJobInto(e.target, "/api/synthetic/experiment", { ...base(), seeds: +$("#x-seeds").value, use_llm: $("#x-llm").checked, llm: llmRef() }, $("#x-progress"), r => {
  const types = Object.keys(TYPES);
  $("#x-out").innerHTML = html`<div class="small muted">씨앗 ${r.seeds} · ${r.seconds}초 · run #${r.run_id}</div>
    <div class="table-wrap"><table><tr><th>학습 데이터</th><th>학습 수</th><th>실제 시험 정확(범위)</th><th>실제 유형 평균 재현</th><th>합성 시험 정확</th>${types.map(t => html`<th class="small">${TYPES[t]}</th>`)}</tr>
      ${html.join(r.summary.map(s => html`<tr><td>${s.condition}</td><td>${s.n_train}</td><td><b>${pct(s.real_acc)}</b> <span class="small muted">(${pct(s.real_min)}~${pct(s.real_max)})</span></td>
        <td>${pct(s.real_macro)}</td><td>${pct(s.synthetic_acc)}</td>${types.map(t => html`<td class="small">${pct(s.recall[t])}</td>`)}</tr>`), "")}</table></div>
    <h3>거른 합성 질문 예(첫 씨앗)</h3><ul class="small">${r.runs[0].examples.map(x => html`<li>[${TYPES[x.type]} · ${x.how}] ${x.query}</li>`)}</ul>`;
}).catch(err => ui.error($("#x-out"), err));

function refresh() {
  return api("/api/synthetic/sources").then(s => {
    TYPES = s.types;
    $("#g-set").innerHTML = html`${s.eval_sets.map(x => html`<option value="${x.id}">#${x.id} ${x.name} · ${x.n}문항</option>`)}`;
    $("#b-open").innerHTML = s.batches.length ? html`${s.batches.map(b => html`<option>${b.name}</option>`)}` : html`<option value="">(없음)</option>`;
  });
}
refresh().catch(err => ui.error($("#g-out"), err));
