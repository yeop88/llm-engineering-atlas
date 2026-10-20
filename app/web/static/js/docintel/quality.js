// D4 정제 · 중복 · 판, D5 근거 보존율, D7 청크 품질 보고
const colId = () => +$("#q-col").value || null;
const csId = () => +$("#q-cs").value || null;

// ── 정제 · 중복 · 판 ───────────────────────────────────────────────────
$("#c-run").onclick = async e => {
  if (!colId()) return toast("컬렉션을 고르세요", "err");
  const th = +$("#c-th").value || 0.85;
  const r = await busy(e.target, () => api(`/api/docintel/collections/${colId()}/clean?threshold=${th}`));
  cRender(r);
};

function cRender(r) {
  const superseded = r.version_groups.reduce((n, g) => n + g.members.filter(m => m.superseded).length, 0);
  $("#c-out").innerHTML = html`<div class="grid cols-4">
      <div class="stat"><div class="label">문서</div><div class="value">${fmtNum(r.n_docs)}</div></div>
      <div class="stat"><div class="label">반복 줄 · 쪽 번호가 있는 문서</div><div class="value">${fmtNum(r.boilerplate.length)}</div></div>
      <div class="stat"><div class="label">거의 같은 문서 쌍</div><div class="value">${fmtNum(r.near_duplicates.length)}</div><div class="small muted">${r.near_duplicates.length >= 100 ? "앞의 100쌍만" : ""}</div></div>
      <div class="stat"><div class="label">판 묶음</div><div class="value">${fmtNum(r.version_groups.length)}</div><div class="small muted">옛 판 ${fmtNum(superseded)}개</div></div></div>

    <h3 class="mt-4">반복 줄 (머리말 · 꼬리말 · 쪽 번호)</h3>
    ${r.boilerplate.length ? html`<div class="table-wrap scroll-md"><table><tr><th>#</th><th>파일</th><th>반복되는 줄 모양 (숫자 = #)</th><th class="num">쪽 번호 줄</th><th>정제</th></tr>
      ${r.boilerplate.map(b => html`<tr><td>${b.id}</td><td class="small break-all">${b.filename}</td>
        <td class="small">${html.or(html.join(b.patterns.map(p => html`<code>${p}</code>`), "<br>"), html`<span class="muted">-</span>`)}</td>
        <td class="num">${fmtNum(b.page_numbers)}</td><td class="small">${b.cleaned ? html`<span class="badge ok">정제함</span> 줄 ${b.cleaned.repeated_lines} · 쪽 번호 ${b.cleaned.page_numbers}` : html`<span class="muted">안 함</span>`}</td></tr>`)}</table></div>`
      : html`<div class="small muted">반복 줄이 없습니다(3쪽 이상인 문서의 절반 이상 쪽에 나오는 줄을 찾습니다).</div>`}

    <h3 class="mt-4">거의 같은 문서</h3>
    ${r.near_duplicates.length ? html`<div class="table-wrap scroll-md"><table><tr><th>문서 A</th><th>문서 B</th><th class="num">자카드</th></tr>
      ${r.near_duplicates.map(p => html`<tr><td class="small">#${p.a} ${p.a_name}</td><td class="small">#${p.b} ${p.b_name}</td><td class="num">${p.sim.toFixed(3)}</td></tr>`)}</table></div>`
      : html`<div class="small muted">기준 이상으로 비슷한 문서가 없습니다.</div>`}

    <h3 class="mt-4">판 묶음</h3>
    ${r.version_groups.length ? html`<div class="stack">${r.version_groups.map(g => html`<div class="p-2 bg-code"><div class="small"><b>${g.group}</b> · ${g.members.length}개</div>
      <ul class="small m-0">${g.members.map(m => html`<li>#${m.id} ${m.filename}${m.date ? html` <span class="muted">(${m.date})</span>` : ""} ${m.superseded ? html`<span class="badge muted">옛 판</span>` : html`<span class="badge ok">최신</span>`}</li>`)}</ul></div>`)}</div>`
      : html`<div class="small muted">판 묶음이 없습니다.</div>`}`;
  $("#c-apply-row").hidden = false;
  $("#c-applied").replaceChildren();
}

$("#c-apply").onclick = async e => {
  const body = { boilerplate: $("#c-boiler").checked, versions: $("#c-versions").checked, threshold: +$("#c-th").value || 0.85 };
  if (!body.boilerplate && !body.versions) return toast("적용할 것을 고르세요", "err");
  const what = [body.boilerplate && "반복 줄 · 쪽 번호를 문서 글에서 지우고", body.versions && "판 묶음의 옛 판을 '새 판에 밀림'으로 표시하고"].filter(Boolean).join(", ");
  // 정제는 문서 글을 바꾼다(원본 파일은 남지만 되돌리려면 다시 올려야 함) — 무엇이 바뀌는지 적고 묻는다
  if (!(await ui.confirm(`이 컬렉션의 모든 문서에서 ${what} 합니다. 글을 바꾼 문서는 청크 세트가 '최신 아님'이 되어 증분 갱신이 필요합니다. 계속할까요?`, { ok: "적용", danger: body.boilerplate }))) return;
  const r = await busy(e.target, () => api(`/api/docintel/collections/${colId()}/clean/apply`, { method: "POST", body }));
  $("#c-applied").innerHTML = html`<div class="warnbox">
    ${r.boilerplate ? html`<div>정제: 문서 ${fmtNum(r.boilerplate.documents)}개 · 반복 줄 ${fmtNum(r.boilerplate.repeated_lines)} · 쪽 번호 ${fmtNum(r.boilerplate.page_numbers)}줄 지움</div>` : ""}
    ${r.versions ? html`<div>판: 묶음 ${fmtNum(r.versions.groups)}개 · 옛 판 ${fmtNum(r.versions.superseded)}개 표시</div>` : ""}
    <div class="small">${r.next} <a href="/docintel/sources">증분 갱신으로 →</a></div></div>`;
  toast("적용했습니다", "ok");
};

// ── 청크 품질 ─────────────────────────────────────────────────────────
$("#q-run").onclick = async e => {
  if (!csId()) return toast("준비된 청크 세트가 없습니다", "err");
  const r = await busy(e.target, () => api(`/api/docintel/chunk-sets/${csId()}/quality`));
  qRender(r);
};

function qRender(r) {
  const L = r.length || {};
  const hist = Object.entries(L.hist || {});
  const hmax = Math.max(1, ...hist.map(([, n]) => n));
  const strat = r.strategy || {};
  $("#q-out").innerHTML = html`
    <div class="small muted">${r.name} · ${strat.method || "-"}${strat.size ? ` · 크기 ${strat.size}` : ""}${strat.overlap ? ` · 겹침 ${strat.overlap}` : ""}${strat.merge_below ? ` · 짧은 청크 합치기 ${strat.merge_below}` : ""}</div>
    ${r.issues.length ? html`<div class="warnbox">${r.issues.map(i => html`<div>${i}</div>`)}</div>` : html`<div class="small"><span class="badge ok">문제 없음</span></div>`}
    <div class="grid cols-4">
      <div class="stat"><div class="label">청크</div><div class="value">${fmtNum(r.n_chunks)}</div><div class="small muted">글 ${fmtNum(r.n_text)} · 그림 ${fmtNum(r.n_media)}</div></div>
      <div class="stat"><div class="label">길이 (글자)</div><div class="value">${L.median ?? "-"}</div><div class="small muted">중앙값 · 평균 ${L.avg ?? "-"} · p95 ${L.p95 ?? "-"} · ${L.min ?? "-"}~${L.max ?? "-"}</div></div>
      <div class="stat"><div class="label">짧은 청크 (&lt;50자)</div><div class="value">${pct(r.short.rate)}%</div><div class="small muted">${fmtNum(r.short.n)}개</div></div>
      <div class="stat"><div class="label">똑같은 청크</div><div class="value">${pct(r.duplicates.rate)}%</div><div class="small muted">${fmtNum(r.duplicates.n)}개 · 깨진 청크 ${fmtNum(r.broken_chunks)}</div></div></div>
    ${hist.length ? html`<h3 class="mt-4">길이 분포</h3><div class="table-wrap"><table><tr><th>글자 수</th><th class="num">청크</th><th></th></tr>
      ${hist.map(([k, n]) => html`<tr><td>${k}</td><td class="num">${fmtNum(n)}</td><td><progress max="${hmax}" value="${n}" aria-label="${k}자 청크 수"></progress></td></tr>`)}</table></div>` : ""}
    ${r.short.examples.length ? html`<h3 class="mt-4">짧은 청크 예시</h3><div class="stack">${r.short.examples.map(t => html`<div class="pre bg-code p-2 small">${t}</div>`)}</div>` : ""}
    ${r.repeated_lines.length ? html`<h3 class="mt-4">여러 청크에 반복되는 줄</h3><div class="table-wrap"><table><tr><th>줄</th><th class="num">청크 수</th></tr>
      ${r.repeated_lines.map(x => html`<tr><td class="small"><code>${x.line}</code></td><td class="num">${fmtNum(x.n)}</td></tr>`)}</table></div>` : ""}
    ${r.empty_docs.length ? html`<div class="small mt-2">청크가 없는 문서: ${html.join(r.empty_docs.map(i => `#${i}`), ", ")} <a href="/docintel/parsing">파싱 점검 →</a></div>` : ""}`;
}

// ── 근거 보존율 ───────────────────────────────────────────────────────
$("#e-run").onclick = async e => {
  if (!csId()) return toast("준비된 청크 세트가 없습니다", "err");
  if (!$("#q-set").value) return toast("평가 세트가 없습니다", "err");
  const r = await busy(e.target, () => api(`/api/docintel/chunk-sets/${csId()}/preservation?eval_set_id=${$("#q-set").value}`));
  $("#e-out").innerHTML = r.n_evidences ? html`
    <div class="grid cols-3">
      <div class="stat"><div class="label">근거 보존율</div><div class="value">${pct(r.rate)}%</div></div>
      <div class="stat"><div class="label">온전히 들어간 근거</div><div class="value">${fmtNum(r.preserved)}</div><div class="small muted">전체 근거 ${fmtNum(r.n_evidences)}</div></div>
      <div class="stat"><div class="label">잘린 근거</div><div class="value">${fmtNum(r.n_evidences - r.preserved)}</div></div></div>
    ${r.broken.length ? html`<h3 class="mt-4">잘린 근거 예시</h3><div class="small muted">가장 많이 담은 청크의 비율 — 0.6 아래면 경계에 걸쳤거나(겹침 · 구조 청킹을 고려) 근거가 원문과 다릅니다(평가 세트 점검).</div>
      <div class="table-wrap"><table><tr><th>문항</th><th>근거</th><th class="num">최대 포함률</th></tr>
      ${r.broken.map(b => html`<tr><td class="small">${b.item_id ?? "-"}</td><td class="small">${b.evidence}</td><td class="num">${pct(b.best_coverage)}%</td></tr>`)}</table></div>` : ""}`
    : html`<div class="small muted">이 평가 세트에는 근거 문장이 없습니다.</div>`;
};

setupCollectionPickers({ col: $("#q-col"), cs: $("#q-cs"), set: $("#q-set"), onDetail: () => {
  ["#c-out", "#c-applied", "#q-out", "#e-out"].forEach(s => $(s).replaceChildren());
  $("#c-apply-row").hidden = true;
} });
