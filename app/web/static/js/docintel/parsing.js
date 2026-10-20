// D2 파싱 점검 · OCR · D3 표 · 그림: 컬렉션 파싱 보고 → 문서 하나 상세(쪽별 글) → OCR · 표 · 그림 추출 작업
let pReport = null;   // 컬렉션 보고(문제가 있는 문서만 거를 때 다시 부르지 않으려고)
let pDoc = null;      // 지금 연 문서 상세

const colId = () => +$("#p-col").value || null;
const brokenBadge = r => (r > 0.01 ? html`<span class="badge err">${pct(r)}%</span>` : r > 0 ? html`<span class="badge warn">${pct(r)}%</span>` : html`<span class="muted">0</span>`);

async function pLoad() {
  const box = $("#p-list");
  $("#p-summary").replaceChildren();
  if (!colId()) return ui.empty(box, "컬렉션이 없습니다", { href: "/rag/collections", label: "컬렉션 만들기" });
  ui.loading(box, "문서마다 쪽 · 글자를 점검하는 중…");
  try {
    pReport = await api(`/api/docintel/collections/${colId()}/parsing`);
    const docs = pReport.documents;
    const broken = docs.filter(d => d.broken_ratio > 0.01).length;
    const empty = docs.reduce((n, d) => n + d.empty_pages.length, 0);
    $("#p-summary").innerHTML = html`<div class="grid cols-4">
      <div class="stat"><div class="label">문서</div><div class="value">${fmtNum(docs.length)}</div></div>
      <div class="stat"><div class="label">문제가 있는 문서</div><div class="value">${fmtNum(pReport.n_issues)}</div></div>
      <div class="stat"><div class="label">빈 쪽 (모든 문서)</div><div class="value">${fmtNum(empty)}</div><div class="small muted">${pReport.n_without_original ? `원본 없음 ${pReport.n_without_original}개 — OCR · 표 추출 불가` : "모두 원본 있음"}</div></div>
      <div class="stat"><div class="label">깨진 글자 &gt; 1%</div><div class="value">${fmtNum(broken)}</div></div></div>`;
    pRender();
  } catch (e) { ui.error(box, e); }
}

function pRender() {
  const box = $("#p-list");
  const docs = pReport.documents.filter(d => !$("#p-only").checked || d.issues.length);
  if (!pReport.documents.length) return ui.empty(box, "문서가 없습니다", { href: `/rag/collections/${colId()}`, label: "문서 올리기" });
  if (!docs.length) return ui.empty(box, "문제가 있는 문서가 없습니다");
  box.innerHTML = html`<div class="table-wrap scroll-lg"><table><tr><th>#</th><th>파일</th><th class="num">쪽</th><th class="num">글자</th><th class="num">빈 쪽</th><th class="num">깨진 글자</th><th>처리</th><th>문제</th><th></th></tr>
    ${docs.map(d => html`<tr><td>${d.document_id}</td><td class="small break-all">${d.filename}${d.has_original ? "" : html` <span class="badge muted" title="원본 저장 전에 올린 문서 — 다시 올려야 OCR · 표 추출을 할 수 있음">원본 없음</span>`}</td>
      <td class="num">${d.n_pages}</td><td class="num">${fmtNum(d.n_chars)}</td><td class="num">${d.empty_pages.length ? html`<b>${d.empty_pages.length}</b>` : html`<span class="muted">0</span>`}</td>
      <td class="num">${brokenBadge(d.broken_ratio)}</td>
      <td class="small">${d.ocr ? html`<span class="badge ok">OCR</span> ` : ""}${d.layout ? html`<span class="badge ok">표 ${d.layout.tables} · 그림 ${d.layout.figures}</span>` : ""}</td>
      <td class="small">${html.join(d.issues.map(i => html`<div>${i}</div>`), "")}</td>
      <td><button class="btn sm${pDoc?.document_id === d.document_id ? " primary" : ""}" data-open="${d.document_id}">열기</button></td></tr>`)}</table></div>`;
}
$("#p-only").addEventListener("change", () => pReport && pRender());
$("#p-reload").onclick = () => pLoad();
$("#p-list").addEventListener("click", e => {
  const b = e.target.closest("[data-open]");
  if (b) dOpen(+b.dataset.open);
});

