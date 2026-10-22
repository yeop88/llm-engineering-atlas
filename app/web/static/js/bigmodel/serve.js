// bigmodel/serve.html 화면 스크립트 — 페이지 KV 캐시 비교(BM4), 연속 배칭 흉내 · 서버 실측(BM5)
const MODE = { reserve: "최대 길이 미리 잡기", paged: "페이지", paged_share: "페이지 + 앞부분 공유", static: "고정 묶음", continuous: "연속 배칭" };
const pct = v => (v == null ? "-" : `${Math.round(v * 100)}%`);

$("#k-run").onclick = e => busy(e.target, () => api("/api/bigmodel/paged", { method: "POST", body: { source: $("#k-src").value, n: +$("#k-n").value,
  prefix_tokens: +$("#k-prefix").value, prefixes: +$("#k-prefixes").value, prompt_mean: +$("#k-prompt").value, out_mean: +$("#k-out").value,
  budget_gb: +$("#k-budget").value, kv_bytes_per_token: +$("#k-tok").value, block_size: +$("#k-block").value, max_len: +$("#k-max").value } })).then(r => {
  $("#k-out").innerHTML = html`<div class="small muted">요청 ${r.requests}개 · KV ${r.budget_gb} GB = 블록 ${r.blocks}개(블록당 ${r.block_size}토큰)</div>
    <div class="table-wrap"><table><tr><th>방식</th><th>평균 동시</th><th>최대 동시</th><th>잡은 칸 중 찬 비율</th><th>물리 칸당 토큰</th><th>공유로 아낀 블록(평균)</th><th>다 끝낸 걸음</th></tr>
    ${html.join(r.results.map(x => html`<tr><td>${MODE[x.mode]}</td><td><b>${x.mean_concurrency}</b></td><td>${x.max_concurrency}</td><td>${pct(x.token_fill)}</td><td>${x.tokens_per_slot}</td>
      <td>${x.shared_blocks_saved}</td><td>${x.steps}</td></tr>`), "")}</table></div>`;
}).catch(err => ui.error($("#k-out"), err));

$("#b-run").onclick = e => busy(e.target, () => api("/api/bigmodel/batching/sim", { method: "POST", body: { n: +$("#b-n").value, rate: +$("#b-rate").value,
  out_mean: +$("#b-out").value, out_spread: +$("#b-spread").value, slots: +$("#b-slots").value, base_ms: +$("#b-base").value, per_seq_ms: +$("#b-seq").value,
  prefill_ms_per_tok: +$("#b-pre").value, max_wait_s: +$("#b-wait").value } })).then(r => {
  $("#b-out").innerHTML = html`<div class="table-wrap"><table><tr><th>방식</th><th>토큰/초</th><th>지연 평균(초)</th><th>지연 p95</th><th>첫 토큰 평균</th><th>첫 토큰 p95</th><th>자리 쓰임</th><th>걸린 시간(초)</th></tr>
    ${html.join([r.static, r.continuous].map(x => html`<tr><td>${MODE[x.mode]}</td><td><b>${x.tok_s}</b></td><td>${x.mean_latency_s}</td><td>${x.p95_latency_s}</td><td>${x.mean_ttft_s}</td>
      <td>${x.p95_ttft_s}</td><td>${pct(x.slot_use)}</td><td>${x.seconds}</td></tr>`), "")}</table></div>
    <div class="small muted">처리할 수 있는 양보다 많이 오면(도착이 빠르면) 두 방식 모두 줄이 길어집니다 — 지연은 대기를 포함합니다.</div>`;
}).catch(err => ui.error($("#b-out"), err));

$("#s-run").onclick = e => runJobInto(e.target, "/api/bigmodel/batching/server", { gguf: $("#s-gguf").value, slots: $("#s-slots").value.split(",").map(s => +s.trim()).filter(n => n > 0),
  ctx_per_slot: +$("#s-ctx").value }, $("#s-progress"), r => {
  $("#s-out").innerHTML = html`<div class="small muted">${r.gguf} · ${r.seconds}초 · run #${r.run_id}</div>
    <div class="table-wrap"><table><tr><th>슬롯</th><th>연속 배칭</th><th>토큰/초</th><th>요청/초</th><th>p50 ms</th><th>p95 ms</th><th>KV MiB</th><th>상태</th></tr>
    ${html.join(r.rows.map(x => html`<tr><td>${x.slots}</td><td>${x.cont_batching ? "켬" : "끔"}</td><td><b>${x.tokens_per_s ?? "-"}</b></td><td>${x.req_per_s ?? "-"}</td><td>${x.p50_ms ?? "-"}</td>
      <td>${x.p95_ms ?? "-"}</td><td>${x.kv_cache_mib ?? "-"}</td><td>${x.status === "ok" ? html`<span class="badge ok">ok</span>` : html`<span class="badge err small">${x.error}</span>`}</td></tr>`), "")}</table></div>`;
}).catch(err => ui.error($("#s-out"), err));

api("/api/bigmodel/machine").then(m => {
  $("#s-gguf").innerHTML = m.gguf.length ? html`${m.gguf.map(f => html`<option value="${f.name}">${f.name} · ${f.gb} GB</option>`)}` : html`<option value="">GGUF 없음(LLM_MODELS_DIR)</option>`;
  $("#s-run").disabled = !m.llama_server || !m.gguf.length;
}).catch(err => ui.error($("#s-out"), err));
