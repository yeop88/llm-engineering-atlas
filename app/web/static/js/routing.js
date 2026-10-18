// 6 라우팅 테스트: 경로 설정 · 질문 하나 판단 · 평가 세트로 라우터 비교(표 + 비용-품질 그림)
let rCol = null;
const R_LABEL = { always_easy: "항상 빠른 경로", always_hard: "항상 전체 경로", rule: "규칙", confidence: "검색 확신도", llm: "LLM 판단", oracle: "오라클 (상한)" };
// 색은 실제 라우터 셋에만 쓴다(모든 쌍 색각이상 검증 통과 조합). 점끼리 어디서나 이웃할 수 있어 5색 이상은 구분이 안 됐다.
// 기준선 두 개 · 오라클은 '참고점'이라 회색 모양으로 구분한다: ■ 항상 빠른, ◆ 항상 전체, ○ 오라클. 모든 점에 이름표를 붙인다.
const R_COLOR = { rule: 1, confidence: 2, llm: 3 };
const R_SHAPE = { always_easy: "square", always_hard: "diamond", oracle: "ring" };
function rMark(k, x, y) {
  if (R_COLOR[k]) return `<circle cx="${x}" cy="${y}" r="6" fill="var(--series-${R_COLOR[k]})" stroke="var(--panel)" stroke-width="2"/>`;
  if (R_SHAPE[k] === "square") return `<rect x="${x - 5.5}" y="${y - 5.5}" width="11" height="11" rx="2" fill="var(--muted)"/>`;
  if (R_SHAPE[k] === "diamond") return `<path d="M${x},${y - 7} L${x + 7},${y} L${x},${y + 7} L${x - 7},${y} Z" fill="var(--muted)"/>`;
  return `<circle cx="${x}" cy="${y}" r="6" fill="none" stroke="var(--text)" stroke-width="2"/>`;
}
function rKey(k) {
  return `<svg width="14" height="14" viewBox="0 0 14 14" style="vertical-align:-2px;margin-right:4px">${rMark(k, 7, 7)}</svg>`;
}
const PATH = { easy: '<span class="badge ok">쉬움 → 빠른 경로</span>', hard: '<span class="badge warn">어려움 → 전체 경로</span>' };

async function rLoad() {
  const cols = await api("/api/collections");
  $("#r-col").innerHTML = cols.map(c => `<option value="${c.id}">${esc(c.name)}</option>`).join("") || '<option value="">컬렉션 없음</option>';
  const saved = localGet("routing-col");
  if (saved && cols.some(c => String(c.id) === saved)) $("#r-col").value = saved;
  const rr = (await getModels()).filter(m => m.kind === "reranker" && m.cached);
  $("#r-rr").innerHTML += rr.map(r => `<option value="${r.id}">${esc(r.name)}</option>`).join("");
  if (rr.length) $("#r-rr").value = String(rr[0].id);
  await rDetail();
}
async function rDetail() {
  if (!$("#r-col").value) return;
  rCol = await api(`/api/collections/${$("#r-col").value}`);
  const idx = rCol.indexes.filter(i => i.status === "ready");
  $("#r-idx").innerHTML = idx.map(i => `<option value="${i.id}">${esc(i.model_hf_id.split(/[\\/]/).pop())} · #${i.id}</option>`).join("") || '<option value="">준비된 인덱스 없음</option>';
  $("#r-cs").innerHTML = rCol.chunk_sets.filter(c => c.status === "ready").map(c => `<option value="${c.id}">${esc(c.name)}</option>`).join("");
  if (!idx.length) $("#r-mode").value = "bm25";
  rMode();
  const sets = (await api(`/api/collections/${rCol.id}/eval-sets`)).filter(s => s.status === "ready");
  $("#e-set").innerHTML = sets.map(s => `<option value="${s.id}">#${s.id} ${esc(s.name)} (${s.n_items}문항)</option>`).join("") || '<option value="">평가 세트 없음</option>';
}
function rMode() { const b = $("#r-mode").value === "bm25"; $("#r-idx-wrap").hidden = b; $("#r-cs-wrap").hidden = !b; }
$("#r-col").addEventListener("change", () => { localSet("routing-col", $("#r-col").value); rDetail(); });
$("#r-mode").addEventListener("change", rMode);

