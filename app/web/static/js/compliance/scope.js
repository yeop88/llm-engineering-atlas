// compliance/scope.html 화면 스크립트 — 규제 자료 가져오기, 기능별 적용 조항(RC1) · 의무 → 조항 검색 실측, 위험 등급 제안 · 확정(RC2)
let CAT = null;
const col = () => $("#s-col").value;
const SHORT = law => (CAT?.regulations.find(r => r.law === law)?.short) || law;
const ctrlName = id => CAT?.controls.find(c => c.id === id)?.name || id;

async function loadCorpus() {
  if (!col()) { $("#s-corpus").innerHTML = html`<span class="muted">컬렉션을 먼저 만드세요(2 RAG → 컬렉션, 분야 '법률').</span>`; return; }
  const a = await api(`/api/compliance/corpus/${col()}/articles?limit=1`);
  $("#s-corpus").innerHTML = a.total
    ? html`조항 ${fmtNum(a.total)}개 — ${html.join(Object.entries(a.laws).map(([k, v]) => html`<span class="badge">${SHORT(k)} ${v}</span>`), " ")}`
    : html`<span class="muted">이 컬렉션에 법령 문서가 없습니다 — '기본 규제 가져오기'로 ${html.join(CAT.regulations.map(r => html`<b>${r.short}</b>`), " · ")}를 받습니다${CAT.law_api ? "" : " (LAW_API_OC 설정 필요)"}.</span>`;
}

function renderScope(r) {
  const items = r.items.map(it => html`<tr>
    <td class="small nowrap"><b>${SHORT(it.law)}</b> ${it.article}${it.title ? html`<div class="muted">${it.title}</div>` : ""}</td>
    <td class="small">${it.obligation}${it.found ? html`<details><summary>원문 (${it.enforced} 시행판)</summary><div class="pre small">${it.text}</div></details>`
      : html` <span class="badge warn" title="규제 자료 컬렉션에 이 조항이 없습니다">원문 없음</span>`}</td>
    <td class="small">${html.join(it.controls.map(c => html`<span class="badge">${ctrlName(c)}</span>`), " ")}</td></tr>`);
  $("#s-out").innerHTML = html`<div class="row"><b>${r.name}</b> <span class="small muted">조항 ${r.items.length}개 · 필요한 통제 ${r.controls.length}개${r.missing.length ? ` · 원문 없음 ${r.missing.length}` : ""}</span></div>
    ${r.items.length ? html`<div class="table-wrap"><table><tr><th>조항</th><th>의무 요지</th><th>통제</th></tr>${html.join(items, "")}</table></div>` : html`<div class="empty">적용 규칙이 없습니다.</div>`}
    ${r.searched ? html`<details class="small"><summary>검토할 후보 — 규칙에 없지만 기능 설명과 가까운 조항 ${r.suggestions.length}개</summary>
      <p class="muted">비슷한 조항이 나왔다고 적용되는 것은 아닙니다. 사람이 읽고 적용된다면 규칙(presets/rules.json)에 더합니다.</p>
      <ul>${html.join(r.suggestions.map(s => html`<li><b>${s.key}</b> ${s.title} <span class="muted">${s.text}</span></li>`), "")}</ul></details>`
      : html`<div class="small muted">검색할 청크 세트가 없어 후보를 찾지 않았습니다.</div>`}`;
}

