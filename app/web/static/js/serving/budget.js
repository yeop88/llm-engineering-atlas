// serving/budget.html 화면 스크립트 — 예산 안 최고 품질 · 파레토 앞줄 · 운영 준수(S7), 캐시 · 모델 · 장치 · 메모리 현황(S1 · S2 · S3 · S6)
const ms = c => Math.round(c.p95_ms || c.latency_ms || 0);

async function run() {
  const body = { max_ms: +$("#u-ms").value || null, max_cost: +$("#u-cost").value || null, min_quality: +$("#u-q").value || null };
  const r = await api("/api/serving/budget", { method: "POST", body });
  $("#u-out").innerHTML = r.sets.length ? html.join(r.sets.map(s => html`<div class="card stack mt-2"><div class="row"><b>${s.eval_set}</b> <span class="small muted">후보 ${s.n}</span>
      ${s.within ? html`<span class="badge ok">목표 안</span>` : html`<span class="badge warn">목표 안 후보 없음 — 가장 가까운 것</span>`}</div>
      <div class="small">고른 것: <b>${s.best.label}</b> · 품질 ${s.best.quality} · ${s.best.p95_ms ? "p95" : "평균"} ${ms(s.best)}ms${s.best.cost != null ? ` · $${s.best.cost}` : ""} <span class="muted">(${s.best.source})</span>
        ${s.best.over?.length ? html` <span class="badge err">${s.best.over.join(" · ")}</span>` : ""}</div>
      <details class="small"><summary>파레토 앞줄 ${s.front.length}</summary><ul>${html.join(s.front.map(c => html`<li>${c.label} — 품질 ${c.quality} · ${ms(c)}ms ${c.over.length ? html`<span class="muted">(${c.over.join(", ")})</span>` : ""}</li>`), "")}</ul></details></div>`), "")
    : html`<div class="small muted">후보가 될 실측 기록이 없습니다 — 연결 비교 · LLM 양자화 · 라우팅 평가를 먼저 돌리세요.</div>`;
  $("#u-live").innerHTML = r.live.length ? html`<div class="table-wrap"><table><tr><th>경로</th><th>모델</th><th>요청</th><th>p95</th><th>평균</th><th>질문당 비용</th><th>지연 목표 넘음</th></tr>
    ${html.join(r.live.map(x => html`<tr><td class="small mono">${x.route}</td><td class="small">${x.model}</td><td>${x.n}</td><td>${x.p95_ms}ms</td><td>${x.mean_ms}ms</td><td>$${x.cost_per_q}</td>
      <td>${x.over_latency == null ? "-" : html`<span class="badge ${x.over_latency > 0.05 ? "warn" : "ok"}">${pct(x.over_latency)}%</span>`}</td></tr>`), "")}</table></div>` : html`<div class="small muted">최근 요청 기록이 없습니다.</div>`;
}

async function res() {
  const r = await api("/api/serving/resources");
  const d = r.device;
  $("#u-res").innerHTML = html`<div class="grid cols-2">
    <div class="small"><b>캐시 (S1)</b><div>AS 의미 캐시 ${r.cache.answer_cache.entries}개 · 다시 쓴 횟수 ${r.cache.answer_cache.hits}</div><div>검색 향상 변형 캐시 ${r.cache.enhance_cache.entries}/${r.cache.enhance_cache.size}</div></div>
    <div class="small"><b>장치 (S6)</b><div>${d.error || html`빌드 ${d.build} · 쓰는 장치 <b>${d.resolved}</b> · 설정 ${d.setting}/${d.dtype}`}</div>
      <div>메모리 ${r.memory.total_gb}GB 중 ${r.memory.used_pct}% · 앱 ${fmtNum(r.memory.process_mb)}MB</div></div>
    <div class="small"><b>올라간 임베딩 · 리랭커 (S3 · S6)</b> 상한 ${r.models.max_loaded}<ul>${html.join(r.models.loaded.map(m => html`<li>${m.hf_id} <span class="muted">${m.device}/${m.dtype} · 로드 ${m.load_seconds}초</span></li>`), "")}</ul></div>
    <div class="small"><b>LLM (S3 · S4)</b><div>기본 ${r.llm.model || "-"} · 소형 ${r.llm.small || "없음"} · 대체 ${r.llm.fallbacks}개</div>
      ${Object.keys(r.llm.urls || {}).length ? html`<div class="mono">${JSON.stringify(r.llm.urls)}</div>` : ""}<div>GGUF ${r.gguf.length}개 · llama-server ${r.llama_server ? "있음" : "없음"}</div></div></div>`;
}

$("#u-run").onclick = e => busy(e.target, run).catch(err => ui.error($("#u-out"), err));
run().catch(e => ui.error($("#u-out"), e));
res().catch(e => ui.error($("#u-res"), e));
