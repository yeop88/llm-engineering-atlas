// history.html 화면 스크립트 (템플릿에서 옮김 — 화면 JS 는 static/js/<영역>/<화면>.js)
let runs = [];
const selected = new Set();

async function load() {
  const kind = $("#kind").value;
  const [list, summary] = await Promise.all([api(`/api/runs?limit=500${kind ? `&kind=${kind}` : ""}`), api("/api/runs/summary")]);
  runs = list;
  [...selected].forEach(id => { if (!runs.some(r => r.id === id)) selected.delete(id); });
  $("#summary").textContent = `전체 ${summary.total}건 · ` + Object.entries(summary.by_kind).map(([k, n]) => `${k} ${n}`).join(" · ");
  $("#btn-del-all").textContent = kind ? `'${kind}' 전체 삭제` : "전체 삭제";
  $("#btn-del-all").disabled = (kind ? summary.by_kind[kind] || 0 : summary.total) === 0;
  $("#rows").innerHTML = runs.map(r => `<tr>
    <td><input type="checkbox" class="sel" value="${r.id}" ${selected.has(r.id) ? "checked" : ""} aria-label="#${r.id} 선택"></td>
    <td>${r.id}</td><td><span class="badge muted">${r.kind}</span></td><td>${esc(r.title)}</td>
    <td class="small mono">${r.model_hf_ids.map(esc).join("<br>")}</td><td class="num">${(r.duration_ms / 1000).toFixed(2)}s</td><td class="small nowrap">${fmtDate(r.created_at)}</td>
    <td class="right nowrap">${r.kind === "benchmark" ? `<a class="btn sm" href="/embedding/benchmark" onclick="sessionStorage.setItem('run', ${r.id})">결과 보기</a>` : ""}
      <button class="btn sm" onclick="show(${r.id})">JSON</button><button class="btn sm danger" onclick="del(${r.id})">삭제</button></td></tr>`).join("")
    || '<tr><td colspan="8" class="empty">기록이 없습니다. 단계 화면에서 실험을 실행하면 여기에 쌓입니다.</td></tr>';
  updateSelection();
}
function updateSelection() {
  $("#sel-count").textContent = `${selected.size}개 선택`;
  $("#btn-del-sel").disabled = selected.size === 0;
  $("#sel-all").checked = runs.length > 0 && runs.every(r => selected.has(r.id));
  $("#sel-all").indeterminate = selected.size > 0 && !$("#sel-all").checked;
}
async function show(id) { const r = await api(`/api/runs/${id}`); $("#dlg-title").textContent = `#${r.id} ${r.title}`; $("#dlg-body").textContent = JSON.stringify(r, null, 2); $("#dlg").showModal(); }
async function del(id) {
  if (!(await ui.confirm(`이력 #${id} 을(를) 삭제할까요?`, { ok: "삭제", danger: true, title: "삭제" }))) return;
  await api(`/api/runs/${id}`, { method: "DELETE" }); selected.delete(id); toast("삭제했습니다", "ok"); load();
}
$("#btn-del-sel").onclick = async e => {
  if (!(await ui.confirm(`선택한 ${selected.size}건의 이력을 삭제할까요? 되돌릴 수 없습니다.`, { ok: "삭제", danger: true, title: "삭제" }))) return;
  const r = await busy(e.target, () => api("/api/runs/bulk-delete", { method: "POST", body: { ids: [...selected] } }));
  selected.clear(); toast(`${r.deleted}건 삭제`, "ok"); load();
};
$("#btn-del-all").onclick = async e => {
  const kind = $("#kind").value;
  const scope = kind ? `'${kind}' 종류의 이력을 모두` : "모든 이력을";
  if (!(await ui.confirm(`${scope} 삭제할까요? 되돌릴 수 없습니다.`, { ok: "삭제", danger: true, title: "삭제" }))) return;
  const r = await busy(e.target, () => api(`/api/runs?confirm=true${kind ? `&kind=${kind}` : ""}`, { method: "DELETE" }));
  selected.clear(); toast(`${r.deleted}건 삭제`, "ok"); load();
};
$("#rows").addEventListener("change", e => {
  if (!e.target.classList.contains("sel")) return;
  const id = Number(e.target.value);
  e.target.checked ? selected.add(id) : selected.delete(id);
  updateSelection();
});
$("#sel-all").addEventListener("change", e => {
  runs.forEach(r => (e.target.checked ? selected.add(r.id) : selected.delete(r.id)));
  $$("#rows .sel").forEach(cb => (cb.checked = e.target.checked));
  updateSelection();
});
$("#kind").addEventListener("change", () => { selected.clear(); load(); });
load();
// 대시보드 · 다른 화면에서 /history#run-<번호> 로 오면 그 기록을 바로 연다
const _runHash = /^#run-(\d+)$/.exec(location.hash);
if (_runHash) show(+_runHash[1]).catch(e => toast(e.message, "err"));
