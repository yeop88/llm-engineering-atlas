// 평가 · 관측 E5 · E8: 피드백 요약(이유 · 자동 판정과 일치), 싫어요 받은 답, 실패 유형 분류 → 평가 세트 후보 · 자료 보강 CSV
const picked = new Set();
const days = () => $("#f-days").value;
const ratio = v => (v == null ? "-" : `${Math.round(v * 100)}%`);
const traceLink = id => html`<a href="/evalops/traces?trace=${id}">#${id}</a>`;
// 같은 요청이 여러 표에 나올 수 있어 체크 상자는 요청 id 로 묶는다(한 곳에서 고르면 다른 곳도 같이)
const pickBox = id => html`<input type="checkbox" data-pick="${id}" aria-label="요청 #${id} 고르기" ${picked.has(id) ? "checked" : ""}>`;

function syncPicked() {
  $("#f-picked").textContent = `고른 요청 ${picked.size}건`;
  $("#f-send").disabled = !picked.size;
  $$("[data-pick]").forEach(cb => { cb.checked = picked.has(+cb.dataset.pick); });
}
document.addEventListener("change", e => {
  const cb = e.target.closest("[data-pick]");
  if (!cb) return;
  if (cb.checked) picked.add(+cb.dataset.pick); else picked.delete(+cb.dataset.pick);
  syncPicked();
});

function sentInfo(r, extra = "") {
  const lines = r.sets.map(s => html`<div class="small"><a href="/evalops/sets?set=${s.eval_set_id}">#${s.eval_set_id} ${s.name}</a> · ${s.added}문항 추가</div>`);
  return html`<div class="card stack mt-2"><div class="small">${extra}평가 세트 후보로 보냈습니다 — 검토 전 상태로 들어가며, 평가 세트 · 회귀 화면에서 정답 문서를 채우고 통과시키세요.${r.skipped ? html` 컬렉션 · 질문이 없는 ${r.skipped}건은 건너뜀.` : ""}</div>
    ${html.or(html.join(lines), html`<div class="small muted">추가된 문항 없음(이미 들어 있는 질문)</div>`)}</div>`;
}
$("#f-send").onclick = e => busy(e.target, async () => {
  const r = await api("/api/evalops/traces/to-eval-set", { method: "POST", body: { trace_ids: [...picked] } });
  $("#f-sent").innerHTML = sentInfo(r);
  picked.clear(); syncPicked();
});

// ── 피드백 요약 ────────────────────────────────────────────────────────────
async function loadSummary() {
  const box = $("#f-summary");
  ui.loading(box);
  let s;
  try { s = await api(`/api/evalops/feedback?days=${days()}`); } catch (e) { return ui.error(box, e); }
  if (!s.n) return ui.empty(box, "아직 피드백이 없습니다. 답변 생성 화면에서 답 아래의 좋아요 · 싫어요를 누르면 여기에 모입니다.", { href: "/rag/answer", label: "답변 생성으로" });
  const a = s.agreement;
  const stat = (label, v, sub) => html`<div class="stat"><div class="label">${label}</div><div class="value">${v}</div><div class="small muted">${sub}</div></div>`;
  box.innerHTML = html`<div class="grid cols-3">
      ${stat("피드백", fmtNum(s.n), "좋아요 · 싫어요를 받은 답")}
      ${stat("좋아요율", ratio(s.positive_rate), "")}
      ${stat("자동 판정과 일치", ratio(a.rate), "사람 판정과 자동 판정(근거 일치 ≥ 50% · 관련 없는 문장 없음 · 거절 아님)이 같은 비율")}
    </div>
    <div class="grid cols-2">
      <div><h3>싫어요 이유</h3>${s.reasons.length ? html`<div class="table-wrap"><table><tr><th>이유</th><th class="num">건수</th></tr>${s.reasons.map(r => html`<tr><td>${r.label}</td><td class="num">${r.n}</td></tr>`)}</table></div>` : html`<div class="small muted">싫어요가 없습니다.</div>`}</div>
      <div><h3>사람 × 자동 판정</h3><div class="table-wrap"><table><tr><th></th><th class="num">자동: 좋음</th><th class="num">자동: 나쁨</th></tr>
        <tr><td>사람: 좋아요</td><td class="num">${a.both_good}</td><td class="num">${a.human_good_auto_bad}</td></tr>
        <tr><td>사람: 싫어요</td><td class="num"><b>${a.human_bad_auto_good}</b></td><td class="num">${a.both_bad}</td></tr></table></div>
        <div class="small muted">굵은 칸(사람 싫어요 · 자동 좋음)이 자동 판정이 놓친 답 — 검증 보정 · 평가 세트로 보낼 후보입니다.</div></div>
    </div>
    ${s.auto_missed.length ? html`<h3>자동 판정이 놓친 답</h3><div class="table-wrap scroll-md"><table><tr><th></th><th>요청</th><th>질문</th><th>이유</th></tr>
      ${s.auto_missed.map(t => html`<tr><td>${pickBox(t.id)}</td><td>${traceLink(t.id)}</td><td class="small">${t.question}</td><td class="small">${t.reason || "-"}</td></tr>`)}</table></div>` : ""}`;
}

