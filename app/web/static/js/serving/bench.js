// serving/bench.html 화면 스크립트 — 동시 부하(S4), KV 캐시 · 추측 디코딩 설정별 비교(S5)
function renderLoad(r) {
  $("#b-load-out").innerHTML = html`<div class="small muted">${r.llm.model} · ${r.llm.base_url}${r.run_id ? ` · run #${r.run_id}` : ""}</div>
    <div class="table-wrap"><table><tr><th>동시</th><th>요청</th><th>오류</th><th>요청/초</th><th>출력 토큰/초</th><th>p50</th><th>p95</th></tr>
    ${html.join(r.rows.map(x => html`<tr><td>${x.concurrency}</td><td>${x.requests}</td><td>${x.errors}</td><td>${x.req_per_s}</td><td>${x.tokens_per_s}</td><td>${x.p50_ms}ms</td><td>${x.p95_ms}ms</td></tr>`), "")}</table></div>`;
}

function renderDecode(r) {
  $("#b-decode-out").innerHTML = html`<div class="small muted">${r.model} · ${r.eval_set.name} · 질문 ${r.n_queries} · 문맥 ${r.ctx} · ${r.seconds}초${r.run_id ? ` · run #${r.run_id}` : ""}</div>
    <div class="table-wrap"><table><tr><th>설정</th><th>품질</th><th>기준 대비</th><th>생성 토큰/초</th><th>빨라짐</th><th>질문당</th><th>KV 캐시</th><th>RSS</th><th>초안 수락</th></tr>
    ${html.join(r.results.map(x => x.status !== "ok" ? html`<tr><td class="small"><b>${x.label}</b></td><td colspan="8"><span class="badge err">실패</span> <span class="small">${x.error}</span></td></tr>`
      : html`<tr><td class="small"><b>${x.label}</b><div class="muted mono">${x.kv_k}/${x.kv_v}${x.draft ? ` · 초안 ${x.draft}` : ""}</div></td>
        <td>${x.quality}${x.quality_ci ? html`<div class="small muted">[${x.quality_ci.join(", ")}]</div>` : ""}</td>
        <td class="small">${x.vs_first ? html`${x.vs_first.diff > 0 ? "+" : ""}${x.vs_first.diff} ${x.vs_first.significant ? html`<span class="badge ${x.vs_first.diff < 0 ? "err" : "ok"}">유의</span>` : html`<span class="badge">불확실</span>`}` : "기준"}</td>
        <td>${x.generation_per_second ?? x.tokens_per_second ?? "-"}</td><td>${x.speedup ? `×${x.speedup}` : ""}</td><td class="small">${x.mean_seconds}초</td>
        <td class="small">${x.kv_cache_mib != null ? `${x.kv_cache_mib} MiB` : "-"}</td><td class="small">${x.rss_mib != null ? `${x.rss_mib} MiB` : "-"}</td><td class="small">${x.draft_acceptance ?? ""}</td></tr>`), "")}</table></div>
    <details class="small"><summary>실행한 명령</summary><ul>${html.join(r.results.filter(x => x.command).map(x => html`<li class="mono">${x.command}</li>`), "")}</ul></details>`;
}

$("#b-load").onclick = e => runJobInto(e.target, "/api/serving/load", { levels: $("#b-levels").value.split(",").map(s => +s.trim()).filter(Boolean), max_tokens: +$("#b-tokens").value || 96,
  provider: Ctx.get().provider || null, model: Ctx.get().model || null }, $("#b-load-progress"), renderLoad).catch(err => toast(err.message, "err"));
$("#b-decode").onclick = e => {
  let variants;
  try { variants = JSON.parse($("#b-variants").value); } catch { return toast("설정은 JSON 목록이어야 합니다", "err"); }
  runJobInto(e.target, "/api/serving/decode", { model: $("#b-model").value, variants, eval_set_id: +$("#b-set").value, max_queries: +$("#b-n").value || 12 },
    $("#b-decode-progress"), renderDecode).catch(err => toast(err.message, "err"));
};

(async () => {
  const r = await api("/api/serving/resources");
  $("#b-model").innerHTML = html`${r.gguf.filter(n => !/^(mmproj|mtp)/i.test(n) && !/mmproj/i.test(n)).map(n => html`<option>${n}</option>`)}`;
  $("#b-env").innerHTML = r.llama_server ? html`<span class="badge ok">llama-server 있음</span> — 설정마다 빈 포트(18100~)에 띄우고 끝나면 끕니다. 초안 모델은 같은 계열(어휘가 같아야)이어야 합니다.`
    : html`<span class="badge warn">LLAMA_SERVER_BIN 이 없습니다</span> — .env 에 llama-server 실행 파일 경로와 LLM_MODELS_DIR 를 넣으세요.`;
  await setupCollectionPickers({ col: $("#b-col"), set: $("#b-set") });
})().catch(e => ui.error($("#b-env"), e));