// ── 문서 상세 ──────────────────────────────────────────────────────────
async function dOpen(id) {
  $("#d-card").hidden = false;
  ui.loading($("#d-info"));
  try {
    pDoc = await api(`/api/docintel/documents/${id}/parsing`);
  } catch (e) { return ui.error($("#d-info"), e); }
  const d = pDoc;
  $("#d-title").textContent = `#${d.document_id} ${d.filename}`;
  const max = Math.max(1, ...d.chars_per_page);
  // 쪽별 글자 수 막대 — 빈 쪽(스캔)은 한눈에 끊겨 보인다. 폭만 값이라 인라인 style(막대 폭) 대신 progress 요소를 쓴다
  $("#d-info").innerHTML = html`<div class="kv small">
      <div>형식</div><div>${d.mime || "-"} · ${d.page_kind || "-"} · ${d.n_pages}쪽 · ${fmtNum(d.n_chars)}자</div>
      <div>빈 쪽</div><div>${d.empty_pages.length ? html.join(d.empty_pages.map(n => `p.${n}`), ", ") : "없음"}</div>
      <div>깨진 글자</div><div>${brokenBadge(d.broken_ratio)}</div>
      <div>원본</div><div>${d.has_original ? "있음" : html`<span class="badge warn">없음 — OCR · 표 추출을 하려면 다시 올리세요</span>`}</div>
      ${d.ocr ? html`<div>OCR</div><div>${d.ocr.engine} · ${d.ocr.pages.length}쪽 · ${d.ocr.seconds}초${d.ocr.accuracy != null ? html` · 글자 정확도 <b>${pct(d.ocr.accuracy)}%</b>` : ""}</div>` : ""}
      ${d.layout ? html`<div>표 · 그림</div><div>표 ${d.layout.tables} · 그림 ${d.layout.figures} · 글자 ${fmtNum(d.layout.chars_before)} → ${fmtNum(d.layout.chars_after)}</div>` : ""}
      <div>문제</div><div>${html.or(html.join(d.issues.map(i => html`<div>${i}</div>`), ""), html`<span class="muted">없음</span>`)}</div>
    </div>
    ${d.n_pages > 1 ? html`<details class="mt-2"><summary class="small">쪽별 글자 수</summary><div class="table-wrap scroll-sm"><table>${d.chars_per_page.map((c, i) => html`<tr><td class="num">p.${i + 1}</td><td class="num">${fmtNum(c)}</td><td><progress max="${max}" value="${c}" aria-label="p.${i + 1} 글자 수"></progress></td></tr>`)}</table></div></details>` : ""}`;
  const pdf = d.filename.toLowerCase().endsWith(".pdf") && d.has_original;
  $("#o-run").disabled = !pdf;
  $("#l-run").disabled = !pdf;
  $("#o-out").innerHTML = pdf ? "" : html`<div class="small muted">OCR · 표 추출은 원본이 있는 PDF 문서만 됩니다.</div>`;
  $("#l-out").replaceChildren();
  $("#o-pages").value = "";
  $("#d-page").innerHTML = html`${(d.pages || []).map((p, i) => html`<option value="${i}">p.${i + 1} (${fmtNum(p.length)}자)${d.empty_pages.includes(i + 1) ? " · 빈 쪽" : ""}</option>`)}`;
  dPage();
  tLoad();
  if (pReport) pRender();
}
function dPage() {
  const t = pDoc?.pages?.[+$("#d-page").value] ?? "";
  $("#d-text").textContent = t || "(글자 없음)";
}
$("#d-page").addEventListener("change", dPage);

// "1, 3-5" → [1, 3, 4, 5]
function parsePages(s) {
  const out = new Set();
  for (const part of s.split(/[,\s]+/).filter(Boolean)) {
    const m = part.match(/^(\d+)(?:-(\d+))?$/);
    if (!m) throw new Error(`쪽 번호를 읽을 수 없습니다: ${part}`);
    const a = +m[1], b = +(m[2] || m[1]);
    for (let n = Math.min(a, b); n <= Math.max(a, b) && out.size < 500; n++) out.add(n);
  }
  return [...out];
}

