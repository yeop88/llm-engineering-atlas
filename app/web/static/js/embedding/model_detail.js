let model = null;
let loadedInfo = null;

function fillForm(m) {
  const form = $("#form");
  $$("[name]", form).forEach(el => {
    const v = m[el.name];
    if (el.type === "checkbox") el.checked = !!v;
    else if (el.dataset.type === "json") el.value = v && Object.keys(v).length ? JSON.stringify(v, null, 1) : "";
    else if (el.dataset.type === "list" || el.dataset.type === "intlist") el.value = (v || []).join(",");
    else el.value = v ?? "";
  });
}

function readForm() {
  const out = {};
  $$("[name]", $("#form")).forEach(el => {
    const t = el.dataset.type;
    if (el.type === "checkbox") out[el.name] = el.checked;
    else if (t === "json") {
      try { out[el.name] = el.value.trim() ? JSON.parse(el.value) : {}; }
      catch { throw new Error(`${el.name}: JSON 형식이 올바르지 않습니다`); }
    } else if (t === "list") out[el.name] = el.value.split(",").map(s => s.trim()).filter(Boolean);
    else if (t === "intlist") out[el.name] = el.value.split(",").map(s => parseInt(s, 10)).filter(n => !isNaN(n));
    else if (el.type === "number") out[el.name] = el.value === "" ? null : Number(el.value);
    else out[el.name] = el.value;
  });
  return out;
}

async function load() {
  model = await api(`/api/models/${MODEL_ID}`);
  const loaded = await api("/api/loaded");
  loadedInfo = loaded.filter(l => l.model_id === MODEL_ID);
  $("#title").textContent = model.name;
  $("#hf-link").textContent = model.hf_id;
  $("#hf-link").href = `https://huggingface.co/${model.hf_id}`;
  $("#badges").innerHTML = modelBadges(model);
  $("#b-load-mm").hidden = !model.modalities.some(x => x !== "text");
  $("#b-download").hidden = model.cached;
  $("#b-unload").hidden = !model.loaded_profiles.length;
  if (!document.activeElement || !$("#form").contains(document.activeElement)) fillForm(model);
  $("#error").innerHTML = model.last_error ? `<div class="errbox"><b>최근 로드 오류</b><br>${esc(model.last_error)}</div>` : "";

  const prompts = [...new Set(loadedInfo.flatMap(l => l.prompts))];
  $("#prompt-names").innerHTML = prompts.map(p => `<option value="${esc(p)}">`).join("");
  $("#runtime").innerHTML = [
    ["로컬 캐시", model.cached ? `${fmtBytes(model.cache_size_bytes)}` : "없음"],
    ["로드 상태", loadedInfo.length ? loadedInfo.map(l => `${l.profile} · ${l.device}/${l.dtype} · ${l.dim}d · max_seq ${l.max_seq_length ?? "-"} · ${l.load_seconds}s`).join("<br>") : "로드 안 됨"],
    ["모델 정의 프롬프트", prompts.length ? prompts.map(p => `<code>${esc(p)}</code>`).join(" ") : '<span class="muted">로드 후 표시</span>'],
    ["Hub 다운로드(30일)", fmtNum(model.hub_downloads)],
    ["Hub 좋아요", fmtNum(model.hub_likes)],
    ["Hub 최종 수정", fmtDate(model.hub_last_modified)],
    ["Hub 동기화", fmtDate(model.hub_synced_at)],
    ["등록 경로", model.source],
  ].map(([k, v]) => `<div>${k}</div><div>${v}</div>`).join("");

  const job = model.download_job;
  $("#dl-progress").innerHTML = job ? `<div class="row"><div class="progress" style="flex:1"><div style="width:${pct(job.progress)}%"></div></div><span class="small muted">${esc(job.message)}</span></div>` : "";
  if (job) setTimeout(load, 1500);
}

$("#form").addEventListener("submit", async e => {
  e.preventDefault();
  const body = readForm();
  await busy(e.submitter, () => api(`/api/models/${MODEL_ID}`, { method: "PATCH", body }));
  toast("저장했습니다. 다음 로드부터 설정이 적용됩니다.", "ok");
  load();
});

$("#b-sync").onclick = async e => { await busy(e.target, () => api(`/api/models/${MODEL_ID}/sync`, { method: "POST" })); toast("Hub 정보 갱신", "ok"); fillForm(await api(`/api/models/${MODEL_ID}`)); load(); };
$("#b-download").onclick = async e => { await busy(e.target, () => api(`/api/models/${MODEL_ID}/download`, { method: "POST" })); load(); };
$("#b-load").onclick = async e => {
  const r = await busy(e.target, () => api(`/api/models/${MODEL_ID}/load`, { method: "POST" }));
  toast(`로드 완료: ${r.dim}차원 · ${r.load_seconds}s`, "ok"); load();
};
$("#b-load-mm").onclick = async e => {
  const r = await busy(e.target, () => api(`/api/models/${MODEL_ID}/load?multimodal=true`, { method: "POST" }));
  toast(`멀티모달 로드 완료 · ${r.load_seconds}s`, "ok"); load();
};
$("#b-unload").onclick = async e => { await busy(e.target, () => api(`/api/models/${MODEL_ID}/unload`, { method: "POST" })); load(); };
$("#b-delete").onclick = async e => {
  if (!confirm(`${model.hf_id} 을(를) 카탈로그에서 삭제할까요?`)) return;
  const cache = model.cached && confirm("로컬 캐시 파일도 함께 삭제할까요?");
  await busy(e.target, () => api(`/api/models/${MODEL_ID}?delete_cache=${cache}`, { method: "DELETE" }));
  location.href = "/models";
};

$("#qt-run").onclick = async e => {
  const documents = $("#qt-docs").value.split("\n").map(s => s.trim()).filter(Boolean);
  const r = await busy(e.target, () => api("/api/retrieve", { method: "POST", body: { model_ids: [MODEL_ID], query: $("#qt-query").value, documents, top_k: documents.length } }));
  const res = r.results[0];
  $("#qt-out").innerHTML = res.error ? `<div class="errbox">${esc(res.error)}</div>` :
    `<div class="small muted">${res.dim}차원 · ${res.seconds}s · 쿼리: ${appliedInfo(res.applied.query)} · 문서: ${appliedInfo(res.applied.document)}</div>${warningsHtml(res.warnings)}` +
    res.ranking.map(x => `<div class="rank-item"><div class="row between"><b>${x.score.toFixed(4)}</b></div><div class="bar" style="width:${Math.max(2, x.score * 100)}%"></div><div class="small">${esc(x.text)}</div></div>`).join("");
  load();
};

load();