function rPaths() {
  const bm25 = $("#r-mode").value === "bm25";
  const search = { mode: $("#r-mode").value, index_id: bm25 ? null : +$("#r-idx").value || null, chunk_set_id: bm25 ? +$("#r-cs").value || null : null };
  const answer = $("#r-ans").value === "1";
  const enh = $("#r-enh").value;
  return {
    easy: { label: "빠른 경로", config: search, answer, model: $("#r-easy-model").value.trim() || null },
    hard: { label: "전체 경로", answer, config: { ...search, enhance: enh === "none" ? null : { technique: enh }, reranker_id: +$("#r-rr").value || null, rerank_top: +$("#r-rtop").value || 10 },
      ...($("#r-hmode").value === "agent" ? { agent: { max_steps: 5, top_k: 4 } } : $("#r-hmode").value === "best" ? { best_of: 4 } : {}) },
  };
}
const rRouters = () => $$('input[name="r-router"]:checked').map(x => x.value);

$("#q-run").onclick = async e => {
  const q = $("#q-text").value.trim();
  if (!q) return toast("질문을 입력하세요", "err");
  if (!rRouters().length) return toast("라우터를 고르세요", "err");
  const r = await busy(e.target, () => api("/api/routing/route", { method: "POST", body: { question: q, easy: rPaths().easy, routers: rRouters(), threshold: +$("#r-th").value, rule_max_chars: +$("#r-max").value } }));
  $("#q-out").innerHTML = `<div class="table-wrap"><table><tr><th>라우터</th><th>판단</th><th>이유</th><th class="num">판단 시간</th></tr>
    ${r.decisions.map(d => `<tr><td><b>${esc(d.label)}</b></td><td>${PATH[d.path]}</td><td class="small">${esc(d.reason)}${d.top ? ` <span class="muted">(1·2위: ${d.top.map(esc).join(", ")})</span>` : ""}</td><td class="num">${d.ms}ms</td></tr>`).join("")}</table></div>`;
};
$("#q-text").addEventListener("keydown", e => { if (e.key === "Enter") $("#q-run").click(); });

$("#e-run").onclick = async e => {
  if (!$("#e-set").value) return toast("평가 세트가 없습니다", "err");
  if (!rRouters().length) return toast("라우터를 고르세요", "err");
  const body = { eval_set_id: +$("#e-set").value, ...rPaths(), routers: rRouters(), threshold: +$("#r-th").value, rule_max_chars: +$("#r-max").value, max_queries: +$("#e-n").value || null };
  const job = await busy(e.target, () => api("/api/routing/evaluate", { method: "POST", body }));
  const box = $("#e-progress"); box.hidden = false; e.target.disabled = true;
  try {
    const done = await pollJob(job.id, j => { box.innerHTML = `<div class="progress"><div style="width:${pct(j.progress)}%"></div></div><div class="small muted">${esc(j.message)}</div>`; }, 1500);
    if (done.status !== "done") { box.innerHTML = `<div class="errbox">${esc(done.error || done.status)}</div>`; return; }
    box.hidden = true; rRender(done.result);
  } finally { e.target.disabled = false; }
};

const sec = ms => `${(ms / 1000).toFixed(ms >= 10000 ? 0 : 1)}초`;

