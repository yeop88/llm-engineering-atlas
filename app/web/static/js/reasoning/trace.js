// reasoning/trace.html 화면 스크립트 — 생각 과정 검사(RS5) · 풀이 보기, 추론 증류 데이터(RS6)
const pct = v => (v == null ? "-" : `${(v * 100).toFixed(1)}%`);
let BANKS = [];
const bank = () => BANKS.find(b => b.key === $("#t-bank").value);

$("#t-run").onclick = e => busy(e.target, () => api("/api/reasoning/trace", { method: "POST", body: { tasks: bank().tasks, bank: bank().key } })).then(r => {
  $("#t-out").innerHTML = html`<div class="small muted">풀이 ${r.n} · 생각이 있는 풀이 ${r.with_thinking} · run #${r.run_id}</div>
    ${r.with_thinking ? html`<div class="table-wrap"><table><tr><th>표시</th><th>풀이</th><th>비율</th><th>표시된 풀이 정답률</th><th>나머지 정답률</th></tr>
    ${html.join(Object.entries(r.flags).map(([f, d]) => html`<tr><td>${f}</td><td>${d.n}</td><td>${pct(d.rate)}</td><td>${pct(d.acc_flagged)}</td><td>${pct(d.acc_clean)}</td></tr>`), "")}</table></div>
    ${r.examples.length ? html`<ul class="small">${html.join(r.examples.slice(0, 10).map(x => html`<li><span class="mono">${x.task_id}#${x.i}</span> ${x.correct ? "맞음" : "틀림"} · ${x.flags.join(", ")}
      ${x.unsupported ? ` · 근거 밖 ${[...x.unsupported.articles, ...x.unsupported.numbers].join(", ")}` : ""}${x.conclusion ? ` · 생각의 결론 ${x.conclusion}` : ""}</li>`), "")}</ul>` : ""}`
    : html`<p class="small muted">이 저장소에는 생각 글이 없습니다(예산 0 · 생각을 돌려주지 않는 모델).</p>`}`;
}).catch(err => ui.error($("#t-out"), err));

$("#t-show").onclick = e => {
  const q = new URLSearchParams({ limit: "20" });
  if ($("#t-task").value.trim()) q.set("task_id", $("#t-task").value.trim());
  busy(e.target, () => api(`/api/reasoning/banks/${bank().key}?${q}`)).then(r => {
    $("#t-rows").innerHTML = html.join(r.rows.map(s => html`<div class="card p-2 stack"><div class="row small"><span class="mono">${s.task_id}#${s.i}</span> <span class="badge ${s.correct ? "ok" : "err"}">${s.correct ? "맞음" : "틀림"}</span>
      <span class="muted">생각 ${s.think_tokens} · 출력 ${s.out_tokens} 토큰 · ${s.seconds}초${s.forced ? " · 예산 강제" : ""}</span></div>
      ${s.thinking ? html`<details><summary class="small">생각 (${s.thinking.length}자)</summary><div class="pre small">${s.thinking}</div></details>` : ""}<div class="pre small">${s.text}</div></div>`), "");
  }).catch(err => ui.error($("#t-rows"), err));
};

$("#d-run").onclick = e => busy(e.target, () => api("/api/reasoning/distill", { method: "POST", body: { tasks: bank().tasks, bank: bank().key, name: $("#d-name").value.trim(),
  include_thinking: $("#d-think").checked, clean_only: $("#d-clean").checked } })).then(m => {
  const r = m.report;
  $("#d-out").innerHTML = html`<div class="small"><b>${m.name}</b> · ${m.n}행 · 목표 글 평균 ${r.mean_target_chars}자 · 유형 ${Object.entries(r.by_type).map(([k, v]) => `${k} ${v}`).join(", ")}
    · 건너뜀(맞은 풀이 없음 ${r.skipped.no_correct} · 검사 표시 ${r.skipped.flagged})</div><div class="small"><a href="${m.next}">후학습 화면에서 이 데이터로 학습 →</a></div>`;
}).catch(err => ui.error($("#d-out"), err));

(async () => {
  BANKS = (await api("/api/reasoning/overview")).banks;
  $("#t-bank").innerHTML = html`${BANKS.map(b => html`<option value="${b.key}">${b.tasks} · ${b.model} · 예산 ${b.budget || "끔"} · 온도 ${b.temperature} · ${b.n_rows}풀이 (정답률 ${pct(b.acc)})</option>`)}`;
  if (!BANKS.length) ui.empty($("#t-out"), "풀이 저장소가 없습니다 — 생각 예산 · 여러 번 풀기 화면에서 먼저 푸세요.");
})().catch(e => ui.error($("#t-out"), e));
