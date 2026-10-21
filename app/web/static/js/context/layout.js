// context/layout.html 화면 스크립트 — 근거 배치 · 바늘 위치(CX1), 긴 맥락 vs RAG(CX2), 프롬프트 캐시(CX4)
const pct = v => (v == null ? "-" : `${(v * 100).toFixed(1)}%`);
const nums = s => s.split(",").map(x => +x.trim()).filter(n => !Number.isNaN(n));
const base = () => ({ eval_set_id: +$("#l-set").value, max_queries: +$("#l-n").value || 20, provider: $("#l-provider").value || null, model: $("#l-model").value.trim() || null });
const head = r => html`<div class="small muted">${r.eval_set} · ${r.model} · 질문 ${r.n ?? "-"} · ${r.seconds}초 · run #${r.run_id}</div>`;
const row = (name, d, extra = "") => html`<tr><td>${name}</td><td>${d.n}</td><td><b>${pct(d.quality)}</b></td><td>${d.prompt_tokens ?? "-"}</td><td>${d.seconds ?? "-"}</td>${extra}</tr>`;

$("#o-run").onclick = e => runJobInto(e.target, "/api/context/layout", { ...base(), top_k: +$("#o-k").value || 6, needle_k: +$("#o-k").value || 6, positions: nums($("#o-pos").value),
  needle: $("#o-needle").checked }, $("#o-progress"), r => {
  $("#o-out").innerHTML = html`${head(r)}<div class="table-wrap"><table><tr><th>배치</th><th>질문</th><th>정답률</th><th>입력 토큰</th><th>시간(초)</th></tr>
    ${html.join(Object.values(r.orders).map(d => row(d.label, d)), "")}</table></div>
    ${r.needle ? html`<h3>정답 근거 위치 (근거 ${r.needle.k}개 중, 쓸 수 있는 질문 ${r.needle.n_usable})</h3><div class="table-wrap"><table><tr><th>위치</th><th>질문</th><th>정답률</th><th>입력 토큰</th><th>시간(초)</th></tr>
    ${html.join(Object.entries(r.needle.positions).map(([p, d]) => row(`${p}번째`, d)), "")}</table></div>` : ""}`;
}).catch(err => ui.error($("#o-out"), err));

$("#g-run").onclick = e => runJobInto(e.target, "/api/context/long", { ...base(), limits: nums($("#g-limits").value) }, $("#g-progress"), r => {
  const rs = r.results;
  $("#g-out").innerHTML = html`${head(r)}<div class="table-wrap"><table><tr><th>맥락</th><th>질문</th><th>정답률</th><th>입력 토큰</th><th>시간(초)</th><th>정답 문서 들어감</th></tr>
    ${row(`RAG 검색 근거 (${rs.rag.chars}자 한도)`, rs.rag, html`<td>-</td>`)}
    ${html.join(Object.entries(rs).filter(([k]) => k.startsWith("full_")).map(([, d]) => row(`통째로 ${d.chars / 1000}K자`, d, html`<td>${pct(d.gold_inside)}</td>`)), "")}</table></div>`;
}).catch(err => ui.error($("#g-out"), err));

$("#c-run").onclick = e => runJobInto(e.target, "/api/context/cache", { ...base(), groups: +$("#c-groups").value || 4, per_group: +$("#c-per").value || 3 }, $("#c-progress"), r => {
  const ls = ["prefix_first", "question_first"].filter(k => r[k]);
  $("#c-out").innerHTML = html`<div class="small muted">${r.eval_set} · ${r.model} · ${r.seconds}초 · run #${r.run_id}</div>
    <div class="table-wrap"><table><tr><th>배치</th><th>호출</th><th>두 번째부터 재사용</th><th>첫 질문 읽기(ms)</th><th>다음 질문 읽기(ms)</th><th>평균 시간(초)</th></tr>
    ${html.join(ls.map(k => html`<tr><td>${r[k].label}</td><td>${r[k].calls}${r[k].errors ? ` (오류 ${r[k].errors})` : ""}</td><td><b>${pct(r[k].reuse)}</b></td><td>${r[k].cold_prompt_ms ?? "-"}</td><td>${r[k].warm_prompt_ms ?? "-"}</td><td>${r[k].seconds ?? "-"}</td></tr>`), "")}</table></div>
    <p class="small muted">${r.note}</p>`;
}).catch(err => ui.error($("#c-out"), err));

setupCollectionPickers({ col: $("#l-col"), set: $("#l-set") }).catch(e => ui.error($("#o-out"), e));
