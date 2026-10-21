// posttrain/data.html 화면 스크립트 — 학습 데이터 모으기(P1), 선별 단계별 남은 건수 · 목록(P2)
const STAGES = [["in", "모음"], ["format_ok", "형식"], ["dedup", "중복 제거"], ["no_leak", "누수 제거"]];

function report(r) {
  return html`<div class="row small">${html.join(STAGES.map(([k, l]) => html`<span class="badge">${l} ${r[k] ?? "-"}</span>`), " → ")}
    ${Object.keys(r.by_source || {}).length ? html` · ${html.join(Object.entries(r.by_source).map(([k, v]) => html`${k} ${v}`), " · ")}` : ""}</div>
    ${r.leaked_examples?.length ? html`<details class="small"><summary>누수로 뺀 예 ${r.leaked_examples.length}</summary><ul>${html.join(r.leaked_examples.map(q => html`<li>${q}</li>`), "")}</ul></details>` : ""}`;
}

async function load() {
  const o = await api("/api/posttrain/overview");
  $("#d-distill").innerHTML = o.distill_files.length ? html.join(o.distill_files.map(f => html`<label class="row m-0"><input type="checkbox" data-file="${f.name}"> ${f.name} <span class="muted">${f.samples}건</span></label>`), "")
    : html`<span class="muted">증류 파일이 없습니다(7a 증류에서 교사 답 만들기)</span>`;
  $("#d-list").innerHTML = o.datasets.length ? html.join(o.datasets.map(d => html`<div class="mt-2"><b class="mono">${d.name}</b> <span class="badge">${d.kind}</span> ${d.n}건${report(d.report)}</div>`), "")
    : html`<div class="small muted">데이터가 없습니다.</div>`;
}

$("#d-build").onclick = e => {
  const set = +$("#d-set").value || null;
  const body = { name: $("#d-name").value.trim(), kind: $("#d-kind").value, distill: $$("[data-file]").filter(x => x.checked).map(x => x.dataset.file), flywheel: $("#d-fw").checked,
    refusal_sets: set && $("#d-refuse").checked ? [set] : [], exclude_sets: set && $("#d-leak").checked ? [set] : [], collection_id: +$("#d-col").value || null };
  busy(e.target, () => api("/api/posttrain/datasets", { method: "POST", body })).then(r => { $("#d-out").innerHTML = html`<div><b>${r.name}</b> ${r.n}건</div>${report(r.report)}`; load(); })
    .catch(err => ui.error($("#d-out"), err));
};

setupCollectionPickers({ col: $("#d-col"), set: $("#d-set") }).catch(() => {});
load().catch(e => ui.error($("#d-list"), e));