function renderEval(r) {
  $("#s-eval-out").innerHTML = html`<div class="row"><b>hit@1 ${pct(r["hit@1"])}%</b> <span class="small muted">· hit@3 ${pct(r["hit@3"])}% · hit@5 ${pct(r["hit@5"])}% · hit@10 ${pct(r["hit@10"])}% · MRR ${r.mrr} · ${r.config.mode} · ${r.n}문항${r.run_id ? ` · run #${r.run_id}` : ""}</span></div>
    <div class="table-wrap scroll-md"><table><tr><th>#</th><th>질문</th><th>순위</th><th>1 · 2위로 찾은 조항</th></tr>
    ${html.join(r.rows.map(x => html`<tr><td class="small nowrap">${x.id}</td><td class="small">${x.q}</td>
      <td>${x.rank ? html`<span class="badge ${x.rank === 1 ? "ok" : ""}">${x.rank}</span>` : html`<span class="badge warn">못 찾음</span>`}</td>
      <td class="small">${x.top.slice(0, 2).join(" · ")}</td></tr>`), "")}</table></div>`;
}

const GRADE_CLASS = { "높음": "err", "중간": "warn", "낮음": "ok" };
async function loadRisk() {
  const rows = await api("/api/compliance/risk");
  const dims = CAT.rubric.dimensions;
  $("#s-rubric").innerHTML = html`${CAT.rubric.note}<div class="table-wrap"><table><tr><th>기준</th><th>1</th><th>2</th><th>3</th></tr>
    ${html.join(dims.map(d => html`<tr><td><b>${d.name}</b></td>${html.join(["1", "2", "3"].map(l => html`<td class="small">${d.levels[l]}</td>`), "")}</tr>`), "")}</table></div>
    <div class="muted">점수 합 ${html.join(CAT.rubric.grades.map(g => html`${g.grade} ≥ ${g.min}`), " · ")}</div>`;
  $("#s-risk").innerHTML = html`<div class="table-wrap"><table><tr><th>기능</th><th>기준표 값</th><th>제안</th><th>확정</th><th>없는 통제</th></tr>
    ${html.join(rows.map(r => {
      const rec = r.record;
      const vals = rec?.data?.values || r.suggested.values;
      return html`<tr data-profile="${r.profile}">
        <td class="small"><b>${r.name}</b>${r.example ? html` <span class="badge muted">예시</span>` : ""}</td>
        <td class="small">${html.join(dims.map(d => html`<label class="row m-0 nowrap">${d.name}
          <select data-dim="${d.key}" aria-label="${r.name} ${d.name}">${html.join(["1", "2", "3"].map(l => html`<option value="${l}" ${String(vals[d.key]) === l ? "selected" : ""}>${l}</option>`), "")}</select></label>`), "")}</td>
        <td class="small"><span class="badge ${GRADE_CLASS[r.suggested.grade]}">${r.suggested.grade}</span> ${r.suggested.score}점
          <details><summary>이유</summary><ul>${html.join(r.suggested.reasons.map(x => html`<li>${x}</li>`), "")}</ul></details></td>
        <td class="small">${rec ? html`<span class="badge ${GRADE_CLASS[rec.data.grade]}">${rec.data.grade}</span> ${rec.status === "confirmed" ? html`<span class="badge ok">확정 · ${rec.reviewed_by}</span>` : html`<span class="badge">초안</span>
          <button class="btn sm" data-confirm="${rec.id}">확정</button>`}${rec.data.reason ? html`<div class="muted">${rec.data.reason}</div>` : ""}` : html`<span class="muted">기록 없음</span>`}
          <div class="row m-0 mt-2"><select data-grade aria-label="${r.name} 등급"><option value="">제안대로</option><option>낮음</option><option>중간</option><option>높음</option></select>
          <input data-reason class="w-md" placeholder="제안과 다르면 이유" aria-label="${r.name} 등급 이유"><button class="btn sm" data-save>저장</button></div></td>
        <td class="small">${r.coverage.gaps.length ? html.join(r.coverage.gaps.map(g => html`<span class="badge warn">${ctrlName(g)}</span>`), " ") : html`<span class="muted">없음</span>`}</td></tr>`;
    }), "")}</table></div>`;
  $$("[data-save]", $("#s-risk")).forEach(b => b.onclick = async () => {
    const tr = b.closest("tr");
    const values = Object.fromEntries($$("[data-dim]", tr).map(s => [s.dataset.dim, +s.value]));
    await busy(b, () => api(`/api/compliance/risk/${tr.dataset.profile}`, { method: "POST", body: { values, grade: $("[data-grade]", tr).value || null, reason: $("[data-reason]", tr).value } }))
      .then(() => { toast("초안을 저장했습니다 — 관리자가 확정합니다"); loadRisk(); }).catch(e => toast(e.message, "err"));
  });
  $$("[data-confirm]", $("#s-risk")).forEach(b => b.onclick = async () => {
    if (!(await ui.confirm("이 위험 등급을 확정할까요? 확정한 사람으로 이름이 남습니다.", { ok: "확정" }))) return;
    await busy(b, () => api(`/api/compliance/records/${b.dataset.confirm}/confirm`, { method: "POST" })).then(loadRisk).catch(e => toast(e.message, "err"));
  });
}

async function init() {
  CAT = await api("/api/compliance/catalog");
  $("#s-profile").innerHTML = html`${CAT.profiles.map(p => html`<option value="${p.key}">${p.name}</option>`)}`;
  const desc = () => {
    const p = CAT.profiles.find(x => x.key === $("#s-profile").value);
    $("#s-profile-desc").innerHTML = html`${p.description} — 특성: ${html.join(p.attrs.map(a => html`<span class="badge" title="${CAT.attrs[a]}">${CAT.attrs[a]}</span>`), " ")}`;
  };
  $("#s-profile").addEventListener("change", desc);
  desc();
  await setupCollectionPickers({ col: $("#s-col"), onDetail: () => loadCorpus().catch(e => ui.error($("#s-corpus"), e)) });
  loadRisk().catch(e => ui.error($("#s-risk"), e));
}

$("#s-import").onclick = e => runJobInto(e.target, `/api/compliance/corpus/${col()}/import`, { date: $("#s-date").value.trim() || null }, $("#s-import-progress"), r => {
  toast(`가져옴 ${r.added.length} · 건너뜀 ${r.skipped.length}`);
  if (r.skipped.length) {  // 이미 있는 법령은 판이 섞이지 않게 건너뛴다 — 왜 건너뛰었는지 보이게
    ui.error($("#s-import-progress"), r.skipped.map(s => `${s.law}: ${s.reason}`).join("\n"));
    $("#s-import-progress").hidden = false;
  }
  loadCorpus();
}).catch(err => toast(err.message, "err"));
$("#s-run").onclick = e => busy(e.target, () => api(`/api/compliance/scope/${$("#s-profile").value}${col() ? `?collection_id=${col()}` : ""}`)).then(renderScope).catch(err => ui.error($("#s-out"), err));
$("#s-eval").onclick = e => runJobInto(e.target, "/api/compliance/scope/eval", { collection_id: +col(), k: 10 }, $("#s-eval-progress"), renderEval).catch(err => toast(err.message, "err"));

init().catch(e => ui.error($("#s-out"), e));
