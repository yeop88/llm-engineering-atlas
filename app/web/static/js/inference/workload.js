// inference/workload.html 화면 스크립트 — 요청 기록 분포(IF1), 미리 채우기 · 생성 분리 탐침(IF2)
const pct = v => (v == null ? "-" : `${Math.round(v * 100)}%`);
const distRow = (name, d) => html`<tr><td>${name}</td><td>${d.n}</td><td>${d.mean ?? "-"}</td><td>${d.p50 ?? "-"}</td><td><b>${d.p95 ?? "-"}</b></td><td>${d.p99 ?? "-"}</td><td>${d.max ?? "-"}</td></tr>`;

$("#w-run").onclick = e => busy(e.target, () => api(`/api/inference/workload?days=${+$("#w-days").value || 30}`)).then(r => {
  if (!r.n) { ui.empty($("#w-out"), "이 기간에 요청 기록이 없습니다."); return; }
  $("#w-out").innerHTML = html`<div class="small muted">요청 ${r.n}개 · ${Object.entries(r.kinds).map(([k, v]) => `${k} ${v}`).join(" · ")} · LLM 몫 ${pct(r.llm_share)} · 동시 최대 ${r.concurrency.peak} (바쁠 때 평균 ${r.concurrency.mean_when_busy})</div>
    <div class="table-wrap"><table><tr><th>항목</th><th>수</th><th>평균</th><th>p50</th><th>p95</th><th>p99</th><th>최대</th></tr>
      ${distRow("프롬프트 토큰", r.tokens_in)}${distRow("답 토큰", r.tokens_out)}${distRow("전체 ms", r.total_ms)}
      ${html.join(Object.entries(r.steps).map(([k, d]) => distRow(`단계 ${k} ms`, d)), "")}</table></div>`;
}).catch(err => ui.error($("#w-out"), err));

const nums = s => s.split(",").map(x => +x.trim()).filter(n => n > 0);
$("#p-run").onclick = e => runJobInto(e.target, "/api/inference/probe", { provider: $("#p-provider").value || null, model: $("#p-model").value.trim() || null,
  prompt_tokens: nums($("#p-plen").value), out_tokens: nums($("#p-olen").value), days: +$("#w-days").value || 30 }, $("#p-progress"), r => {
  const s = r.split;
  $("#p-out").innerHTML = html`<div class="table-wrap"><table><tr><th>프롬프트(실제)</th><th>답</th><th>미리 채우기 토큰/초</th><th>생성 토큰/초</th><th>미리 채우기 ms</th><th>생성 ms</th></tr>
    ${html.join(r.probes.map(p => html`<tr><td>${p.prompt_tokens ?? p.prompt_target}</td><td>${p.out_tokens ?? p.out_target}</td><td>${p.prompt_tps ?? "-"}</td><td>${p.gen_tps ?? "-"}</td>
      <td>${p.prompt_ms ? Math.round(p.prompt_ms) : "-"}</td><td>${p.gen_ms ? Math.round(p.gen_ms) : "-"}</td></tr>`), "")}</table></div>
    ${s.available ? html`<div class="table-wrap"><table><tr><th>워크로드 요청</th><th>프롬프트 · 답 토큰</th><th>미리 채우기 ms</th><th>생성 ms</th><th>미리 채우기 몫</th></tr>
      ${html.join(["p50", "p95"].map(q => html`<tr><td>${q}</td><td>${s[q].tokens_in} · ${s[q].tokens_out}</td><td>${s[q].prefill_ms}</td><td>${s[q].decode_ms}</td><td><b>${pct(s[q].prefill_share)}</b></td></tr>`), "")}</table></div>
      <div class="small">병목 <span class="badge warn">${s.bottleneck === "prefill" ? "미리 채우기(프롬프트 읽기)" : "생성(토큰 만들기)"}</span> → 먼저: ${s.advice.join(" · ")}</div>`
      : html`<div class="small muted">요청 기록이나 서버 단계 시간(timings)이 없어 워크로드와 곱하지 못했습니다.</div>`}
    <div class="small muted">${r.model} · run #${r.run_id}</div>`;
}).catch(err => ui.error($("#p-out"), err));