// ── 싫어요 받은 답 (요청 목록의 '싫어요' 표시) ─────────────────────────────
async function loadBad() {
  const box = $("#f-bad");
  ui.loading(box);
  let r;
  try { r = await api(`/api/evalops/traces?days=${days()}&flag=${encodeURIComponent("싫어요")}&limit=200`); } catch (e) { return ui.error(box, e); }
  if (!r.rows.length) return ui.empty(box, "기간 안에 싫어요 받은 답이 없습니다.");
  box.innerHTML = html`<div class="table-wrap scroll-md"><table><tr><th></th><th>요청</th><th>시각</th><th>질문</th><th>표시</th></tr>
    ${r.rows.map(t => html`<tr><td>${pickBox(t.id)}</td><td>${traceLink(t.id)}</td><td class="small nowrap">${fmtDate(t.created_at)}</td><td class="small">${t.question}</td>
      <td class="small">${html.join(t.flags.map(f => html`<span class="badge ${f === "싫어요" ? "err" : "warn"}">${f}</span>`), " ")}</td></tr>`)}</table></div>`;
}

// ── 개선 루프 ──────────────────────────────────────────────────────────────
async function loadLoop() {
  const box = $("#l-out");
  ui.loading(box);
  let r;
  try { r = await api(`/api/evalops/loop?days=${days()}`); } catch (e) { return ui.error(box, e); }
  if (!r.n) return ui.empty(box, "기간 안에 요청 기록이 없습니다. 서비스 답변(답변 생성 · AS 상담 · A/B 실험)을 쓰면 기록이 쌓입니다.", { href: "/rag/answer", label: "답변 생성으로" });
  box.innerHTML = html`<div class="small">요청 ${fmtNum(r.n)}건 중 실패 유형에 든 요청 <b>${fmtNum(r.failed)}</b>건 (${ratio(r.fail_rate)})</div>
    <div class="table-wrap"><table><tr><th>유형</th><th>고칠 곳</th><th class="num">건수</th><th></th></tr>
    ${r.categories.map(c => html`<tr><td><b>${c.label}</b></td><td class="small muted">${c.fix}</td><td class="num">${c.n}</td>
      <td class="nowrap">${c.n ? html`<button class="btn sm" data-send="${c.key}">평가 세트로</button> <button class="btn sm" data-csv="${c.key}" title="질문 · 검색 결과 수 · 1위 점수 · 피드백 이유">목록 CSV</button>` : ""}</td></tr>
      ${c.examples.length ? html`<tr><td colspan="4"><details><summary class="small">예시 ${c.examples.length}건</summary><div class="table-wrap mt-2"><table>
        ${c.examples.map(t => html`<tr><td>${pickBox(t.id)}</td><td>${traceLink(t.id)}</td><td class="small">${t.question}</td><td class="small">${t.feedback === -1 ? html`<span class="badge err">싫어요</span> ${t.reason}` : t.feedback === 1 ? html`<span class="badge ok">좋아요</span>` : ""}</td></tr>`)}</table></div></details></td></tr>` : ""}`)}</table></div>`;
}
$("#l-out").addEventListener("click", async e => {
  const send = e.target.closest("[data-send]"), csv = e.target.closest("[data-csv]");
  if (send) {
    await busy(send, async () => {
      const r = await api("/api/evalops/loop/send", { method: "POST", body: { category: send.dataset.send, days: +days(), dest: "eval_set" } });
      $("#f-sent").innerHTML = sentInfo(r, html`실패 유형 요청 ${r.n}건을 `);
      $("#f-sent").scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
  } else if (csv) {
    // 내려받기는 POST 라 링크로 걸 수 없다 — 받아서 파일로 저장
    await busy(csv, async () => {
      const res = await fetch("/api/evalops/loop/send", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ category: csv.dataset.csv, days: +days(), dest: "gap_csv" }) });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
      const url = URL.createObjectURL(await res.blob());
      const a = document.createElement("a");
      a.href = url; a.download = `gap-${csv.dataset.csv}.csv`;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
  }
});

function reload() { loadSummary(); loadBad(); loadLoop(); }
$("#f-reload").onclick = reload;
$("#f-days").onchange = reload;
reload();