// 비용(가로: 질문당 평균 지연) - 품질(세로) 그림. 왼쪽 위로 갈수록 좋다. 표가 같은 값을 모두 담고 있어 그림은 보조다.
function rChart(r) {
  const W = 640, H = 310, L = 48, R = 130, T = 26, B = 40;
  const pts = r.results.map(x => ({ k: x.router, x: x.latency_ms.mean, y: x.quality }));
  const xs = [...pts.map(p => p.x), ...r.sweep.map(s => s.latency_ms)], ys = [...pts.map(p => p.y), ...r.sweep.map(s => s.quality)];
  const xMax = Math.max(...xs) * 1.08 || 1, yMin = Math.max(0, Math.floor((Math.min(...ys) - 0.05) * 10) / 10), yMax = 1;
  const X = v => L + (v / xMax) * (W - L - R), Y = v => T + (1 - (v - yMin) / (yMax - yMin || 1)) * (H - T - B);
  const ticksX = [0, 0.25, 0.5, 0.75, 1].map(f => f * xMax), ticksY = [0, 0.25, 0.5, 0.75, 1].map(f => yMin + f * (yMax - yMin));
  const grid = ticksY.map(v => `<line x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--border)" stroke-width="1"/><text x="${L - 6}" y="${Y(v) + 4}" text-anchor="end" font-size="11" fill="var(--muted)">${(v * 100).toFixed(0)}</text>`).join("")
    + ticksX.map(v => `<text x="${X(v)}" y="${H - B + 16}" text-anchor="middle" font-size="11" fill="var(--muted)">${sec(v)}</text>`).join("");
  const line = r.sweep.map((s, i) => `${i ? "L" : "M"}${X(s.latency_ms).toFixed(1)},${Y(s.quality).toFixed(1)}`).join(" ");
  const sweepDots = r.sweep.map(s => `<circle cx="${X(s.latency_ms)}" cy="${Y(s.quality)}" r="9" fill="transparent"><title>확신도 기준 ${s.threshold}: 어려움 ${(s.hard_rate * 100).toFixed(0)}% · 품질 ${(s.quality * 100).toFixed(1)} · ${sec(s.latency_ms)}</title></circle>`).join("");
  // 품질이 같은 라우터가 많아(예: 모두 100) 이름표가 겹친다 — 왼쪽부터 놓으며 겹치면 한 줄씩 아래로 비켜 놓고 지시선을 긋는다
  // 마커도 장애물로 두고, 오른쪽 → 아래 → 위 → 왼쪽 순으로 빈 자리를 찾는다. 비켜 놓으면 지시선을 긋는다.
  const boxes = pts.map(p => ({ x0: X(p.x) - 8, x1: X(p.x) + 8, y0: Y(p.y) - 8, y1: Y(p.y) + 8 }));
  const hit = b => boxes.some(o => b.x0 < o.x1 && o.x0 < b.x1 && b.y0 < o.y1 && o.y0 < b.y1);
  const place = p => {
    const w = R_LABEL[p.k].length * 11 + 4, cx = X(p.x), cy = Y(p.y);
    const tries = [[10, 0], [10, 14], [10, -14], [10, 28], [10, -28], [-10 - w, 0], [-10 - w, 14], [-10 - w, -14], [10, 42]];
    for (const [dx, dy] of tries) {
      const b = { x0: cx + dx, x1: cx + dx + w, y0: cy + dy - 8, y1: cy + dy + 6 };
      if (!hit(b) && b.x0 >= L && b.x1 <= W) { boxes.push(b); return { x: cx + dx, y: cy + dy + 4, moved: dy !== 0 || dx < 0 }; }
    }
    return { x: cx + 10, y: cy + 4, moved: false };
  };
  const dots = [...pts].sort((a, b) => a.x - b.x).map(p => {
    const lb = place(p);
    return `<g>${rMark(p.k, X(p.x), Y(p.y))}
      <circle cx="${X(p.x)}" cy="${Y(p.y)}" r="12" fill="transparent"><title>${R_LABEL[p.k]}: 품질 ${(p.y * 100).toFixed(1)} · ${sec(p.x)}</title></circle>
      ${lb.moved ? `<line x1="${X(p.x)}" y1="${Y(p.y)}" x2="${lb.x < X(p.x) ? lb.x + R_LABEL[p.k].length * 11 : lb.x}" y2="${lb.y - 4}" stroke="var(--muted)" stroke-width="1"/>` : ""}
      <text x="${lb.x}" y="${lb.y}" font-size="11" fill="var(--text)">${R_LABEL[p.k]}</text></g>`;
  }).join("");
  return `<svg viewBox="0 0 ${W} ${H}" width="100%" style="max-width:${W}px" role="img" aria-label="라우터별 비용-품질">
    ${grid}<line x1="${L}" x2="${L}" y1="${T}" y2="${H - B}" stroke="var(--border)"/>
    <text x="${(L + W - R) / 2}" y="${H - 6}" text-anchor="middle" font-size="11" fill="var(--muted)">질문당 평균 지연 →</text>
    <text x="${L - 6}" y="12" text-anchor="end" font-size="11" fill="var(--muted)">품질 ↑</text>
    ${r.sweep.length > 1 ? `<path d="${line}" fill="none" stroke="var(--series-${R_COLOR.confidence})" stroke-width="2" stroke-dasharray="4 3" opacity=".7"/>${sweepDots}` : ""}
    ${dots}</svg>
    <div class="legend">${Object.keys(R_LABEL).filter(k => pts.some(p => p.k === k)).map(k => `<span>${rKey(k)}${R_LABEL[k]}</span>`).join("")}<span><span class="swatch" style="background:none;border-top:2px dashed var(--series-${R_COLOR.confidence});height:0;border-radius:0"></span>확신도 기준을 바꿀 때</span></div>`;
}

