// platform/ops.html 화면 스크립트 — 배포 상태(PF5), 구성 요소 · 차단기 · 대체 사슬(PF6), 테넌트 · 기능별 비용 · 예산(PF7)
const ok = b => (b ? html`<span class="badge ok">정상</span>` : html`<span class="badge err">멈춤</span>`);

async function loadOps() {
  const o = await api("/api/platform/ops");
  const same = o.migration && o.migrations_in_repo && o.migration === o.migrations_in_repo;
  $("#o-deploy").innerHTML = html`앱 <b>v${o.version}</b> · 화면 · API 경로 ${o.routes}개 · 마이그레이션 <span class="mono">${o.migration || "-"}</span>
    ${same ? html`<span class="badge ok">최신</span>` : html`<span class="badge warn">저장소 ${o.migrations_in_repo}</span>`} · 방어 모드 ${o.guard_mode}`;
  const brk = Object.entries(o.breakers);
  $("#o-res").innerHTML = html`<div class="table-wrap"><table><tr><th>구성 요소</th><th>상태</th><th>설명</th></tr>
    ${html.join(Object.entries(o.vector_stores).map(([k, v]) => html`<tr><td class="small">벡터 DB ${k}</td><td>${ok(v.ok)}</td><td class="small muted">${v.detail || v.mode || ""}</td></tr>`), "")}
    ${html.join(o.graph_engines.map(g => html`<tr><td class="small">그래프 ${g.label}</td><td>${ok(g.ok)}</td><td class="small muted">${g.url || ""} ${g.detail || ""}</td></tr>`), "")}
    ${html.join(o.llm_chain.map((c, i) => html`<tr><td class="small">LLM ${i ? `대체 ${i}` : "기본"}</td><td>${c.error ? html`<span class="badge err">설정 없음</span>` : (o.breakers[c.key]?.open ? html`<span class="badge err">차단기 열림</span>` : html`<span class="badge">닫힘</span>`)}</td>
      <td class="small mono">${c.error || `${c.model} · ${c.base_url}`}</td></tr>`), "")}</table></div>
    ${brk.length ? html`<details class="small"><summary>차단기 ${brk.length}</summary><ul>${html.join(brk.map(([k, v]) => html`<li class="mono">${k} — 실패 ${v.fails}${v.open ? " · 열림" : ""}${v.last_error ? ` · ${v.last_error}` : ""}</li>`), "")}</ul></details>` : ""}
    ${o.llm_chain.length < 2 ? html`<div class="small muted">대체 모델이 없습니다 — .env 의 LLM_FALLBACKS 에 [{"provider": "openai", "model": "…", "base_url": "…"}]</div>` : ""}`;
}

async function loadCharge() {
  const c = await api("/api/platform/chargeback");
  $("#o-charge").innerHTML = html`<div class="small muted">${c.since.slice(0, 10)} 부터(이번 달)</div>
    <div class="table-wrap"><table><tr><th>테넌트</th><th>요청</th><th>토큰</th><th>비용($)</th><th>예산</th></tr>
    ${html.join(c.tenants.map(t => html`<tr><td class="small"><b>${t.tenant}</b></td><td class="small">${fmtNum(t.requests)}</td><td class="small">${fmtNum(t.tokens)}</td><td class="small">${t.cost.toFixed(4)}</td>
      <td class="small">${t.budget ? html`${t.used_pct}% / $${t.budget} ${t.over_alert ? html`<span class="badge err">경보 ${t.alert_pct}%</span>` : ""}` : html`<span class="muted">없음</span>`}</td></tr>`), "")}</table></div>
    <details class="small"><summary>기능별</summary><div class="table-wrap"><table><tr><th>테넌트</th><th>기능</th><th>요청</th><th>토큰</th><th>비용($)</th><th>평균 지연</th></tr>
    ${html.join(c.rows.map(r => html`<tr><td>${r.tenant}</td><td class="mono">${r.kind}</td><td>${fmtNum(r.requests)}</td><td>${fmtNum(r.tokens)}</td><td>${r.cost.toFixed(4)}</td><td>${r.requests ? Math.round(r.ms / r.requests) : 0}ms</td></tr>`), "")}</table></div></details>`;
}

$("#o-check").onclick = e => busy(e.target, () => api("/api/platform/ops/llm-check", { method: "POST" }))
  .then(r => { $("#o-check-out").innerHTML = html`<ul class="small">${html.join(r.chain.map(c => html`<li>${c.ok ? html`<span class="badge ok">응답</span>` : html`<span class="badge err">실패</span>`} ${c.model} · ${c.ms}ms ${c.error || c.text || ""}</li>`), "")}</ul>`; loadOps(); })
  .catch(err => ui.error($("#o-check-out"), err));
$("#o-budget").onclick = e => busy(e.target, () => api("/api/platform/budgets", { method: "POST", body: { tenant: $("#o-tenant").value.trim() || "공용", monthly_usd: +$("#o-usd").value || 0, alert_pct: +$("#o-pct").value || 80 } }))
  .then(() => { toast("예산을 저장했습니다"); loadCharge(); }).catch(err => toast(err.message, "err"));
loadOps().catch(e => ui.error($("#o-deploy"), e));
loadCharge().catch(e => ui.error($("#o-charge"), e));
