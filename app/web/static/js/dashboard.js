// 대시보드: 연결 상태 · 다음에 할 일 · 최근 실험 · 작업 · 로드된 모델 · 메모리
const KIND_LABEL = {
  rag_answer: "답변", rag_answer_eval: "답변 평가", rag_eval: "검색 평가", rag_search: "검색 비교", flow: "연결 실행", flow_eval: "연결 비교",
  benchmark: "벤치마크", rerank_eval: "리랭킹", routing_eval: "라우팅", quant_llm: "양자화(LLM)", quant_vectors: "양자화(벡터)", rl_eval: "강화학습",
  distill_llm_data: "증류 데이터", agent: "에이전트", verify_agreement: "검증 보정", multimodal: "멀티모달", similarity: "유사도", embed: "임베딩",
  retrieval: "검색", projection: "임베딩 지도", compat: "호환성 점검",
};
const kindLabel = k => KIND_LABEL[k] || (k.startsWith("app_") ? `의미 응용 · ${k.slice(4)}` : k);
const firstLine = s => String(s || "").split("\n")[0].slice(0, 140);

let llmOk = null;
async function health() {
  const [llm, stores, sys, models] = await Promise.all([
    api("/api/llm/status"), api("/api/vector-stores").catch(() => []), api("/api/system"), getModels(true),
  ]);
  // LLM: 설정만 보면 서버가 꺼져 있어도 '정상'으로 보이므로, 모델 목록을 실제로 받아 본다
  if (llm.default.error) { llmOk = false; $("#h-llm").innerHTML = html`<span class="badge warn">미설정</span>`; $("#h-llm-sub").innerHTML = html`${llm.default.error} · <a href="/settings/llm">LLM 연결</a>`; }
  else {
    llmOk = await api("/api/llm/models").then(() => true, () => false);
    $("#h-llm").innerHTML = llmOk ? html`<span class="badge ok">연결됨</span>` : html`<span class="badge err">응답 없음</span>`;
    $("#h-llm-sub").innerHTML = llmOk ? html`<span class="mono">${llm.default.model}</span>`
      : html`${llm.default.base_url || llm.default.provider} 에 닿지 않습니다 — 로컬 서버(llama-server)를 켜거나 <a href="/settings/llm">LLM 연결</a>을 확인하세요.`;
  }
  const okStores = stores.filter(s => s.ok), def = stores.find(s => s.default);
  $("#h-vs").innerHTML = def?.ok ? html`<span class="badge ok">${def.label}</span>` : html`<span class="badge err">${def?.label || "없음"} 꺼짐</span>`;
  $("#h-vs-sub").textContent = `${okStores.length}/${stores.length} 사용 가능` + (stores.some(s => !s.ok) ? ` · 꺼진 것: ${stores.filter(s => !s.ok).map(s => s.label).join(", ")} (docker compose up)` : "");
  const cached = models.filter(m => m.cached);
  $("#h-models").textContent = `${sys.loaded.length} / ${cached.length}`;
  $("#h-models-sub").innerHTML = html`로드됨 / 받아 둠 · 카탈로그 ${models.length}개 · <a href="/embedding/models">모델 →</a>`;
  $("#h-device").textContent = sys.device.toUpperCase();
  $("#h-device-sub").textContent = `${sys.dtype}${sys.cuda ? ` · ${sys.cuda.name}` : ""} · 메모리 ${sys.memory ? `${sys.memory.available_gb}/${sys.memory.total_gb} GB 여유` : "-"}`;

  $("#loaded").innerHTML = sys.loaded.length
    ? html`<table><tr><th>모델</th><th>프로필</th><th class="num">차원</th><th class="num">로드</th><th></th></tr>${sys.loaded.map(l => html`<tr><td>${l.hf_id}</td><td>${l.profile}</td><td class="num">${l.dim}</td><td class="num">${l.load_seconds}s</td>
      <td class="right"><button class="btn sm" data-unload="${l.model_id}">언로드</button></td></tr>`)}</table>`
    : html`<div class="empty">로드된 모델이 없습니다</div>`;
  const mem = sys.memory ? `${sys.memory.available_gb} / ${sys.memory.total_gb} GB 사용 가능 · 프로세스 ${sys.memory.process_gb} GB` : "-";
  $("#system").innerHTML = html`${[
    ["Python", sys.python], ["플랫폼", sys.platform], ["CPU 코어", `${sys.cpu_count} (torch threads ${sys.torch_threads})`], ["메모리", mem],
    ["HF_TOKEN", sys.hf_token_set ? "설정됨" : "미설정 (gated 모델 다운로드 불가)"], ...Object.entries(sys.packages),
  ].map(([k, v]) => html`<div>${k}</div><div class="mono">${v}</div>`)}`;
  return { cached, sys };
}

