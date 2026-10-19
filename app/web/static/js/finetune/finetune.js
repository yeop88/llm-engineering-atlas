// finetune/finetune.html 화면 스크립트 (템플릿에서 옮김 — 화면 JS 는 static/js/<영역>/<화면>.js)
let fCols = [], fModels = [], fTimer = null;
const pctv = v => (v == null ? "-" : (v * 100).toFixed(1));

async function fInit() {
  fModels = (await getModels()).filter(m => m.kind === "embedding" && (m.modalities || ["text"]).every(x => x === "text"));
  fModels.sort((a, b) => (b.loaded_profiles?.length ? 2 : b.cached ? 1 : 0) - (a.loaded_profiles?.length ? 2 : a.cached ? 1 : 0));
  $("#f-base").innerHTML = fModels.map(m => `<option value="${m.id}">${m.loaded_profiles?.length ? "● " : m.cached ? "○ " : ""}${esc(m.name)} (${esc(m.params || "?")})${m.source === "finetuned" ? " · 파인튜닝" : ""}</option>`).join("");
  fCols = await api("/api/collections");
  $("#f-col").innerHTML = fCols.map(c => `<option value="${c.id}">${esc(c.name)}</option>`).join("") || '<option value="">컬렉션 없음</option>';
  await fColChanged();
  const s = await api("/api/llm/status");
  $("#f-llm-status").innerHTML = s.default.error ? '<span class="badge warn">LLM 미설정</span>' : `LLM: <span class="mono">${esc(s.default.model)}</span>`;
}
async function fColChanged() {
  if (!$("#f-col").value) return;
  const d = await api(`/api/collections/${$("#f-col").value}`);
  $("#f-cs").innerHTML = d.chunk_sets.filter(c => c.status === "ready").map(c => `<option value="${c.id}">${esc(c.name)} (${c.n_chunks})</option>`).join("") || '<option value="">청크 세트 없음</option>';
  const sets = (await api(`/api/collections/${d.id}/eval-sets`)).filter(s => s.status === "ready");
  $("#f-eval").innerHTML = '<option value="">비교하지 않음</option>' + sets.map(s => `<option value="${s.id}">#${s.id} ${esc(s.name)} (${s.n_items}문항)</option>`).join("");
  const manual = sets.find(s => s.method === "manual" || s.method === "import") || sets.find(s => s.method === "llm");
  if (manual) $("#f-eval").value = manual.id;
  fHint();
}
function fHint() {
  const m = $("#f-method").value;
  $("#f-llm-opts").hidden = m !== "llm";
  $("#f-hint").innerHTML = m === "llm"
    ? "지문마다 고른 유형 수만큼 질문을 만듭니다(지문 200개 × 3유형 ≈ 600쌍). 로컬 LLM 은 지문당 20~30초가 걸려 데이터 만들기가 가장 오래 걸립니다."
    : "LLM 없이 바로 만들 수 있지만, 질문이 원문 문장 그대로라 실제 질문보다 쉽습니다. 분야 용어에 익숙해지는 효과를 빠르게 볼 때 씁니다.";
}
$("#f-col").addEventListener("change", fColChanged);
$("#f-method").addEventListener("change", fHint);

$("#f-run").onclick = async e => {
  const styles = [...document.querySelectorAll('input[name="f-style"]:checked')].map(x => x.value);
  const base = fModels.find(m => String(m.id) === $("#f-base").value);
  const body = {
    name: $("#f-name").value.trim(), base_model_id: +$("#f-base").value, collection_id: +$("#f-col").value, chunk_set_id: +$("#f-cs").value,
    data_method: $("#f-method").value, n_passages: +$("#f-n").value, styles: styles.length ? styles : ["fact"],
    eval_set_id: +$("#f-eval").value || null, epochs: +$("#f-epochs").value, batch_size: +$("#f-batch").value, learning_rate: parseFloat($("#f-lr").value),
    max_seq_length: +$("#f-seq").value || null, mini_batch_size: +$("#f-mini").value || null, eval_ratio: +$("#f-evr").value || 0,
    matryoshka_dims: $("#f-mrl").checked ? (base?.mrl_dims || []) : [],
  };
  if (!body.chunk_set_id) return toast("청크 세트가 필요합니다", "err");
  await busy(e.target, () => api("/api/finetune", { method: "POST", body }));
  toast("학습을 시작했습니다", "ok"); fLoad();
};

