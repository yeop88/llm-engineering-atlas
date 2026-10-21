// G3 · G5 · G6 권한 · 감사 · 라이선스: 문서 ACL 보기 · 누출 시험, 감사 로그 조회 · 무결성 · 내보내기 · 정리, 자료 · 모델 라이선스 점검
const groupsOf = s => s.split(",").map(x => x.trim()).filter(Boolean);
const aclBadges = g => (g.length ? html.join(g.map(x => html`<span class="badge warn">🔒 ${x}</span>`), " ") : html`<span class="badge muted">모두</span>`);

// ── 문서 권한 ──
async function loadAcl() {
  const cid = $("#a-col").value;
  if (!cid) return ui.empty($("#a-acl"), "컬렉션이 없습니다", { href: "/rag/collections", label: "컬렉션 만들기" });
  ui.loading($("#a-acl"));
  try {
    const r = await api(`/api/guardrails/acl/collections/${cid}`);
    const locked = r.documents.filter(d => d.acl.length).length;
    $("#a-acl").innerHTML = html`<div class="small">${locked ? html`권한이 붙은 문서 <b>${locked}</b> / ${r.documents.length}개 · 그룹: ${html.join(r.groups.map(g => html`<span class="badge">${g}</span>`), " ")}`
        : html`<span class="muted">권한이 붙은 문서가 없습니다 — 모든 문서를 모두가 봅니다. 문서 meta.acl 에 그룹 목록을 넣으면 그 그룹만 검색 후보에 들어갑니다.</span>`}</div>
      ${r.documents.length ? html`<div class="table-wrap scroll-sm"><table><tr><th>문서</th><th>볼 수 있는 그룹</th></tr>
        ${r.documents.map(d => html`<tr><td class="small">${d.filename} <span class="muted">#${d.document_id}</span></td><td>${aclBadges(d.acl)}</td></tr>`)}</table></div>` : ""}`;
  } catch (e) { ui.error($("#a-acl"), e); }
}
function aMode() { const b = $("#a-mode").value === "bm25"; $("#a-idx-wrap").hidden = b; $("#a-cs-wrap").hidden = !b; }
$("#a-mode").addEventListener("change", aMode);

function searchConfig() {
  const bm25 = $("#a-mode").value === "bm25";
  return { mode: $("#a-mode").value, index_id: bm25 ? null : +$("#a-idx").value || null, chunk_set_id: bm25 ? +$("#a-cs").value || null : null, top_k: 10 };
}

$("#l-run").onclick = async e => {
  const groups = groupsOf($("#l-groups").value);
  if (!groups.length) return toast("시험할 그룹을 넣으세요", "err");
  const queries = $("#l-queries").value.split("\n").map(x => x.trim()).filter(Boolean);
  const body = { config: searchConfig(), groups, queries, eval_set_id: +$("#l-set").value || null, max_queries: +$("#l-n").value || 30 };
  const r = await busy(e.target, () => api("/api/guardrails/acl/leak-test", { method: "POST", body }));
  $("#l-out").innerHTML = html`<div class="row">
      ${r.ok ? html`<span class="badge ok">✓ 누출 없음</span>` : html`<span class="badge err">⛔ 누출 ${r.leaks}건</span>`}
      <span class="small">질문 ${r.n}개 · 그룹 ${html.join(r.groups.map(g => html`<span class="badge">${g}</span>`), " ")} · 이 그룹이 볼 수 없는 문서 ${r.restricted_docs}개 ·
        거르지 않았다면 섞였을 질문 <b>${r.would_leak}</b>개</span></div>
    ${r.restricted_docs ? "" : html`<div class="warnbox">이 그룹이 볼 수 없는 문서가 없어 시험 의미가 없습니다 — 다른 그룹으로 시험하세요.</div>`}
    <div class="table-wrap scroll-md"><table><tr><th>질문</th><th class="num">권한 없이 섞인 수</th><th class="num">이 그룹으로 섞인 수</th><th class="num">결과 수</th></tr>
      ${r.rows.map(x => html`<tr><td class="small">${x.query}</td><td class="num">${x.restricted_without_acl}</td>
        <td class="num">${x.restricted_with_acl ? html`<span class="badge err">⛔ ${x.restricted_with_acl}</span>` : "0"}</td><td class="num">${x.n_results}</td></tr>`)}</table></div>`;
};