$("#o-run").onclick = async e => {
  if (!pDoc) return;
  let pages;
  try { pages = parsePages($("#o-pages").value); } catch (err) { return toast(err.message, "err"); }
  if (!pages.length && !pDoc.empty_pages.length) return toast("빈 쪽이 없습니다 — 정확도를 재려면 쪽 번호를 적으세요", "err");
  const body = { provider: $("#o-provider").value || null, model: $("#o-model").value.trim() || null, pages };
  const id = pDoc.document_id;
  await runJobInto(e.target, `/api/docintel/documents/${id}/ocr`, body, $("#o-progress"), r => {
    $("#o-out").innerHTML = r.message ? html`<div class="small muted">${r.message}</div>` : html`
      <div class="small">${r.pages.length}쪽 · ${r.seconds}초${r.accuracy != null ? html` · 글자 정확도 <b>${pct(r.accuracy)}%</b> <span class="muted">(파서 글 기준)</span>` : ""}</div>
      <div class="table-wrap"><table><tr><th class="num">쪽</th><th class="num">읽은 글자</th><th class="num">시간</th><th>결과</th></tr>
        ${r.pages.map(p => html`<tr><td class="num">p.${p.page}</td><td class="num">${fmtNum(p.chars)}</td><td class="num">${p.seconds}초</td>
          <td class="small">${p.measured_only ? html`정확도만 잼 · <b>${pct(p.accuracy)}%</b>` : p.chars ? "빈 쪽을 채움" : html`<span class="muted">글자 없음</span>`}</td></tr>`)}</table></div>`;
    toast("OCR 을 마쳤습니다", "ok");
    dOpen(id); pLoad();
  }).catch(() => {});
};

$("#l-run").onclick = async e => {
  if (!pDoc) return;
  const id = pDoc.document_id;
  await runJobInto(e.target, `/api/docintel/documents/${id}/layout`, { figures: $("#l-figs").checked }, $("#l-progress"), r => {
    $("#l-out").innerHTML = html`<div class="small">표 <b>${r.tables}</b>개 · 그림 <b>${r.figures}</b>개 · 글자 ${fmtNum(r.chars_before)} → ${fmtNum(r.chars_after)}</div>`;
    toast("표 · 그림을 추출했습니다", "ok");
    dOpen(id); pLoad();
  }).catch(() => {});
};

// ── 표 · 그림 목록 ─────────────────────────────────────────────────────
async function tLoad() {
  const box = $("#t-out");
  ui.loading(box);
  try {
    const id = pDoc.document_id;
    const r = await api(`/api/docintel/documents/${id}/tables`);
    if (!r.tables.length && !r.figures.length) return ui.empty(box, r.layout ? "추출했지만 표 · 그림이 없습니다" : "아직 표 · 그림을 추출하지 않았습니다(PDF 만)");
    box.innerHTML = html`
      ${r.tables.length ? html`<div class="small muted">표 ${r.tables.length}개 — 문서 글 안에 이 모양으로 들어가 청킹 · 검색 · 답변에 그대로 쓰입니다.</div>
        <div class="stack scroll-md">${r.tables.map(t => html`<div class="pre bg-code p-2 small">${t}</div>`)}</div>` : ""}
      ${r.figures.length ? html`<div class="small muted mt-2">그림 ${r.figures.length}개 — 청크 세트에서 글 청크 뒤에 그림 청크로 들어갑니다(멀티모달 모델 인덱스면 그림으로 색인).</div>
        <div class="thumbs">${r.figures.map((f, i) => html`<figure class="m-0"><img src="/api/docintel/documents/${id}/figures/${i}" alt="${f.label}" loading="lazy"><figcaption class="small muted">${f.label}</figcaption></figure>`)}</div>` : ""}`;
  } catch (e) { ui.error(box, e); }
}

// 컬렉션이 없으면 onDetail 이 불리지 않는다 — 그때도 안내가 보이게
setupCollectionPickers({ col: $("#p-col"), onDetail: () => { pDoc = null; $("#d-card").hidden = true; pLoad(); } }).then(d => { if (!d) pLoad(); });