async function fLoad() {
  const rows = await api("/api/finetune");
  const st = r => ({ done: '<span class="badge ok">완료</span>', error: `<span class="badge err" title="${esc(r.error || "")}">오류</span>`, cancelled: '<span class="badge">취소</span>',
    running: `<span class="badge warn">진행 중</span>${r.job ? `<div class="progress" style="margin-top:4px;min-width:120px"><div style="width:${pct(r.job.progress)}%"></div></div><div class="small muted">${esc(r.job.message)}</div>` : ""}`,
    pending: '<span class="badge warn">대기</span>' })[r.status] || esc(r.status);
  $("#f-rows").innerHTML = rows.map(r => {
    const t = r.metrics?.train || {}, c = r.metrics?.comparison?.dense;
    return `<tr><td>${r.id}</td><td><b>${esc(r.name)}</b></td><td class="small mono">${esc(r.base_hf_id.split(/[\\/]/).pop())}</td><td>${st(r)}</td>
      <td class="num">${r.data_stats?.pairs ?? "-"}</td><td class="small nowrap">${t.first_loss != null ? `${t.first_loss.toFixed(3)} → ${t.final_loss.toFixed(3)}` : "-"}</td>
      <td class="small nowrap">${c ? `${pctv(c.before["ndcg@10"])} → <b>${pctv(c.after["ndcg@10"])}</b> <span class="badge ${c.paired.significant ? (c.paired.diff > 0 ? "ok" : "err") : ""}">${(c.paired.diff * 100).toFixed(1)}%p${c.paired.significant ? "" : " 불확실"}</span>` : "-"}</td>
      <td class="small nowrap">${fmtDate(r.created_at)}</td>
      <td class="right nowrap"><button class="btn sm" onclick="fShow(${r.id})">상세</button>${r.job ? `<button class="btn sm danger" onclick="fCancel('${r.job.id}')">취소</button>` : `<button class="btn sm danger" onclick="fDelete(${r.id})">삭제</button>`}</td></tr>`;
  }).join("") || '<tr><td colspan="9" class="empty">아직 학습한 모델이 없습니다</td></tr>';
  clearTimeout(fTimer);
  if (rows.some(r => r.status === "running" || r.status === "pending")) fTimer = setTimeout(fLoad, 3000);
}
$("#f-refresh").onclick = fLoad;
async function fCancel(jobId) { if (confirm("학습을 취소할까요?")) { await api(`/api/jobs/${jobId}/cancel`, { method: "POST" }); fLoad(); } }
async function fDelete(id) {
  const withModel = confirm(`실행 #${id} 기록을 삭제합니다.\n학습한 모델(카탈로그 항목과 파일)도 함께 지울까요? [확인 = 함께 삭제 / 취소 = 기록만 삭제]`);
  await api(`/api/finetune/${id}?delete_model=${withModel}`, { method: "DELETE" }); toast("삭제했습니다", "ok"); $("#f-detail").innerHTML = ""; fLoad();
}

// 손실 곡선 (SVG, 외부 라이브러리 없이)
function lossSvg(log) {
  const pts = log.filter(e => e.loss != null);
  if (pts.length < 2) return '<div class="small muted">손실 기록이 부족합니다</div>';
  const W = 560, H = 160, P = 30, xs = pts.map(p => p.step), ys = pts.map(p => p.loss);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = 0, y1 = Math.max(...ys) * 1.05;
  const X = v => P + (v - x0) / Math.max(1, x1 - x0) * (W - P - 8), Y = v => H - 18 - (v - y0) / (y1 - y0) * (H - 28);
  const path = pts.map((p, i) => `${i ? "L" : "M"}${X(p.step).toFixed(1)},${Y(p.loss).toFixed(1)}`).join("");
  const ev = log.filter(e => e.eval_loss != null).map(e => `<circle cx="${X(e.step)}" cy="${Y(e.eval_loss)}" r="4" fill="var(--warn)"><title>검증 손실 ${e.eval_loss}</title></circle>`).join("");
  return `<svg viewBox="0 0 ${W} ${H}" style="width:100%;max-width:${W}px" role="img" aria-label="학습 손실 곡선">
    <line x1="${P}" y1="${H - 18}" x2="${W}" y2="${H - 18}" stroke="var(--chart-axis)"/><line x1="${P}" y1="6" x2="${P}" y2="${H - 18}" stroke="var(--chart-axis)"/>
    <text x="${P - 4}" y="${Y(y1) + 4}" font-size="10" text-anchor="end" fill="var(--muted)">${y1.toFixed(2)}</text><text x="${P - 4}" y="${H - 18}" font-size="10" text-anchor="end" fill="var(--muted)">0</text>
    <text x="${W - 4}" y="${H - 4}" font-size="10" text-anchor="end" fill="var(--muted)">단계 ${x1}</text>
    <path d="${path}" fill="none" stroke="var(--accent)" stroke-width="2"/>${ev}</svg>`;
}