// ── 감사 로그 ──
let auditRows = [];
function auditParams() {
  const q = new URLSearchParams();
  if ($("#g-user").value) q.set("user", $("#g-user").value);
  const days = +$("#g-days").value;
  if (days > 0) q.set("date_from", new Date(Date.now() - days * 86400000).toISOString().slice(0, 10));
  return q;
}
function updateCsv() { $("#g-csv").href = `/api/guardrails/audit/export.csv?${auditParams()}`; }
["#g-user", "#g-days"].forEach(s => $(s).addEventListener("change", updateCsv));

const ST = { ok: ["ok", "ok"], blocked: ["⛔ 차단", "err"], error: ["오류", "err"] };
function renderAudit() {
  const kind = $("#g-kind").value;
  const rows = kind ? auditRows.filter(t => t.kind === kind) : auditRows;
  if (!rows.length) return ui.empty($("#g-out"), "조건에 맞는 기록이 없습니다");
  const act = t => (t.guard?.output?.action || t.guard?.action || "");
  $("#g-out").innerHTML = html`<div class="small muted">${rows.length}행 (최근 순)</div>
    <div class="table-wrap scroll-lg"><table><tr><th>#</th><th>시각</th><th>사용자</th><th>종류</th><th>질문</th><th>답변</th><th>근거 문서</th><th>상태</th><th>정책</th></tr>
    ${rows.map(t => html`<tr><td class="num small">${t.id}</td><td class="small nowrap">${fmtDate(t.created_at)}</td><td class="small">${t.user}</td><td class="small">${t.kind}</td>
      <td class="small">${t.question}</td><td class="small muted">${t.answer}</td>
      <td class="small">${html.join((t.source_files || []).map(f => html`<div>${f}</div>`), "")}${t.n_sources > (t.source_files || []).length ? html`<span class="muted">외 ${t.n_sources - t.source_files.length}개</span>` : ""}</td>
      <td><span class="badge ${(ST[t.status] || ["", "muted"])[1]}">${(ST[t.status] || [t.status])[0]}</span></td>
      <td class="small">${act(t) ? html`<span class="badge ${act(t) === "block" ? "err" : act(t) === "fix" ? "warn" : "muted"}">${act(t)}</span>` : ""}
        ${t.guard?.input?.suspicious ? html`<span class="badge warn" title="입력 인젝션 의심">⚠ 입력</span>` : ""}
        ${t.guard?.context?.length ? html`<span class="badge warn" title="근거 속 지시 의심">⚠ 근거 ${t.guard.context.length}</span>` : ""}</td></tr>`)}</table></div>`;
}

async function loadAudit(btn) {
  const q = auditParams();
  if ($("#g-status").value) q.set("status", $("#g-status").value);
  q.set("limit", String(+$("#g-limit").value || 200));
  try {
    const r = await busy(btn, () => api(`/api/guardrails/audit?${q}`));
    auditRows = r.rows;
    const keepU = $("#g-user").value, keepK = $("#g-kind").value;
    const names = [...new Set([...r.users.map(u => u.name), ...r.rows.map(t => t.user)].filter(Boolean))];
    $("#g-user").innerHTML = html`<option value="">모두</option>${names.map(n => html`<option value="${n}">${n}</option>`)}`;
    $("#g-user").value = names.includes(keepU) ? keepU : "";
    const kinds = [...new Set(r.rows.map(t => t.kind))].sort();
    $("#g-kind").innerHTML = html`<option value="">모두</option>${kinds.map(k => html`<option value="${k}">${k}</option>`)}`;
    $("#g-kind").value = kinds.includes(keepK) ? keepK : "";
    renderAudit();
  } catch (e) { ui.error($("#g-out"), e); }
}
$("#g-load").onclick = e => loadAudit(e.target);
$("#g-kind").addEventListener("change", renderAudit);