function rRender(r) {
  const hard = r.results.find(x => x.router === "always_hard");
  const vs = d => (d ? `${d.diff >= 0 ? "+" : ""}${(d.diff * 100).toFixed(1)}%p ${d.significant ? '<span class="badge err">유의</span>' : '<span class="badge">불확실</span>'}` : "—");
  const save = x => (hard && x.router !== "always_hard" ? `${((1 - x.latency_ms.mean / hard.latency_ms.mean) * 100).toFixed(0)}%` : "—");
  $("#e-out").innerHTML = `<div class="row between"><h3>결과 · ${esc(r.eval_set?.name || "")}</h3><span class="small muted">질문 ${r.n_queries}개 · 품질 = ${esc(r.quality_metric)}${r.seconds != null ? ` · ${r.seconds}s` : ""}${r.run_id ? ` · run #${r.run_id}` : ""}</span></div>
    <div class="table-wrap"><table>
      <tr><th>라우터</th><th class="num">어려움 비율</th><th class="num">품질 (95% 구간)</th><th>전체 경로 대비 품질</th><th class="num">nDCG@10</th><th class="num">지연 평균 / p95</th><th class="num" title="항상 전체 경로 대비 평균 지연 감소">지연 절감</th></tr>
      ${r.results.map(x => `<tr><td><b>${esc(R_LABEL[x.router] || x.label)}</b></td><td class="num">${pct(x.hard_rate)}%</td>
        <td class="num">${pct(x.quality)} <span class="small muted">(${pct(x.quality_ci[0])}–${pct(x.quality_ci[1])})</span></td><td class="small nowrap">${vs(x.vs_hard)}</td>
        <td class="num">${pct(x.ndcg)}</td><td class="num small nowrap">${sec(x.latency_ms.mean)} / ${sec(x.latency_ms.p95)}</td><td class="num">${save(x)}</td></tr>`).join("")}
    </table></div>
    ${rChart(r)}
    <div class="small muted">확신도 라우터의 지연에는 '어려움'으로 판단해 버린 첫 검색이, LLM 판단 라우터에는 판단 호출 시간이 들어 있습니다. 오라클은 정답을 보고 고른 상한이라 실제로는 만들 수 없습니다.</div>
    <h3>질문별 판단</h3>
    <div class="table-wrap" style="max-height:420px"><table><tr><th>질문</th><th class="num">빠른</th><th class="num">전체</th><th class="num">확신도</th>${Object.keys(r.per_query[0]?.routes || {}).map(k => `<th>${esc(R_LABEL[k])}</th>`).join("")}</tr>
      ${r.per_query.map(q => `<tr><td class="small">${esc(q.query)}</td><td class="num">${pct(q.easy_q)}</td><td class="num">${pct(q.hard_q)}</td><td class="num small">${q.confidence != null ? q.confidence.toFixed(3) : "-"}</td>
        ${Object.entries(q.routes).map(([k, p]) => `<td class="small" title="${esc(k === "rule" ? q.rule_reason : k === "llm" ? q.llm_reason || "" : "")}">${p === "hard" ? "어려움" : "쉬움"}</td>`).join("")}</tr>`).join("")}
    </table></div>
    <div class="small muted">빠른 · 전체 = 그 경로의 질문별 품질(%), 칸에 마우스를 올리면 규칙 · LLM 판단 이유가 보입니다.</div>`;
}

rLoad();