// 다음에 할 일: 처음 쓰는 순서(README '처음 써보기')를 지금 상태로 체크 — 끝난 단계는 접히듯 흐리게
async function todo({ cached }) {
  const [cols, summary] = await Promise.all([api("/api/collections"), api("/api/runs/summary")]);
  const k = summary.by_kind;
  const steps = [
    [cached.length > 0, "임베딩 모델 받기", "카탈로그에서 한국어 모델(예: KURE)을 받아 로드", "/embedding/models"],
    [llmOk === true, "LLM 연결", "로컬 llama-server 또는 Claude API — 답변 · 평가 질문 생성에 필요", "/settings/llm"],
    [cols.length > 0, "컬렉션 만들기", "문서를 올리거나 공개 자료(법령 · 판례) 가져오기", "/rag/collections"],
    [cols.some(c => c.n_indexes > 0), "벡터 인덱스 만들기", "컬렉션 › ② 청크 세트 · ③ 벡터 인덱스", cols[0] ? `/rag/collections/${cols[0].id}#t-index` : "/rag/collections"],
    [(k.rag_eval || 0) > 0, "검색 평가", "평가 세트를 만들고 검색 조합을 숫자로 비교", cols[0] ? `/rag/collections/${cols[0].id}#t-eval` : "/rag/collections"],
    [(k.rag_answer || 0) + (k.rag_answer_eval || 0) > 0, "답변 생성", "근거 인용 답변 · 문장별 검증", "/rag/answer"],
    [(k.flow_eval || 0) > 0, "연결 비교", "단계를 이어 붙인 경로끼리 품질 · 지연 비교", "/maps/llm#flow"],
  ];
  const done = steps.filter(s => s[0]).length;
  $("#todo-sum").textContent = `${done} / ${steps.length} 완료`;
  const next = steps.findIndex(s => !s[0]);
  $("#todo").innerHTML = html`${steps.map(([ok, title, desc, href], i) => html`<li class="${ok ? "done" : i === next ? "next" : ""}">
    <a href="${href}"><b>${title}</b></a> ${ok ? html`<span class="badge ok">완료</span>` : i === next ? html`<span class="badge">다음</span>` : ""}
    <div class="small muted">${desc}</div></li>`)}`;
}

async function activity() {
  const [runs, jobs] = await Promise.all([api("/api/runs?limit=8"), api("/api/jobs?limit=6")]);
  $("#runs").innerHTML = runs.length
    ? html`<table><tr><th>종류</th><th>실험</th><th>시각</th></tr>${runs.map(r => html`<tr><td class="nowrap"><span class="badge muted">${kindLabel(r.kind)}</span></td>
        <td><a href="/history#run-${r.id}">${r.title}</a></td><td class="nowrap small muted">${fmtDate(r.created_at)}</td></tr>`)}</table>`
    : html`<div class="empty">아직 실험이 없습니다<div class="empty-act"><a class="btn" href="/rag/answer">답변 생성 해 보기</a></div></div>`;
  const ST = { pending: ["대기", "warn"], running: ["실행 중", "warn"], done: ["완료", "ok"], error: ["오류", "err"], cancelled: ["취소", "muted"], interrupted: ["중단됨(재시작)", "muted"] };
  $("#jobs").innerHTML = jobs.length
    ? html`${jobs.map(j => ["pending", "running"].includes(j.status) ? html`<div class="job-row">${ui.jobProgress(j)}</div>` : html`<div class="job-row">
        <div class="row between small"><span>${j.title}</span><span class="badge ${ST[j.status]?.[1] ?? ""}">${ST[j.status]?.[0] ?? j.status}</span></div>
        ${j.error ? html`<details class="small"><summary class="errline">${firstLine(j.error)}</summary><pre class="pre">${j.error}</pre></details>` : ""}</div>`)}`
    : html`<div class="empty">작업 없음</div>`;
}

let lastMem = null;
async function memory() {
  if (typeof Chart === "undefined") return; // CDN 실패 시 차트만 생략
  const metrics = await api("/api/system/metrics");
  lastMem = metrics.samples;
  if (!lastMem.length) return;
  const s = lastMem[lastMem.length - 1];
  $("#mem-now").textContent = `프로세스 ${s.process_gb.toFixed(2)} GB · 시스템 ${s.used_gb} / ${s.total_gb} GB`;
  BenchCharts.renderMemory($("#ch-mem"), lastMem);
}
window.addEventListener("themechange", () => { if (lastMem?.length) BenchCharts.renderMemory($("#ch-mem"), lastMem); });

async function refresh(first = false) {
  memory().catch(() => {});
  activity().catch(e => ui.error($("#runs"), e));
  const st = await health().catch(e => { toast(e.message, "err"); return null; });
  if (st && first) todo(st).catch(e => ui.error($("#todo"), e));
}
document.addEventListener("click", async e => {
  const b = e.target.closest("[data-unload]");
  if (b) { await busy(b, () => api(`/api/models/${b.dataset.unload}/unload`, { method: "POST" })); refresh(); }
});
$("#unload-all").onclick = async e => {
  if (!(await ui.confirm("메모리에 올린 모델을 모두 내립니다. 다음에 쓸 때 다시 로드합니다.", { ok: "모두 언로드" }))) return;
  await busy(e.target, () => api("/api/loaded/unload-all", { method: "POST" })); refresh();
};
refresh(true);
setInterval(refresh, 10000);