$("#g-verify").onclick = async e => {
  const r = await busy(e.target, () => api("/api/guardrails/audit/integrity"));
  $("#g-verify-out").innerHTML = r.ok
    ? html`<div class="row"><span class="badge ok">✓ 사슬 온전</span><span class="small muted">${r.checked}행 검사${r.first_id ? html` · 첫 행 #${r.first_id}` : ""}</span></div>`
    : html`<div class="errbox">⛔ 사슬이 끊긴 행 ${r.broken.length}개 (${r.checked}행 검사) — 기록이 고쳐졌거나 지워졌습니다.
        ${html.join(r.broken.map(b => html`#${b.id}${!b.link ? " (앞 행과 안 이어짐)" : ""}${!b.body ? " (내용이 바뀜)" : ""}`), ", ")}</div>`;
};

$("#g-purge").onclick = async e => {
  const days = +$("#g-purge-days").value;
  if (!(days >= 1)) return toast("1일 이상을 넣으세요", "err");
  const ok = await ui.confirm(`${days}일보다 오래된 감사 기록을 지웁니다. 되돌릴 수 없고, 지운 기록은 CSV 로도 받을 수 없습니다. 남은 기록의 무결성 검사는 그대로 됩니다.`,
    { ok: "기록 지우기", danger: true, title: "감사 기록 지우기" });
  if (!ok) return;
  const r = await busy(e.target, () => api(`/api/guardrails/audit/purge?confirm=true&days=${days}`, { method: "POST" }));
  toast(`${r.deleted}행을 지웠습니다`, "ok");
  loadAudit(null);
};

// ── 라이선스 ──
const LV = { ok: ["✓ 문제없음", "ok"], warn: ["⚠ 약관 확인", "warn"], unknown: ["? 출처 확인 필요", "muted"], block: ["⛔ 상업 사용 불가", "err"] };
const lvBadge = l => html`<span class="badge ${(LV[l] || ["", ""])[1]}">${(LV[l] || [l])[0]}</span>`;
$("#c-run").onclick = async e => {
  const body = {
    collection_id: $("#c-use-col").checked ? +$("#a-col").value || null : null,
    index_id: $("#c-use-idx").checked ? +$("#a-idx").value || null : null,
    reranker_id: +$("#c-rr").value || null,
    llm_models: groupsOf($("#c-llm").value),
  };
  const r = await busy(e.target, () => api("/api/guardrails/license", { method: "POST", body }));
  if (!r.items.length) return ui.empty($("#c-out"), "점검할 항목이 없습니다 — 컬렉션 · 인덱스 · 리랭커 · LLM 중 하나를 고르세요");
  $("#c-out").innerHTML = html`<div class="row">${r.ok ? html`<span class="badge ok">✓ 상업 사용을 막는 항목 없음</span>` : html`<span class="badge err">⛔ 상업 사용 불가 항목 있음</span>`}
      ${html.join(Object.entries(r.summary).map(([l, n]) => html`${lvBadge(l)} ${n}`), " · ")}</div>
    <div class="table-wrap"><table><tr><th>종류</th><th>이름</th><th>라이선스</th><th>판정</th></tr>
      ${r.items.map(it => html`<tr><td class="small nowrap">${it.kind}</td><td class="small">${it.name}</td><td class="small">${it.license}</td><td>${lvBadge(it.level)}</td></tr>`)}</table></div>`;
};

async function init() {
  await setupCollectionPickers({
    col: $("#a-col"), idx: $("#a-idx"), cs: $("#a-cs"),
    onDetail: async d => {
      if (d.indexes.some(i => i.status === "ready") && $("#a-mode").value === "bm25" && !d.chunk_sets.some(c => c.status === "ready")) $("#a-mode").value = "dense";
      aMode();
      const sets = (await api(`/api/collections/${d.id}/eval-sets`)).filter(s => s.status === "ready");
      $("#l-set").innerHTML = html`<option value="">쓰지 않음</option>${sets.map(s => html`<option value="${s.id}">#${s.id} ${s.name} (${s.n_items}문항)</option>`)}`;
      loadAcl();
    },
  });
  if (!$("#a-col").value) loadAcl();
  const rr = (await getModels()).filter(m => m.kind === "reranker");
  $("#c-rr").innerHTML = html`<option value="">없음</option>${rr.map(m => html`<option value="${m.id}">${m.name}</option>`)}`;
  updateCsv();
  loadAudit(null);
}
init();
