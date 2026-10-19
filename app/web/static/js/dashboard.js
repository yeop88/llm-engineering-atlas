// dashboard.html 화면 스크립트 (템플릿에서 옮김 — 화면 JS 는 static/js/<영역>/<화면>.js)
let latestBenchId = null;
async function refreshCharts() {
  if (typeof Chart === "undefined") return; // CDN 실패 시 차트만 생략
  const [metrics, runs] = await Promise.all([api("/api/system/metrics"), api("/api/runs?kind=benchmark&limit=1")]);
  if (metrics.samples.length) {
    const s = metrics.samples[metrics.samples.length - 1];
    $("#mem-now").textContent = `프로세스 ${s.process_gb.toFixed(2)} GB · 시스템 ${s.used_gb} / ${s.total_gb} GB`;
    BenchCharts.renderMemory($("#ch-mem"), metrics.samples);
  }
  const run = runs[0];
  if (!run) { latestBenchId = null; $("#bench-box").hidden = true; $("#bench-sub").textContent = "아직 실행한 벤치마크가 없습니다."; return; }
  if (run.id === latestBenchId) return; // 바뀐 경우에만 다시 그림
  latestBenchId = run.id;
  const detail = await api(`/api/runs/${run.id}`);
  const res = detail.result;
  $("#bench-sub").textContent = `${res.dataset.title || res.dataset.name} · run #${run.id} · ${fmtDate(run.created_at)} · ${res.primary_metric}${res.truncate_dim ? ` · ${res.truncate_dim}차원` : ""}`;
  $("#bench-link").onclick = () => sessionStorage.setItem("run", run.id);
  $("#bench-box").hidden = false;
  BenchCharts.renderLatestBench($("#ch-bench"), res);
}

async function refresh() {
  refreshCharts().catch(() => {});
  const [models, sys, jobs, runs] = await Promise.all([getModels(true), api("/api/system"), api("/api/jobs"), api("/api/runs?limit=6")]);
  $("#st-total").textContent = models.length;
  const cached = models.filter(m => m.cached);
  $("#st-cached").textContent = cached.length;
  $("#st-cache-size").textContent = fmtBytes(cached.reduce((s, m) => s + m.cache_size_bytes, 0));
  $("#st-loaded").textContent = sys.loaded.length;
  $("#st-max").textContent = `최대 ${sys.max_loaded_models}개 (LRU)`;
  $("#st-device").textContent = sys.device.toUpperCase();
  $("#st-dtype").textContent = `dtype ${sys.dtype}` + (sys.cuda ? ` · ${sys.cuda.name}` : "");

  renderRecommendations(models);

  $("#loaded").innerHTML = sys.loaded.length ? `<table><tr><th>모델</th><th>프로필</th><th class="num">차원</th><th class="num">로드</th><th></th></tr>` +
    sys.loaded.map(l => `<tr><td>${esc(l.hf_id)}</td><td>${l.profile}</td><td class="num">${l.dim}</td><td class="num">${l.load_seconds}s</td>
      <td class="right"><button class="btn sm" onclick="unload(${l.model_id})">언로드</button></td></tr>`).join("") + "</table>"
    : '<div class="empty">로드된 모델이 없습니다</div>';

  $("#jobs").innerHTML = jobs.slice(0, 6).map(j => `
    <div class="row between small" style="padding:4px 0">
      <span>${esc(j.title)}</span>
      <span class="row"><span class="badge ${j.status === "done" ? "ok" : j.status === "error" ? "err" : "warn"}">${({ pending: "대기", running: "실행 중", done: "완료", error: "오류", cancelled: "취소", interrupted: "중단됨(재시작)" })[j.status] || j.status}</span>
      ${["pending", "running"].includes(j.status) ? `<div class="progress"><div style="width:${pct(j.progress)}%"></div></div>` : ""}</span>
    </div>${j.error ? `<div class="errbox">${esc(j.error)}</div>` : j.message ? `<div class="small muted">${esc(j.message)}</div>` : ""}`).join("") || '<div class="empty">작업 없음</div>';

  $("#runs").innerHTML = runs.map(r => `<div class="small" style="padding:3px 0"><span class="badge muted">${r.kind}</span> ${esc(r.title)} <span class="muted">· ${fmtDate(r.created_at)}</span></div>`).join("") || '<div class="empty">아직 없음</div>';

  const mem = sys.memory ? `${sys.memory.available_gb} / ${sys.memory.total_gb} GB 사용 가능 · 프로세스 ${sys.memory.process_gb} GB` : "-";
  $("#system").innerHTML = [
    ["Python", sys.python], ["플랫폼", sys.platform], ["CPU 코어", `${sys.cpu_count} (torch threads ${sys.torch_threads})`], ["메모리", mem],
    ["HF_TOKEN", sys.hf_token_set ? "설정됨" : "미설정 (gated 모델 다운로드 불가)"],
    ...Object.entries(sys.packages),
  ].map(([k, v]) => `<div>${esc(k)}</div><div class="mono">${esc(v)}</div>`).join("");
}
// 용도별 추천: 카탈로그 태그/메타데이터로 동적으로 분류하므로 모델을 추가해도 자동 반영된다.
const byDateDesc = (a, b) => (b.release_date || "").localeCompare(a.release_date || "");
const ready = m => (m.loaded_profiles.length ? 2 : m.cached ? 1 : 0);
const paramsB = m => { const x = /([\d.]+)\s*B\b/.exec(m.params || ""); return x ? Number(x[1]) : 0; };  // "8.0B" → 8, "568M" → 0
const REC_GROUPS = [
  { key: "ready", label: "바로 사용", desc: "이미 다운로드·로드되어 바로 테스트할 수 있는 모델입니다.",
    pick: ms => ms.filter(m => m.cached || m.loaded_profiles.length).sort((a, b) => ready(b) - ready(a) || byDateDesc(a, b)), more: "/models?status=cached" },
  { key: "recent", label: "최근 공개", desc: `공개일 기준 최근 ${RECENT_DAYS}일 이내 모델입니다.`,
    pick: ms => ms.filter(m => isRecent(m)).sort(byDateDesc), more: "/models?sort=release_date" },
  { key: "light", label: "경량 · CPU", desc: "CPU·노트북에서도 빠르게 돌아가는 작은 모델입니다. 동작 확인용으로 먼저 써 보세요.",
    pick: ms => ms.filter(m => m.tags.some(t => ["tiny", "on-device", "baseline"].includes(t))).sort(byDateDesc), more: "/models?tag=tiny" },
  { key: "korean", label: "한국어", desc: "한국어 특화 모델과 한국어 검색 품질이 검증된 다국어 모델입니다.",
    pick: ms => ms.filter(m => m.tags.includes("korean") || /\bko\b/.test(m.languages) || ["google/embeddinggemma-2", "Qwen/Qwen3-Embedding-0.6B", "BAAI/bge-m3"].includes(m.hf_id)).sort((a, b) => Number(b.tags.includes("korean")) - Number(a.tags.includes("korean")) || byDateDesc(a, b)), more: "/models?tag=korean" },
  { key: "multimodal", label: "멀티모달", desc: "텍스트와 이미지(일부는 오디오·비디오)를 같은 벡터 공간에 임베딩합니다.",
    pick: ms => ms.filter(m => m.modalities.some(x => x !== "text")).sort(byDateDesc), more: "/models?modality=image" },
  { key: "top", label: "고성능 · GPU", desc: "리더보드 상위권 대형 모델입니다. CPU에서는 매우 느리고 RAM을 많이 씁니다.",
    pick: ms => ms.filter(m => m.tags.some(t => t.startsWith("top-")) && paramsB(m) >= 1).sort(byDateDesc), more: "/models?sort=downloads" },
  { key: "reranker", label: "리랭커", desc: "검색 후보를 질의와 함께 다시 읽어 순위를 매기는 모델입니다. 문서 검색 화면에서 하이브리드 검색 뒤에 붙여 씁니다.",
    pick: ms => ms.filter(m => m.kind === "reranker").sort((a, b) => ready(b) - ready(a) || paramsB(a) - paramsB(b)), more: "/models?kind=reranker" },
];
let recKey = (() => { try { return localStorage.getItem("rec-tab"); } catch { return null; } })() || "ready";

