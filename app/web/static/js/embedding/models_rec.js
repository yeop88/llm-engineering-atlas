// 용도별 추천 모델 (예전 대시보드에서 옮김 — 임베딩 카탈로그 정보는 1 임베딩 › 모델 화면에 모은다)
// 카탈로그 태그/메타데이터로 동적으로 분류하므로 모델을 추가해도 자동 반영된다.
const byDateDesc = (a, b) => (b.release_date || "").localeCompare(a.release_date || "");
const ready = m => (m.loaded_profiles.length ? 2 : m.cached ? 1 : 0);
const paramsB = m => { const x = /([\d.]+)\s*B\b/.exec(m.params || ""); return x ? Number(x[1]) : 0; };  // "8.0B" → 8, "568M" → 0
const REC_GROUPS = [
  { key: "ready", label: "바로 사용", desc: "이미 다운로드·로드되어 바로 테스트할 수 있는 모델입니다.",
    pick: ms => ms.filter(m => m.cached || m.loaded_profiles.length).sort((a, b) => ready(b) - ready(a) || byDateDesc(a, b)), more: "/embedding/models?status=cached" },
  { key: "recent", label: "최근 공개", desc: `공개일 기준 최근 ${RECENT_DAYS}일 이내 모델입니다.`,
    pick: ms => ms.filter(m => isRecent(m)).sort(byDateDesc), more: "/embedding/models?sort=release_date" },
  { key: "light", label: "경량 · CPU", desc: "CPU·노트북에서도 빠르게 돌아가는 작은 모델입니다. 동작 확인용으로 먼저 써 보세요.",
    pick: ms => ms.filter(m => m.tags.some(t => ["tiny", "on-device", "baseline"].includes(t))).sort(byDateDesc), more: "/embedding/models?tag=tiny" },
  { key: "korean", label: "한국어", desc: "한국어 특화 모델과 한국어 검색 품질이 검증된 다국어 모델입니다.",
    pick: ms => ms.filter(m => m.tags.includes("korean") || /\bko\b/.test(m.languages) || ["google/embeddinggemma-2", "Qwen/Qwen3-Embedding-0.6B", "BAAI/bge-m3"].includes(m.hf_id)).sort((a, b) => Number(b.tags.includes("korean")) - Number(a.tags.includes("korean")) || byDateDesc(a, b)), more: "/embedding/models?tag=korean" },
  { key: "multimodal", label: "멀티모달", desc: "텍스트와 이미지(일부는 오디오·비디오)를 같은 벡터 공간에 임베딩합니다.",
    pick: ms => ms.filter(m => m.modalities.some(x => x !== "text")).sort(byDateDesc), more: "/embedding/models?modality=image" },
  { key: "top", label: "고성능 · GPU", desc: "리더보드 상위권 대형 모델입니다. CPU에서는 매우 느리고 RAM을 많이 씁니다.",
    pick: ms => ms.filter(m => m.tags.some(t => t.startsWith("top-")) && paramsB(m) >= 1).sort(byDateDesc), more: "/embedding/models?sort=downloads" },
  { key: "reranker", label: "리랭커", desc: "검색 후보를 질의와 함께 다시 읽어 순위를 매기는 모델입니다. 문서 검색 화면에서 하이브리드 검색 뒤에 붙여 씁니다.",
    pick: ms => ms.filter(m => m.kind === "reranker").sort((a, b) => ready(b) - ready(a) || paramsB(a) - paramsB(b)), more: "/embedding/models?kind=reranker" },
];
let recKey = localGet("rec-tab") || "ready";

function recAction(m) {
  if (m.loaded_profiles.length) return `<a class="btn sm primary" href="/embedding/playground?model=${m.id}">테스트</a>`;
  if (m.download_job) return `<span class="badge warn">다운로드 ${pct(m.download_job.progress)}%</span>`;
  if (m.cached) return `<button class="btn sm" onclick="recDo(${m.id}, 'load', this)">로드</button>`;
  return `<button class="btn sm" onclick="recDo(${m.id}, 'download', this)">다운로드</button>`;
}
async function recDo(id, action, btn) {
  await busy(btn, () => api(`/api/models/${id}/${action}`, { method: "POST" }));
  toast(action === "load" ? "로드 완료" : "다운로드를 시작했습니다", "ok");
  renderRecommendations(await getModels(true));
  if (typeof load === "function") load();  // 아래 카탈로그 표(embedding/models.js)도 새 상태로
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
    <div class="row between nowrap-row">
      <div class="min-0"><a href="/embedding/models/${m.id}"><b>${esc(m.name)}</b></a> ${modelBadges(m)}<br>
        <span class="small muted">${esc(m.provider)} · ${esc(m.release_date)} · ${esc(m.params)} · ${m.dim ?? "?"}d · ${esc(m.license)} · ${esc(m.languages)}</span></div>
      <div class="nowrap">${recAction(m)}</div>
    </div>`).join("") || '<div class="empty">해당 모델이 없습니다</div>';
}
$("#rec-tabs").addEventListener("click", e => {
  const btn = e.target.closest("button[data-key]");
  if (!btn) return;
  recKey = btn.dataset.key;
  localSet("rec-tab", recKey);
  renderRecommendations(_modelsCache);
});
getModels().then(renderRecommendations).catch(e => ui.error($("#rec-list"), e));
