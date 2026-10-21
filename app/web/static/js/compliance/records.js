// compliance/records.html 화면 스크립트 — 처리 근거 · 보관(RC3), 결정 기록(RC4), 사람 검토 요청 처리(RC6)
const OUTCOME = { upheld: "답 유지", corrected: "고쳐 다시 답함", handoff: "상담원에게 넘김" };
const day = s => (s ? s.slice(0, 10) : "-");

async function loadData() {
  const d = await api("/api/compliance/data");
  const reg = r => r ? html`<span class="badge ok">${r.purpose}</span> <span class="muted">${r.basis} · ${r.retention_days ? `${r.retention_days}일` : "기한 없음"}${r.owner ? ` · ${r.owner}` : ""}</span>` : html`<span class="badge warn">미등록</span>`;
  $("#r-data").innerHTML = html`<div class="table-wrap"><table><tr><th>자료</th><th>문서</th><th>출처 · 라이선스</th><th>처리 근거</th><th>기한 지남</th></tr>
    ${html.join(d.collections.map(c => html`<tr><td class="small"><b>${c.name}</b> <span class="muted">${c.domain}</span></td><td class="small">${fmtNum(c.documents)}</td>
      <td class="small">${c.with_source}/${c.documents}${c.licenses.length ? html`<div class="muted">${c.licenses.join(" · ")}</div>` : ""}</td>
      <td class="small">${reg(c.register)}</td><td class="small">${c.expired || ""}</td></tr>`), "")}
    ${html.join(d.logs.map(l => html`<tr><td class="small"><b>${l.name}</b> <span class="muted">${l.setting}</span></td><td class="small">${fmtNum(l.n)}</td>
      <td class="small muted">가장 오래된 것 ${day(l.oldest)}</td><td class="small">${reg(l.register)}${l.setting ? html`<div class="muted">설정 보관 ${l.retention_days ? `${l.retention_days}일` : "0 (지우지 않음)"}</div>` : ""}</td>
      <td class="small">${l.expired || ""}</td></tr>`), "")}</table></div>`;
  $("#r-subject").innerHTML = html`${d.collections.map(c => html`<option value="collection:${c.collection_id}">${c.name}</option>`)}${d.logs.map(l => html`<option value="log:${l.key}">${l.name}</option>`)}`;
}

async function loadRecent() {
  const rows = await api("/api/compliance/decisions?limit=15");
  $("#r-recent").innerHTML = rows.length ? html`<div class="table-wrap scroll-md"><table><tr><th>#</th><th>때</th><th>종류</th><th>질문</th><th>기록</th></tr>
    ${html.join(rows.map(t => html`<tr><td><a href="#" data-trace="${t.trace_id}">${t.trace_id}</a></td><td class="small nowrap">${t.at.slice(0, 16).replace("T", " ")}</td>
      <td class="small">${t.kind}</td><td class="small">${t.question}</td>
      <td class="small">${t.complete ? html`<span class="badge ok">근거 · 검증</span>` : html`<span class="badge warn">빠짐</span>`} ${t.notice ? html`<span class="badge">고지</span>` : ""}</td></tr>`), "")}</table></div>`
    : html`<div class="small muted">서비스 답변 기록이 아직 없습니다.</div>`;
  $$("[data-trace]", $("#r-recent")).forEach(a => a.onclick = ev => { ev.preventDefault(); openDecision(+a.dataset.trace); });
}

async function openDecision(id) {
  $("#r-trace").value = id;
  const d = await api(`/api/compliance/decisions/${id}`);
  const v = d.verify || {};
  const integ = d.integrity;
  $("#r-decision").innerHTML = html`<div class="card stack mt-2">
    <div class="row"><b>요청 #${d.trace_id}</b> <span class="small muted">${d.at.slice(0, 19).replace("T", " ")} · ${d.user} · ${d.kind} · ${d.model || "모델 없음"} · ${d.status}</span>
      ${integ.body && integ.link !== false ? html`<span class="badge ok">기록 고쳐지지 않음</span>` : html`<span class="badge err">기록이 바뀜</span>`}
      ${d.guard.notice ? html`<span class="badge">AI 고지함</span>` : html`<span class="badge warn">고지 기록 없음</span>`}</div>
    <div><b>질문</b><div class="pre small">${d.question}</div></div>
    <div><b>답</b><div class="pre small">${d.answer}</div></div>
    <div class="small">검증: 근거 일치 ${v.supported_ratio ?? "-"} · 질문 관련성 ${v.relevant_ratio ?? "-"}${v.refused ? " · 거절" : ""}${v.invalid_citations?.length ? ` · 없는 근거 번호 ${v.invalid_citations.join(",")}` : ""}${v.citations ? ` · 조문 인용 ${v.citations.n}개 중 못 찾음 ${v.citations.not_found}` : ""}
      · 가드레일 출력 ${d.guard.output_action || "-"}${d.guard.changed ? " (답을 고침)" : ""}${d.guard.input?.suspicious ? " · 입력 의심" : ""}</div>
    <div><b>근거 ${d.sources.length}</b><ol class="small">${html.join(d.sources.map(s => html`<li><b>${s.filename}</b>${s.text ? html`<div class="muted">${s.text}</div>` : html` <span class="muted">(청크를 다시 나눠 본문 없음)</span>`}</li>`), "")}</ol></div>
    <div class="small muted">단계: ${d.steps.map(s => `${s.name} ${Math.round(s.ms || 0)}ms`).join(" → ")}</div>
    ${d.reviews.length ? html`<div class="small">검토 요청: ${html.join(d.reviews.map(r => html`<span class="badge">#${r.id} ${r.status}${r.outcome ? ` · ${OUTCOME[r.outcome]}` : ""}</span>`), " ")}</div>` : ""}</div>`;
}