function recAction(m) {
  if (m.loaded_profiles.length) return `<a class="btn sm primary" href="/playground?model=${m.id}">테스트</a>`;
  if (m.download_job) return `<span class="badge warn">다운로드 ${pct(m.download_job.progress)}%</span>`;
  if (m.cached) return `<button class="btn sm" onclick="recDo(${m.id}, 'load', this)">로드</button>`;
  return `<button class="btn sm" onclick="recDo(${m.id}, 'download', this)">다운로드</button>`;
}
async function recDo(id, action, btn) {
  await busy(btn, () => api(`/api/models/${id}/${action}`, { method: "POST" }));
  toast(action === "load" ? "로드 완료" : "다운로드를 시작했습니다", "ok");
  refresh();
}

function renderRecommendations(all) {
  const models = all.filter(m => m.kind !== "reranker");
  const groups = REC_GROUPS.map(g => ({ ...g, items: g.key === "reranker" ? g.pick(all) : g.pick(models) }));
  if (!groups.find(g => g.key === recKey)?.items.length) recKey = groups.find(g => g.items.length)?.key || "light";
  $("#rec-tabs").innerHTML = groups.map(g =>
    `<button data-key="${g.key}" class="${g.key === recKey ? "active" : ""}">${g.label} <span class="muted small">${g.items.length}</span></button>`).join("");
  const g = groups.find(x => x.key === recKey);
  $("#rec-desc").textContent = g.desc;
  $("#rec-more").href = g.more;
  $("#rec-list").innerHTML = g.items.slice(0, 8).map(m => `
    <div class="row between" style="flex-wrap:nowrap">
      <div style="min-width:0"><a href="/models/${m.id}"><b>${esc(m.name)}</b></a> ${modelBadges(m)}<br>
        <span class="small muted">${esc(m.provider)} · ${esc(m.release_date)} · ${esc(m.params)} · ${m.dim ?? "?"}d · ${esc(m.license)} · ${esc(m.languages)}</span></div>
      <div class="nowrap">${recAction(m)}</div>
    </div>`).join("") || '<div class="empty">해당 모델이 없습니다</div>';
}
$("#rec-tabs").addEventListener("click", e => {
  const btn = e.target.closest("button[data-key]");
  if (!btn) return;
  recKey = btn.dataset.key;
  try { localStorage.setItem("rec-tab", recKey); } catch {}
  renderRecommendations(_modelsCache);
});

async function unload(id) { await api(`/api/models/${id}/unload`, { method: "POST" }); refresh(); }
$("#unload-all").onclick = async () => { await api("/api/loaded/unload-all", { method: "POST" }); refresh(); };
refresh();
setInterval(refresh, 5000);
