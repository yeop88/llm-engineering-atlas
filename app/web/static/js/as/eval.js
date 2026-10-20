// as/eval.html 화면 스크립트 — AS2 분류 · AS4 사진 진단 · 종단 평가와 실행 기록
const KIND = { as_triage: "분류", as_photo: "사진 진단", as_e2e: "종단" };
const r3 = v => (v == null ? "-" : `${pct(v)}%`);
const yes = v => (v == null ? html`<span class="muted">-</span>` : v ? html`<span class="badge ok">예</span>` : html`<span class="badge err">아니오</span>`);
const stat = (v, label) => html`<div class="stat"><div class="value">${v}</div><div class="label">${label}</div></div>`;

// ── 결과 그리기 (실행 직후 · 기록 상세가 같은 함수) ─────────────────────────
function renderTriage(o) {
  const zs = o.intent_zero_shot, cv = o.intent_trained_cv || {}, u = o.urgency;
  const cvBy = Object.fromEntries((cv.per_class || []).map(c => [c.label, c]));
  return html`<div class="small muted">모델 <span class="mono">${o.model}</span> · 문의 ${o.n}개${o.run_id ? html` · 실행 #${o.run_id}` : ""}</div>
    <div class="grid cols-4">
      ${stat(r3(zs.accuracy), `의도 정확도 · 제로샷 (macro F1 ${zs.macro_f1})`)}
      ${stat(cv.accuracy != null ? r3(cv.accuracy) : "-", cv.accuracy != null ? `의도 정확도 · 학습 ${cv.folds}겹 CV (macro F1 ${cv.macro_f1})` : `학습 분류기: ${cv.note || "-"}`)}
      ${stat(r3(u.safety_recall), `안전 재현율 (정밀도 ${r3(u.safety_precision)})`)}
      ${stat(`${o.codes.extracted}/${o.codes.n}`, `오류 코드 추출 · 긴급도 정확도 ${r3(u.accuracy)}`)}
    </div>
    ${u.safety_recall != null && u.safety_recall < 1 ? html`<div class="errbox">안전 문의를 놓쳤습니다 — 자동 답변으로 흘러가면 위험합니다. triage.SAFETY 규칙을 보강하세요.</div>` : ""}
    <div class="table-wrap"><table><thead><tr><th>의도</th><th class="num">문의</th><th class="num">제로샷 정밀도</th><th class="num">제로샷 재현율</th><th class="num">제로샷 F1</th><th class="num">학습 F1</th></tr></thead>
      <tbody>${zs.per_class.map(c => html`<tr><td>${c.label}</td><td class="num">${c.support}</td><td class="num">${c.precision}</td><td class="num">${c.recall}</td><td class="num">${c.f1}</td><td class="num">${cvBy[c.label]?.f1 ?? "-"}</td></tr>`)}</tbody></table></div>
    ${zs.errors.length ? html`<details><summary class="small">제로샷 오답 ${zs.errors.length}개</summary><div class="table-wrap mt-2"><table><thead><tr><th>문의</th><th>정답</th><th>예측</th></tr></thead>
      <tbody>${zs.errors.map(e => html`<tr><td class="small">${e.text}</td><td>${e.true}</td><td>${e.pred}</td></tr>`)}</tbody></table></div></details>` : ""}`;
}

function renderPhoto(o) {
  return html`<div class="small muted">${o.llm?.model || ""} · 그림 ${o.n}장${o.hard ? " · 어려운 사진" : ""}${o.run_id ? html` · 실행 #${o.run_id}` : ""}</div>
    <div class="grid cols-4">
      ${stat(r3(o.raw_accuracy), "정확도 · 목록 맞춤 전")}
      ${stat(r3(o.accuracy), "정확도 · 목록 맞춤 후")}
      ${stat(o.snapped, "비슷한 글자로 고친 수")}
      ${stat(`${o.mean_seconds}s`, "그림당 평균 시간")}
    </div>
    <div class="table-wrap scroll-md"><table><thead><tr><th>정답 코드</th><th>읽은 글자</th><th>맞춘 코드</th><th>맞음 (맞춤 전)</th><th>맞음 (맞춤 후)</th><th class="num">초</th></tr></thead>
      <tbody>${o.rows.map(r => html`<tr><td class="mono">${r.code}</td><td class="mono">${r.raw_read || "-"}</td><td class="mono">${r.read || "-"}${r.snapped ? html` <span class="badge warn">고침</span>` : ""}</td>
        <td>${yes(r.raw_ok)}</td><td>${yes(r.ok)}</td><td class="num">${r.seconds}</td></tr>`)}</tbody></table></div>`;
}

function renderE2E(o) {
  return html`<div class="small muted">${o.llm?.model || ""} · 가드레일 ${o.guard_mode} · 제품 필터 ${o.filter_model ? "켬" : "끔"} · 문의 ${o.n}개${o.errors ? html` · <span class="badge err">오류 ${o.errors}</span>` : ""}${o.run_id ? html` · 실행 #${o.run_id}` : ""}</div>
    <div class="grid cols-4">
      ${stat(r3(o.safety_handoff), "안전 문의 이관 (1 이어야 함)")}
      ${stat(r3(o.right_doc), "고장 문의 · 고객 제품 문서를 근거로")}
      ${stat(r3(o.mismatch_rate), "다른 모델 근거가 섞인 비율")}
      ${stat(r3(o.handoff_rate), "상담원 이관률")}
      ${stat(r3(o.intent_accuracy), "의도 분류 정확도")}
      ${stat(r3(o.supported_mean), "근거 일치 평균")}
      ${stat(o.mean_seconds != null ? `${o.mean_seconds}s` : "-", "문의당 평균 시간")}
      ${stat(html.join(Object.entries(o.by_intent || {}).map(([k, v]) => `${k} ${v}`), " · "), "의도별 문의 수")}
    </div>
    <div class="table-wrap scroll-lg"><table><thead><tr><th>문의</th><th>의도 (예측)</th><th>긴급도</th><th>이관</th><th>맞는 문서</th><th>다른 모델</th><th>거절</th><th class="num">근거 일치</th><th class="num">초</th></tr></thead>
      <tbody>${o.rows.map(r => (r.error ? html`<tr><td class="small">${r.text}</td><td colspan="8"><span class="errline small">${r.error}</span></td></tr>`
        : html`<tr><td class="small">${r.text}</td><td>${r.intent}${r.pred_intent !== r.intent ? html` <span class="badge err">${r.pred_intent}</span>` : ""}</td>
          <td>${r.urgency === "safety" ? html`<span class="badge err">안전</span>` : r.urgency}</td><td>${yes(r.handoff)}</td><td>${yes(r.right_doc)}</td>
          <td>${r.mismatch ? html`<span class="badge warn">섞임</span>` : ""}</td><td>${r.refused ? html`<span class="badge">거절</span>` : ""}</td>
          <td class="num">${r.supported == null ? "-" : r.supported}</td><td class="num">${r.seconds}</td></tr>`))}</tbody></table></div>`;
}
const RENDER = { as_triage: renderTriage, as_photo: renderPhoto, as_e2e: renderE2E };

// ── 실행 ───────────────────────────────────────────────────────────────────
const llmRef = () => ({ provider: $("#ph-provider").value || null, model: $("#ph-model").value.trim() || null });
const after = (out, render) => r => { out.innerHTML = render(r); loadRuns(); };

$("#tr-run").onclick = e => runJobInto(e.target, "/api/as/eval/triage", { model_id: +$("#tr-model").value || null }, $("#tr-progress"), after($("#tr-out"), renderTriage));
$("#ph-run").onclick = e => runJobInto(e.target, "/api/as/eval/photo", { ...llmRef(), hard: $("#ph-hard").checked, repeats: +$("#ph-repeats").value || 1 }, $("#ph-progress"), after($("#ph-out"), renderPhoto));
$("#e2e-run").onclick = e => runJobInto(e.target, "/api/as/eval/e2e",
  { ...llmRef(), guard_mode: $("#e2e-guard").value, filter_model: $("#e2e-filter").checked, limit: +$("#e2e-limit").value || 48 }, $("#e2e-progress"), after($("#e2e-out"), renderE2E));

// ── 실행 기록 ──────────────────────────────────────────────────────────────
const SUM = { accuracy: "정확도", raw_accuracy: "맞춤 전", intent_zero_shot: "제로샷", safety_handoff: "안전 이관", right_doc: "맞는 문서", mismatch_rate: "다른 모델", handoff_rate: "이관률", intent_accuracy: "의도", mean_seconds: "평균 초" };
async function loadRuns() {
  const box = $("#h-list");
  try {
    const runs = await api("/api/as/eval/runs");
    if (!runs.length) return ui.empty(box, "아직 실행 기록이 없습니다.");
    box.innerHTML = html`<div class="table-wrap scroll-md"><table><thead><tr><th>#</th><th>종류</th><th>제목</th><th>요약</th><th>시각</th></tr></thead>
      <tbody>${runs.map(r => html`<tr><td><a href="#run-${r.id}" data-run="${r.id}">${r.id}</a></td><td>${KIND[r.kind] || r.kind}</td><td class="small">${r.title}</td>
        <td class="small">${html.join(Object.entries(r.summary).map(([k, v]) => `${SUM[k] || k} ${k === "mean_seconds" ? `${v}s` : r3(v)}`), " · ")}</td><td class="small">${fmtDate(r.created_at)}</td></tr>`)}</tbody></table></div>`;
  } catch (e) { ui.error(box, e); }
}
$("#h-list").addEventListener("click", async e => {
  const a = e.target.closest("[data-run]");
  if (!a) return;
  e.preventDefault();
  const box = $("#h-detail");
  ui.loading(box);
  try {
    const r = await api(`/api/as/eval/runs/${a.dataset.run}`);
    box.innerHTML = html`<h3>#${r.id} ${r.title} <span class="small muted">${fmtDate(r.created_at)}</span></h3>${RENDER[r.kind] ? RENDER[r.kind](r) : ""}`;
  } catch (err) { ui.error(box, err); }
});
$("#h-reload").onclick = loadRuns;

async function init() {
  bindCtx();
  const sel = $("#tr-model");
  try {
    await fillModelSelect(sel);
    // 비우면 서버의 VERIFY_MODEL — 상담 창이 쓰는 분류 모델과 같은 것으로 재게 기본값으로 둔다
    sel.insertAdjacentHTML("afterbegin", html`<option value="">기본 (VERIFY_MODEL — 상담 창과 같은 모델)</option>`);
    sel.value = "";
  } catch (e) { toast(e.message, "err"); }
  try { const m = await api("/api/llm/models"); $("#ev-model-list").innerHTML = html`${m.models.map(x => html`<option value="${x}">`)}`; } catch { /* 로컬 서버가 꺼져 있으면 목록 없음 */ }
  loadRuns();
}
init();
