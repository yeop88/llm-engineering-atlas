// longrun/approvals.html 화면 스크립트 — 승인 대기 단계 목록 · 승인 · 반려(LR4), 끝난 업무의 완료 판정(LR6)
function checks(v) {
  return v?.items ? html.join(v.items.map(i => html`<div>${i.ok ? html`<span class="badge ok">통과</span>` : html`<span class="badge err">미달</span>`} ${i.key} — ${i.detail}</div>`), "") : html`<span class="muted">검사 단계 없음</span>`;
}

async function load() {
  const rows = await api("/api/longrun/approvals");
  $("#p-list").innerHTML = rows.length ? html.join(rows.map(a => html`<div class="card stack mt-2" data-run="${a.run_id}" data-idx="${a.idx}">
      <div class="row"><b>업무 <a href="/longrun/runs?run=${a.run_id}">#${a.run_id}</a></b> <span class="small">${a.goal}</span> <span class="badge warn">${a.name}</span></div>
      ${a.report ? html`<details open><summary class="small">승인할 초안</summary><div class="pre small scroll-md">${a.report}</div></details>` : ""}
      <div class="small">${checks(a.verdict_preview)}</div>
      <div class="row"><div class="field grow"><label for="p-note-${a.run_id}-${a.idx}">메모</label><input id="p-note-${a.run_id}-${a.idx}" data-note></div>
        <div class="self-end"><button class="btn primary" data-ok>승인</button> <button class="btn danger" data-no>반려</button></div></div></div>`), "")
    : html`<div class="small muted">승인을 기다리는 업무가 없습니다.</div>`;
  $$("[data-run]", $("#p-list")).forEach(card => {
    const send = async (ok, btn) => {
      if (!ok && !(await ui.confirm("반려하면 업무가 멈춥니다. 업무 화면에서 고친 뒤 '실패 · 반려 단계부터 다시'로 이어 갈 수 있습니다.", { ok: "반려", danger: true }))) return;
      busy(btn, () => api(`/api/longrun/runs/${card.dataset.run}/steps/${card.dataset.idx}/approve`, { method: "POST", body: { ok, note: $("[data-note]", card).value } }))
        .then(() => { toast(ok ? "승인했습니다 — 다음 단계부터 이어 갑니다" : "반려했습니다"); load(); }).catch(e => toast(e.message, "err"));
    };
    $("[data-ok]", card).onclick = e => send(true, e.target);
    $("[data-no]", card).onclick = e => send(false, e.target);
  });
  const done = (await api("/api/longrun/runs")).filter(r => r.status === "done");
  $("#p-done").innerHTML = done.length ? html.join(done.slice(0, 10).map(r => html`<div class="mt-2"><b><a href="/longrun/runs?run=${r.id}">#${r.id}</a></b> ${r.goal.slice(0, 80)}
      ${r.verdict?.ok ? html`<span class="badge ok">완료 조건 통과</span>` : html`<span class="badge warn">검토 필요</span>`}<div class="small">${checks(r.verdict)}</div></div>`), "")
    : html`<div class="small muted">끝난 업무가 없습니다.</div>`;
}

load().catch(e => ui.error($("#p-list"), e));