async function loadReviews() {
  const st = $("#r-status").value;
  const r = await api(`/api/compliance/reviews${st ? `?status=${st}` : ""}`);
  $("#r-reviews").innerHTML = r.rows.length ? html`<div class="table-wrap"><table><tr><th>#</th><th>요청</th><th>이유</th><th>상태</th><th>처리</th></tr>
    ${html.join(r.rows.map(x => html`<tr data-review="${x.id}"><td class="small">${x.id}</td><td class="small"><a href="#" data-trace="${x.trace_id}">답 #${x.trace_id}</a> · ${x.by} · ${day(x.at)}</td>
      <td class="small">${x.reason_label}${x.note ? html`<div class="muted">${x.note}</div>` : ""}</td>
      <td class="small">${x.status === "open" ? html`<span class="badge warn">열림</span>` : html`<span class="badge ok">${OUTCOME[x.outcome] || "처리됨"} · ${x.reviewed_by}</span>${x.resolution ? html`<div class="muted">${x.resolution}</div>` : ""}`}</td>
      <td class="small">${x.status === "open" ? html`<div class="row m-0"><select data-outcome aria-label="처리 결과 #${x.id}">${html.join(Object.entries(OUTCOME).map(([k, v]) => html`<option value="${k}">${v}</option>`), "")}</select>
        <input data-note class="w-md" placeholder="처리 내용" aria-label="처리 내용 #${x.id}"><button class="btn sm" data-resolve>처리</button></div>` : ""}</td></tr>`), "")}</table></div>`
    : html`<div class="small muted">검토 요청이 없습니다(기한 ${r.sla_days}일 — 넘기면 감사에서 실패).</div>`;
  $$("[data-trace]", $("#r-reviews")).forEach(a => a.onclick = ev => { ev.preventDefault(); openDecision(+a.dataset.trace); location.hash = "decisions"; });
  $$("[data-resolve]", $("#r-reviews")).forEach(b => b.onclick = () => {
    const tr = b.closest("tr");
    busy(b, () => api(`/api/compliance/reviews/${tr.dataset.review}/resolve`, { method: "POST", body: { outcome: $("[data-outcome]", tr).value, note: $("[data-note]", tr).value } }))
      .then(() => { toast("처리했습니다"); loadReviews(); }).catch(e => toast(e.message, "err"));
  });
}

$("#r-save").onclick = e => busy(e.target, () => api("/api/compliance/data/register", { method: "POST", body: {
  subject: $("#r-subject").value, purpose: $("#r-purpose").value.trim(), basis: $("#r-basis").value.trim(), retention_days: +$("#r-days").value || 0, owner: $("#r-owner").value.trim() } }))
  .then(() => { toast("등록했습니다"); loadData(); }).catch(err => toast(err.message, "err"));
$("#r-purge").onclick = async e => {
  if (!(await ui.confirm("보관 기한이 지난 요청 기록 · 고객 프로필과, 등록한 기한이 지난 컬렉션 문서(청크 · 벡터 포함)를 지웁니다. 되돌릴 수 없습니다.", { ok: "지우기", danger: true }))) return;
  const r = await busy(e.target, () => api("/api/compliance/data/purge?confirm=true", { method: "POST" })).catch(err => toast(err.message, "err"));
  if (r) { toast(`요청 기록 ${r.traces} · 프로필 ${r.profiles} · 문서 ${r.documents.deleted}건 삭제`); loadData(); }
};
$("#r-open").onclick = () => { const id = +$("#r-trace").value; if (id) openDecision(id).catch(e => ui.error($("#r-decision"), e)); };
$("#r-status").addEventListener("change", () => loadReviews().catch(e => ui.error($("#r-reviews"), e)));

api("/api/compliance/catalog").then(c => { $("#r-notice").innerHTML = c.notice ? html`서비스 답변의 고지(AI_NOTICE): <span class="muted">${c.notice}</span>` : html`<span class="badge warn">AI 응답 고지가 꺼져 있습니다(AI_NOTICE 비어 있음)</span>`; }).catch(() => {});
loadData().catch(e => ui.error($("#r-data"), e));
loadRecent().catch(e => ui.error($("#r-recent"), e));
loadReviews().catch(e => ui.error($("#r-reviews"), e));
const want = new URLSearchParams(location.search).get("trace");
if (want) openDecision(+want).catch(e => ui.error($("#r-decision"), e));
