const params = new URLSearchParams(location.search);
["q", "kind", "modality", "tag", "status", "sort"].forEach(k => { if (params.get(k)) $(`#f-${k}`).value = params.get(k); });

let timer = null;
let current = [];          // 현재 목록 (필터 적용 후)
const selected = new Set(); // 선택한 모델 id (다운로드 진행 중 자동 새로고침에도 유지)

async function load() {
  const qs = new URLSearchParams();
  ["q", "kind", "modality", "tag", "status", "sort"].forEach(k => { const v = $(`#f-${k}`).value; if (v) qs.set(k, v); });
  history.replaceState(null, "", `?${qs}`);
  current = await api(`/api/models?${qs}`);
  [...selected].forEach(id => { if (!current.some(m => m.id === id)) selected.delete(id); });
  $("#rows").innerHTML = current.map(row).join("") || '<tr><td colspan="11" class="empty">조건에 맞는 모델이 없습니다</td></tr>';
  updateSelection();
  loadExclusions();
  clearTimeout(timer);
  if (current.some(m => m.download_job)) timer = setTimeout(load, 1500);
}

function updateSelection() {
  $("#sel-count").textContent = `${selected.size}개 선택`;
  $("#btn-bulk-delete").disabled = selected.size === 0;
  $("#sel-all").checked = current.length > 0 && current.every(m => selected.has(m.id));
  $("#sel-all").indeterminate = selected.size > 0 && !$("#sel-all").checked;
}

async function loadExclusions() {
  const ex = await api("/api/catalog/exclusions");
  const btn = $("#btn-restore");
  btn.hidden = ex.length === 0;
  btn.textContent = `삭제한 기본 모델 복원 (${ex.length})`;
  btn.title = ex.map(e => e.hf_id).join("\n");
}

// 삭제 대화상자: 단건/다건 공통
function openDelete(ids) {
  const targets = current.filter(m => ids.includes(m.id));
  if (!targets.length) return;
  const cacheBytes = targets.reduce((s, m) => s + (m.cached ? m.cache_size_bytes : 0), 0);
  $("#del-msg").textContent = targets.length === 1 ? `${targets[0].hf_id} 을(를) 카탈로그에서 삭제할까요?` : `선택한 ${targets.length}개 모델을 카탈로그에서 삭제할까요?`;
  $("#del-list").innerHTML = targets.length > 1 ? targets.map(m => esc(m.hf_id)).join("<br>") : "";
  $("#del-cache").checked = false;
  $("#del-cache-row").hidden = cacheBytes === 0;
  $("#del-cache-size").textContent = cacheBytes ? `(${fmtBytes(cacheBytes)} 확보)` : "";
  $("#del-go").onclick = async e => {
    const r = await busy(e.target, () => api("/api/models/bulk-delete", { method: "POST", body: { ids: targets.map(m => m.id), delete_cache: $("#del-cache").checked } }));
    $("#dlg-delete").close();
    targets.forEach(m => selected.delete(m.id));
    toast(`${r.deleted.length}개 모델 삭제${r.freed_bytes ? ` · ${fmtBytes(r.freed_bytes)} 확보` : ""}`, "ok");
    load();
  };
  $("#dlg-delete").showModal();
}

function row(m) {
  const dims = m.mrl_dims?.length ? `<div class="small muted" title="Matryoshka 차원">${m.mrl_dims.join("/")}</div>` : "";
  const loaded = m.loaded_profiles.length > 0;
  const dl = m.download_job
    ? `<div class="progress" title="${esc(m.download_job.message)}"><div style="width:${pct(m.download_job.progress)}%"></div></div><div class="small muted">${esc(m.download_job.message)}</div>`
    : "";
  return `<tr>
    <td><input type="checkbox" class="sel" value="${m.id}" ${selected.has(m.id) ? "checked" : ""} aria-label="${esc(m.hf_id)} 선택"></td>
    <td><button class="btn sm" title="즐겨찾기" onclick="fav(${m.id}, ${!m.is_favorite})">${m.is_favorite ? "★" : "☆"}</button></td>
    <td><a href="/embedding/models/${m.id}"><b>${esc(m.name)}</b></a><br>
      <a class="small mono" href="https://huggingface.co/${esc(m.hf_id)}" target="_blank" rel="noopener">${esc(m.hf_id)}</a>
      <div class="small muted">${esc(m.provider)}</div></td>
    <td class="nowrap">${esc(m.release_date)}</td>
    <td class="num">${esc(m.params)}</td>
    <td class="num">${m.dim ?? "-"}${dims}</td>
    <td class="num">${fmtNum(m.max_seq_len)}</td>
    <td class="small">${esc(m.license)}</td>
    <td class="small">${esc(m.languages)}<br><span class="muted">${m.modalities.join(" · ")}</span></td>
    <td>${modelBadges(m)}${m.cached ? `<div class="small muted">${fmtBytes(m.cache_size_bytes)}</div>` : ""}${dl}</td>
    <td class="right nowrap">
      ${m.cached ? "" : `<button class="btn sm" onclick="download(${m.id}, this)" ${m.download_job ? "disabled" : ""}>다운로드</button>`}
      ${loaded ? `<button class="btn sm" onclick="act(${m.id}, 'unload', this)">언로드</button>`
               : `<button class="btn sm" onclick="act(${m.id}, 'load', this)">로드</button>`}
      ${m.cached ? `<button class="btn sm danger" onclick="removeCache(${m.id}, '${esc(m.hf_id)}', this)">캐시 삭제</button>` : ""}
      ${m.kind === "reranker" ? "" : `<a class="btn sm" href="/embedding/playground?model=${m.id}">테스트</a>`}
      <button class="btn sm danger" title="카탈로그에서 삭제" onclick="openDelete([${m.id}])">삭제</button>
    </td>
  </tr>`;
}

