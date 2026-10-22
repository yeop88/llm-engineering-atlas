// realtime/stream.html 화면 스크립트 — 스트림 재생(RT1~RT8), 조건 훑기, LLM 첫 토큰 실측(RT6)
let PRE = null;
const pct = v => (v == null ? "-" : `${Math.round(v * 100)}%`);
const ms = d => (d ? html`${d.p50} · ${d.p95} · <b>${d.p99}</b>` : "-");
const nums = s => s.split(",").map(x => +x.trim()).filter(x => x >= 0 && !Number.isNaN(x));

function params() {
  return { chunk_ms: +$("#p-chunk").value, buffer_ms: +$("#p-buf").value, agree: +$("#p-agree").value, endpoint_ms: +$("#p-end").value,
    ttft_ms: +$("#p-ttft").value, ttft_sigma: +$("#p-sigma").value, tok_ms: +$("#p-tok").value, first_sentence_tokens: +$("#p-fst").value,
    tts_ms: +$("#p-tts").value, early_retrieval: $("#p-early").checked, net: PRE.networks[$("#p-net").value] };
}

$("#p-run").onclick = e => busy(e.target, () => api("/api/realtime/run", { method: "POST", body: { params: params(), seeds: +$("#p-seeds").value } })).then(r => {
  const L = r.labels;
  $("#p-out").innerHTML = html`<div class="small muted">${r.n_turns}턴 · ${r.seconds}초 · run #${r.run_id} — 값은 p50 · p95 · p99 (ms)</div>
    <div class="grid cols-2"><div><b>말 끝 → 첫 소리</b> ${ms(r.first_sound)} <span class="small">(1.2초 넘은 몫 ${pct(r.over_budget_1200)})</span></div>
      <div><b>말 끝 → 첫 토큰</b> ${ms(r.first_token)}</div></div>
    <div class="table-wrap"><table><tr><th>단계</th><th>p50</th><th>p95</th><th>p99</th></tr>
      ${html.join(Object.entries(r.stages).map(([k, d]) => html`<tr><td>${L[k]}</td><td>${d.p50}</td><td>${d.p95}</td><td>${d.p99}</td></tr>`), "")}</table></div>
    <ul class="small"><li>확정 오류 턴당 ${r.commit_errors} 낱말 · 깜빡임 ${r.flicker} · 상태(제품 · 코드) 정확 ${pct(r.state_ok)} · 손실 조각 ${r.lost_chunks} · 못 들은 낱말 ${r.dropped_words}</li>
      <li>검색 미리 시작으로 줄인 시간 ${ms(r.early_saved)}</li>
      <li>끼어들기 → 소리 멈춤: 서버 취소 ${ms(r.barge.server)} · 기기에서 멈춤 ${ms(r.barge.client)}</li></ul>
    <div class="table-wrap"><table><tr><th>끊김 복구 전략</th><th>복구율(잃은 낱말 0)</th><th>잃은 몫</th><th>다시 보낸 낱말</th><th>순번 없이 겹칠 낱말</th></tr>
      ${html.join(Object.entries(r.recover).map(([k, v]) => html`<tr><td>${k}</td><td><b>${pct(v.recovery_rate)}</b></td><td>${pct(v.lost_share)}</td><td>${v.resent_words}</td><td>${v.dup_if_no_seq}</td></tr>`), "")}</table></div>`;
}).catch(err => ui.error($("#p-out"), err));

$("#w-run").onclick = e => runJobInto(e.target, "/api/realtime/sweep", { params: params(), chunk_ms: nums($("#w-chunk").value), buffer_ms: nums($("#w-buf").value) }, $("#w-progress"), r => {
  $("#w-out").innerHTML = html`<div class="small muted">${r.seconds}초 · run #${r.run_id} — 첫 소리 p50 · p95 · p99 (ms)</div>
    <div class="table-wrap"><table><tr><th>망</th><th>조각</th><th>버퍼</th><th>첫 소리</th><th>1.2초 초과</th><th>확정 오류</th><th>상태 정확</th><th>못 들은 낱말</th><th>끼어들기 멈춤 p95</th></tr>
      ${html.join(r.rows.map(x => html`<tr><td>${x.network}</td><td>${x.chunk_ms}</td><td>${x.buffer_ms}</td><td>${ms(x.first_sound)}</td><td>${pct(x.over_budget_1200)}</td>
        <td>${x.commit_errors}</td><td>${pct(x.state_ok)}</td><td>${x.dropped_words}</td><td>${x.barge_stop_p95}</td></tr>`), "")}</table></div>`;
}).catch(err => ui.error($("#w-out"), err));

$("#l-run").onclick = e => runJobInto(e.target, "/api/realtime/live", { llm: { provider: $("#l-provider").value || null, model: $("#l-model").value.trim() || null }, n: +$("#l-n").value }, $("#l-progress"), r => {
  if (r.ttft_ms) $("#p-ttft").value = r.ttft_ms;
  $("#p-sigma").value = r.ttft_sigma;
  if (r.tok_ms) $("#p-tok").value = r.tok_ms;
  if (r.first_sentence_tokens) $("#p-fst").value = r.first_sentence_tokens;
  $("#l-out").innerHTML = html`<div class="small">${r.model} · 첫 토큰 중앙 <b>${r.ttft_ms}ms</b> · 퍼짐 ${r.ttft_sigma} · 토큰 간격 ${r.tok_ms}ms · 첫 문장 ${r.first_sentence_ms}ms(≈${r.first_sentence_tokens} 토큰) · run #${r.run_id} — 위 설정에 넣었습니다</div>
    <div class="table-wrap"><table><tr><th>질문</th><th>첫 토큰 ms</th><th>첫 문장 ms</th><th>토큰 간격</th><th>토큰</th></tr>
      ${html.join(r.rows.map(x => html`<tr><td class="small">${x.question}</td><td>${x.ttft_ms}</td><td>${x.first_sentence_ms}</td><td>${x.tok_ms ?? "-"}</td><td>${x.tokens ?? "-"}</td></tr>`), "")}</table></div>`;
}).catch(err => ui.error($("#l-out"), err));

api("/api/realtime/preset").then(p => {
  PRE = p;
  $("#p-net").innerHTML = html`${Object.keys(p.networks).map(k => html`<option>${k}</option>`)}`;
  $("#p-net").value = Object.keys(p.networks)[1];
}).catch(err => ui.error($("#p-out"), err));
