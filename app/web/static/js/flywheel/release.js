// flywheel/release.html 화면 스크립트 — 버전 만들기 · 게이트(FW6), 단계적 배포 · 감시 · 단계 올리기 · 롤백(FW7)
const VS = { candidate: ["", "후보"], passed: ["ok", "게이트 통과"], failed: ["err", "게이트 실패"], rolling: ["warn", "배포 중"], live: ["ok", "현재"], rolled_back: ["err", "되돌림"], retired: ["", "물러남"] };
const vb = s => html`<span class="badge ${(VS[s] || [""])[0]}">${(VS[s] || ["", s])[1]}</span>`;

function gateHtml(g) {
  if (!g?.items) return "";
  return html`<details class="small"><summary>게이트 ${g.ok ? "통과" : "실패"} · ${g.items.length}항목${g.mode ? ` · 방어 ${g.mode}` : ""}</summary>${html.join(g.items.map(i => html`<div>${i.ok ? html`<span class="badge ok">통과</span>` : html`<span class="badge err">미달</span>`} ${i.key} — ${i.detail}</div>`), "")}</details>`;
}

async function load() {
  const rows = await api(`/api/flywheel/versions?collection_id=${$("#r-col").value}`);
  $("#r-versions").innerHTML = rows.length ? html`<div class="table-wrap"><table><tr><th>#</th><th>버전</th><th>상태</th><th>배포</th><th>게이트</th><th></th></tr>
    ${html.join(rows.map(v => html`<tr data-v="${v.id}"><td class="small">${v.id}</td><td class="small"><b>${v.name}</b><div class="muted mono">${v.config.search?.mode || ""} ${v.config.guard_mode ? `· ${v.config.guard_mode}` : ""}</div></td>
      <td>${vb(v.status)}</td><td class="small">${v.status === "rolling" ? `${v.rollout.pct}%` : ""}</td><td>${gateHtml(v.gate)}</td>
      <td class="small nowrap">${["candidate", "failed", "passed"].includes(v.status) ? html`<button class="btn sm" data-gate>게이트</button>` : ""}
        ${v.status === "passed" ? html`<button class="btn sm primary" data-start>배포 시작</button>` : ""}
        ${v.status === "rolling" ? html`<button class="btn sm" data-mon>감시</button> <button class="btn sm primary" data-step>단계 올리기</button>` : ""}
        ${["rolling", "live"].includes(v.status) ? html`<button class="btn sm danger" data-rb>롤백</button>` : ""}</td></tr>`), "")}</table></div>` : html`<div class="small muted">버전이 없습니다.</div>`;
  const rowOf = b => +b.closest("[data-v]").dataset.v;
  $$("[data-gate]", $("#r-versions")).forEach(b => b.onclick = () => runJobInto(b, `/api/flywheel/versions/${rowOf(b)}/gate`, { redteam: $("#r-rt").checked, provider: Ctx.get().provider || null, model: Ctx.get().model || null },
    $("#r-progress"), () => load()).catch(e => toast(e.message, "err")));
  $$("[data-start]", $("#r-versions")).forEach(b => b.onclick = () => busy(b, () => api(`/api/flywheel/versions/${rowOf(b)}/start`, { method: "POST" })).then(load).catch(e => toast(e.message, "err")));
  $$("[data-step]", $("#r-versions")).forEach(b => b.onclick = () => busy(b, () => api(`/api/flywheel/versions/${rowOf(b)}/step`, { method: "POST" }))
    .then(r => { toast(r.health.decision === "wait" ? `더 모으기: ${r.health.why}` : r.health.decision === "rollback" ? `롤백: ${r.health.why}` : `${r.pct}% 로`); load(); monitor(r.version); }).catch(e => toast(e.message, "err")));
  $$("[data-mon]", $("#r-versions")).forEach(b => b.onclick = () => monitor(rowOf(b)).catch(e => ui.error($("#r-monitor"), e)));
  $$("[data-rb]", $("#r-versions")).forEach(b => b.onclick = async () => {
    if (!(await ui.confirm("이 버전을 되돌립니다. 요청은 바로 이전 설정(현재 버전 · 기본 설정)으로 갑니다.", { ok: "롤백", danger: true }))) return;
    busy(b, () => api(`/api/flywheel/versions/${rowOf(b)}/rollback`, { method: "POST" })).then(load).catch(e => toast(e.message, "err"));
  });
}

async function monitor(id) {
  const m = await api(`/api/flywheel/versions/${id}/monitor`);
  const row = (k, a) => html`<tr><td>${k}</td><td>${a.n}</td><td>${a.supported ?? "-"}</td><td>${a.refused ?? "-"}</td><td>${a.dislike ?? "-"} (${a.n_feedback})</td><td>${a.fail_rate ?? "-"}</td></tr>`;
  $("#r-monitor").innerHTML = html`<div class="small">버전 #${m.version} · ${vb(m.status)} ${m.pct}% · 판단 <b>${{ wait: "더 모으기", advance: "다음 단계 가능", rollback: "되돌려야 함" }[m.health.decision]}</b> — ${m.health.why}</div>
    <div class="table-wrap"><table><tr><th>팔</th><th>요청</th><th>근거 일치</th><th>거절률</th><th>싫어요(피드백)</th><th>실패 분류율</th></tr>${row("후보", m.metrics.candidate)}${row("나머지(현재)", m.metrics.base)}</table></div>`;
}

$("#r-create").onclick = e => {
  let search = null;
  try { search = $("#r-search").value.trim() ? JSON.parse($("#r-search").value) : null; } catch { return toast("검색 설정은 JSON 이어야 합니다", "err"); }
  if (!$("#r-name").value.trim()) return toast("버전 이름을 적으세요", "err");
  busy(e.target, () => api("/api/flywheel/versions", { method: "POST", body: { name: $("#r-name").value.trim(), collection_id: +$("#r-col").value, search, guard_mode: $("#r-guard").value || null } }))
    .then(() => { toast("버전을 만들었습니다 — 게이트를 돌리세요"); load(); }).catch(err => toast(err.message, "err"));
};

setupCollectionPickers({ col: $("#r-col"), onDetail: () => load().catch(e => ui.error($("#r-versions"), e)) }).catch(e => ui.error($("#r-versions"), e));