async function download(id, btn) {
  await busy(btn, () => api(`/api/models/${id}/download`, { method: "POST" }));
  toast("다운로드를 시작했습니다");
  load();
}
async function act(id, action, btn) {
  const r = await busy(btn, () => api(`/api/models/${id}/${action}`, { method: "POST" }));
  toast(action === "load" ? `로드 완료 (${r.load_seconds}s, ${r.dim}차원, ${r.device}/${r.dtype})` : "언로드했습니다", "ok");
  load();
}
async function removeCache(id, hfId, btn) {
  if (!(await ui.confirm(`${hfId} 의 로컬 캐시를 삭제할까요?`, { ok: "삭제", danger: true, title: "삭제" }))) return;
  const r = await busy(btn, () => api(`/api/models/${id}/cache`, { method: "DELETE" }));
  toast(`${fmtBytes(r.freed_bytes)} 확보`, "ok");
  load();
}
async function fav(id, value) {
  await api(`/api/models/${id}`, { method: "PATCH", body: { is_favorite: value } });
  load();
}

$("#btn-add").onclick = () => $("#dlg-add").showModal();
$("#add-go").onclick = async e => {
  const id = $("#add-id").value.trim();
  if (!id) return;
  const m = await busy(e.target, () => api("/api/hub/import", { method: "POST", body: { hf_id: id } }));
  $("#dlg-add").close();
  toast(`${m.hf_id} 추가됨`, "ok");
  location.href = `/embedding/models/${m.id}`;
};

$("#rows").addEventListener("change", e => {
  if (!e.target.classList.contains("sel")) return;
  const id = Number(e.target.value);
  e.target.checked ? selected.add(id) : selected.delete(id);
  updateSelection();
});
$("#sel-all").addEventListener("change", e => {
  current.forEach(m => (e.target.checked ? selected.add(m.id) : selected.delete(m.id)));
  $$("#rows .sel").forEach(cb => (cb.checked = e.target.checked));
  updateSelection();
});
$("#btn-bulk-delete").onclick = () => openDelete([...selected]);
$("#btn-restore").onclick = async e => {
  if (!(await ui.confirm("삭제했던 기본 카탈로그 모델을 모두 다시 등록할까요? (카탈로그 기본 설정으로 등록됩니다)", { ok: "다시 등록" }))) return;
  const r = await busy(e.target, () => api("/api/catalog/restore", { method: "POST" }));
  toast(`${r.added}개 모델 복원`, "ok");
  load();
};

["f-kind", "f-modality", "f-tag", "f-status", "f-sort"].forEach(id => $(`#${id}`).addEventListener("change", load));
let qTimer; $("#f-q").addEventListener("input", () => { clearTimeout(qTimer); qTimer = setTimeout(load, 250); });
load();

// 호환성 점검 — 마지막 결과와 '라이브러리가 바뀌어 다시 점검 권장' 표시
function showCompat(r) {
  if (!r) { $("#c-out").innerHTML = '<div class="empty">아직 점검한 적이 없습니다</div>'; return; }
  $("#c-out").innerHTML = `<div class="small muted">${esc(r.created_at ? fmtDate(r.created_at) : "방금")} · ${r.n_ok}/${r.n} 통과 · ${r.seconds}초 · ${Object.entries(r.versions || {}).map(([k, v]) => `${esc(k)} ${esc(v)}`).join(" · ")}</div>
    <div class="table-wrap"><table><tr><th>모델</th><th>결과</th><th class="num">차원</th><th class="num">관련−무관 차이</th><th class="num">로드(초)</th><th>문제</th></tr>
    ${r.results.map(x => `<tr><td class="mono small">${esc(x.hf_id)}</td><td>${x.ok ? '<span class="badge ok">✓ 통과</span>' : '<span class="badge err">✗ 문제</span>'}</td>
      <td class="num">${x.dim ?? "-"}</td><td class="num small">${(x.margins || []).join(" / ") || "-"}</td><td class="num">${x.load_seconds ?? "-"}</td>
      <td class="small">${esc((x.issues || []).concat(x.warnings || []).join(" · ")) || "-"}</td></tr>`).join("")}</table></div>`;
}
(async () => {
  const r = await api("/api/models/compat-check/last");
  $("#c-ver").textContent = Object.entries(r.versions).map(([k, v]) => `${k} ${v}`).join(" · ");
  if (r.upgrade_detected) { $("#c-head").innerHTML = '<span class="badge warn">⚠ 지난 점검 뒤 라이브러리 버전이 바뀜 — 점검 권장</span>'; $("#compat").open = true; }
  else if (r.run) $("#c-head").textContent = `마지막 점검: ${r.run.n_ok}/${r.run.n} 통과`;
  showCompat(r.run);
})();
$("#c-run").onclick = e => runJobInto(e.target, "/api/models/compat-check", undefined, $("#c-progress"), r => { showCompat(r); $("#c-head").textContent = `마지막 점검: ${r.n_ok}/${r.n} 통과`; });