async function fShow(id) {
  const r = await api(`/api/finetune/${id}`);
  const d = r.data_stats || {}, t = r.metrics?.train || {}, cmp = r.metrics?.comparison;
  const card = await (await fetch(`/api/finetune/${id}/card`)).text();
  const cmpRow = (name, p) => p ? `<tr><td>${name}</td><td class="num">${pctv(p.before["ndcg@10"])} → <b>${pctv(p.after["ndcg@10"])}</b></td><td class="num">${pctv(p.before["hit@1"])} → ${pctv(p.after["hit@1"])}</td><td class="num">${pctv(p.before["hit@5"])} → ${pctv(p.after["hit@5"])}</td>
    <td class="small nowrap">${(p.paired.diff * 100).toFixed(1)}%p [${(p.paired.ci[0] * 100).toFixed(1)}, ${(p.paired.ci[1] * 100).toFixed(1)}] <span class="badge ${p.paired.significant ? (p.paired.diff > 0 ? "ok" : "err") : ""}">${p.paired.significant ? "유의한 차이" : "차이 불확실"}</span></td></tr>` : "";
  const changed = (cmp?.queries || []).filter(q => q.ranks["원래 모델 · 의미"] !== q.ranks["학습한 모델 · 의미"]);
  $("#f-detail").innerHTML = `<div class="card stack">
    <div class="row between"><h2>실행 #${r.id} · ${esc(r.name)}</h2>${r.output_model_id ? `<a class="btn sm" href="/models/${r.output_model_id}">학습한 모델 보기</a>` : ""}</div>
    ${r.error ? `<div class="errbox">${esc(r.error)}</div>` : ""}
    <div class="grid cols-2">
      <div class="stack"><h3>학습 데이터</h3><div class="small">${d.method === "llm" ? `LLM 질문 생성 (${esc(d.llm?.model || "")})` : "ICT"} · 지문 ${d.passages ?? "-"}개 → 학습 쌍 <b>${d.pairs ?? "-"}</b>개 · 문서 ${d.documents ?? "-"}개 · 평가 세트 근거로 제외한 지문 ${d.excluded_for_eval ?? 0}개</div>
        ${(d.examples || []).slice(0, 3).map(x => `<div class="small" style="border-left:3px solid var(--border);padding-left:8px"><b>Q</b> ${esc(x.anchor)}<div class="muted">${esc(x.positive)}…</div></div>`).join("")}</div>
      <div class="stack"><h3>학습</h3><div class="small">${t.steps ?? "-"}단계 · ${t.seconds ?? "-"}초 · ${esc(t.device || "")} · 손실 ${t.first_loss ?? "-"} → ${t.final_loss ?? "-"}${t.eval_loss != null ? ` · 검증 ${t.eval_loss}` : ""}</div>${lossSvg(r.log || [])}</div>
    </div>
    ${cmp && !cmp.skipped ? `<h3>학습 전후 비교 · ${esc(cmp.eval_set.name)} (${cmp.eval_set.n}문항)</h3>
      <table><tr><th>검색</th><th class="num">nDCG@10</th><th class="num">Hit@1</th><th class="num">Hit@5</th><th>학습 전 대비 (95% 구간)</th></tr>${cmpRow("의미", cmp.dense)}${cmpRow("하이브리드", cmp.hybrid)}</table>
      ${changed.length ? `<details><summary class="small">의미 검색 순위가 바뀐 질문 ${changed.length}개</summary><table>${changed.map(q => `<tr><td class="small">${esc(q.query)}</td><td class="num mono">${q.ranks["원래 모델 · 의미"] ?? "✗"} → ${q.ranks["학습한 모델 · 의미"] ?? "✗"}</td></tr>`).join("")}</table></details>` : ""}` : ""}
    <details><summary class="small">기록 (모델 카드 · 학습한 모델 폴더의 README.md)</summary><pre class="small" style="white-space:pre-wrap">${esc(card)}</pre></details>
  </div>`;
  $("#f-detail").scrollIntoView({ behavior: "smooth" });
}
fInit(); fLoad();
