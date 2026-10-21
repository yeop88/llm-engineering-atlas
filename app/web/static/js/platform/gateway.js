// platform/gateway.html 화면 스크립트 — 사용량 · 속도 제한(PF1), 컬렉션 테넌트 지정 · 누출 시험(PF2)
async function usage() {
  const u = await api("/api/platform/gateway");
  $("#g-usage").innerHTML = html`<div class="small">분당 상한 ${u.limit_per_min ? html`<b>${u.limit_per_min}</b>회` : html`<span class="badge warn">끔(RATE_LIMIT_PER_MIN=0)</span>`}
      · 인증 ${u.auth ? "켜짐" : html`<span class="badge">꺼짐 — 모두 로컬 사용자</span>`} · 개별 상한 ${Object.keys(u.overrides).length ? JSON.stringify(u.overrides) : "없음"}
      · 거절 ${Object.values(u.denied).reduce((a, b) => a + b, 0)}회 · 서버 시작 ${new Date(u.since * 1000).toLocaleString()}</div>
    <div class="table-wrap scroll-md"><table><tr><th>테넌트</th><th>사용자</th><th>경로 묶음</th><th>요청</th></tr>
    ${html.join(u.rows.map(r => html`<tr><td class="small">${r.tenant}</td><td class="small">${r.user}</td><td class="small mono">${r.route}</td><td class="small">${fmtNum(r.n)}</td></tr>`), "")}</table></div>`;
}

async function tenants() {
  const t = await api("/api/platform/tenants");
  $("#g-users").innerHTML = t.users.length ? html`API_USERS: ${html.join(t.users.map(u => html`<span class="badge">${u.name} ${u.tenants.length ? `→ ${u.tenants.join(", ")}` : "(테넌트 없음)"}</span>`), " ")}`
    : html`<span class="muted">API_USERS 가 없어 모두 로컬(전체 권한)입니다 — 테넌트 격리를 시험하려면 groups 에 '${t.prefix}이름'을 넣은 사용자를 만드세요.</span>`;
  $("#g-tenants").innerHTML = html`<div class="table-wrap"><table><tr><th>컬렉션</th><th>테넌트 (비우면 공용)</th><th></th></tr>
    ${html.join(t.collections.map(c => html`<tr data-cid="${c.collection_id}"><td class="small">${c.name}</td>
      <td><input data-tenant value="${c.tenant || ""}" class="w-md" aria-label="${c.name} 테넌트" placeholder="공용"></td><td><button class="btn sm" data-save>저장</button></td></tr>`), "")}</table></div>`;
  $$("[data-save]", $("#g-tenants")).forEach(b => b.onclick = () => {
    const tr = b.closest("tr");
    busy(b, () => api("/api/platform/tenants", { method: "POST", body: { collection_id: +tr.dataset.cid, tenant: $("[data-tenant]", tr).value.trim() || null } }))
      .then(() => toast("저장했습니다")).catch(e => toast(e.message, "err"));
  });
}

$("#g-leak").onclick = e => busy(e.target, () => api("/api/platform/tenants/leak-test", { method: "POST", body: { queries: $("#g-q").value.split(",").map(s => s.trim()).filter(Boolean) } }))
  .then(r => {
    $("#g-leak-out").innerHTML = r.checks ? html`<div class="small">${r.leaks ? html`<span class="badge err">누출 ${r.leaks}</span>` : html`<span class="badge ok">누출 없음</span>`} · 시험 ${r.checks}개(테넌트 ${r.tenants.join(", ")})</div>
      <div class="table-wrap"><table><tr><th>이 테넌트로</th><th>남의 컬렉션</th><th>주인</th><th>결과 수</th></tr>${html.join(r.rows.map(x => html`<tr><td class="small">${x.as}</td><td class="small">#${x.collection_id}</td><td class="small">${x.owner}</td>
        <td>${x.leak ? html`<span class="badge err">${x.results}</span>` : html`<span class="badge ok">0</span>`}</td></tr>`), "")}</table></div>`
      : html`<div class="small muted">테넌트를 둘 이상 지정해야 시험할 수 있습니다.</div>`;
  }).catch(err => ui.error($("#g-leak-out"), err));

usage().catch(e => ui.error($("#g-usage"), e));
tenants().catch(e => ui.error($("#g-tenants"), e));
