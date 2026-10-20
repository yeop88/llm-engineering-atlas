// G1 · G2 · G4 입력 · 출력 검사: 글 하나로 인젝션 감지 · 개인정보 찾기 · 출력 정책을 바로 시험하고, 컬렉션 문서의 개인정보를 세고 가린다
let PII_LABEL = {};
// 방어 모드는 색만으로 구분하지 않게 글자를 함께 쓴다
const MODE = {
  off: ["off · 검사 · 기록만", "muted"],
  mask: ["mask · 개인정보만 가림", "warn"],
  enforce: ["enforce · 차단 · 수정 · 거절", "ok"],
};
const ACTION = { pass: ["✓ 통과", "ok"], fix: ["✎ 수정해 내보냄", "warn"], block: ["⛔ 거절", "err"] };
const modeBadge = m => html`<span class="badge ${(MODE[m] || ["", ""])[1]}">방어 모드 ${(MODE[m] || [m])[0]}</span>`;
const actBadge = a => html`<span class="badge ${(ACTION[a] || ["", ""])[1]}">${(ACTION[a] || [a])[0]}</span>`;
const countList = c => html.or(html.join(Object.entries(c || {}).map(([k, v]) => html`<span class="badge">${PII_LABEL[k] || k} ${v}</span>`), " "), html`<span class="muted">없음</span>`);

function text() {
  const t = $("#c-text").value.trim();
  if (!t) toast("검사할 글을 넣으세요", "err");
  return t;
}

$("#c-input").onclick = async e => {
  const t = text();
  if (!t) return;
  const r = await busy(e.target, () => api("/api/guardrails/check-input", { method: "POST", body: { text: t } }));
  $("#c-out").innerHTML = html`<h3>입력 검사</h3>
    <div class="row">${r.suspicious ? html`<span class="badge err">⚠ 의심 · 규칙 ${r.score}종</span>` : html`<span class="badge ok">✓ 의심 문형 없음</span>`}
      <span class="small muted">enforce 모드에서는 의심 질문을 LLM 에 보내지 않고 거절합니다.</span></div>
    ${r.hits.length ? html`<div class="table-wrap"><table><tr><th>규칙</th><th>맞은 부분</th></tr>
      ${r.hits.map(h => html`<tr><td class="nowrap"><b>${h.rule}</b></td><td class="small"><code>${h.match}</code></td></tr>`)}</table></div>` : ""}`;
};

$("#c-pii").onclick = async e => {
  const t = text();
  if (!t) return;
  const r = await busy(e.target, () => api("/api/guardrails/pii/scan", { method: "POST", body: { text: t } }));
  $("#c-out").innerHTML = html`<h3>개인정보</h3>
    <div class="row">${r.hits.length ? html`<span class="badge warn">⚠ ${r.hits.length}개 찾음</span>` : html`<span class="badge ok">✓ 찾지 못함</span>`} ${countList(r.counts)}</div>
    ${r.hits.length ? html`<div class="table-wrap"><table><tr><th>종류</th><th>찾은 글</th><th class="num">위치</th></tr>
      ${r.hits.map(h => html`<tr><td class="nowrap">${PII_LABEL[h.type] || h.type}</td><td><code>${h.text}</code></td><td class="num small">${h.start}–${h.end}</td></tr>`)}</table></div>` : ""}
    <div class="field-label mt-2">가린 글</div><div class="pre small bg-code p-2">${r.masked}</div>`;
};

$("#c-output").onclick = async e => {
  const t = text();
  if (!t) return;
  const r = await busy(e.target, () => api("/api/guardrails/check-output", { method: "POST", body: { text: t, domain: $("#c-domain").value } }));
  $("#c-out").innerHTML = html`<h3>출력 정책 · ${$("#c-domain").selectedOptions[0].textContent}</h3>
    <div class="row">${actBadge(r.action)} <span class="small">개인정보: ${countList(r.pii)}</span></div>
    ${r.violations.length ? html`<div class="table-wrap"><table><tr><th>규칙</th><th>동작</th><th>맞은 부분</th></tr>
      ${r.violations.map(v => html`<tr><td class="nowrap"><b>${v.rule}</b></td><td>${actBadge(v.action)}</td><td class="small"><code>${v.match}</code></td></tr>`)}</table></div>`
      : html`<div class="small muted">분야 정책 위반 없음</div>`}
    <div class="field-label mt-2">내보낼 글 (enforce 모드 기준)</div><div class="pre small bg-code p-2">${r.fixed}</div>`;
};

async function loadPolicies() {
  try {
    const p = await api("/api/guardrails/policies");
    PII_LABEL = p.pii_types || {};
    $("#c-mode").innerHTML = modeBadge(p.mode);
    const DOM = { legal: "법률", medical: "의료", support: "고객 AS", general: "일반" };
    // 같은 규칙 이름에 정규식이 여럿이라(문형별) 이름 · 동작으로 한 번만 보인다
    const uniq = rs => [...new Map(rs.map(r => [`${r.rule}|${r.action}`, r])).values()];
    const rules = rs => html.or(html.join(uniq(rs).map(r => html`<div class="small">${r.rule} ${actBadge(r.action)}</div>`), ""), html`<div class="small muted">분야 규칙 없음</div>`);
    $("#c-policies").innerHTML = html`<div class="grid cols-4">
      ${Object.entries(p.domains).map(([d, rs]) => html`<div class="stack gap-1"><b>${DOM[d] || d}</b>${rules(rs)}</div>`)}
      <div class="stack gap-1"><b>공통 (모든 분야)</b>${rules(p.common)}<div class="small">개인정보 → 가림</div></div></div>
      <div class="small mt-2"><span class="muted">인젝션 규칙:</span> ${html.join(p.injection_rules.map(r => html`<span class="badge muted">${r}</span>`), " ")}</div>
      <div class="small"><span class="muted">개인정보 종류:</span> ${html.join(Object.values(PII_LABEL).map(r => html`<span class="badge muted">${r}</span>`), " ")}</div>`;
  } catch (e) { ui.error($("#c-policies"), e); }
}

// ── 컬렉션 개인정보 ──
async function loadCols() {
  const cols = await api("/api/collections");
  $("#p-col").innerHTML = html.or(html.join(cols.map(c => html`<option value="${c.id}">${c.name}</option>`), ""), html`<option value="">컬렉션 없음</option>`);
  applyCtx($("#p-col"));
}

async function scan(btn) {
  const cid = $("#p-col").value;
  if (!cid) return toast("컬렉션을 고르세요", "err");
  const r = await busy(btn, () => api(`/api/guardrails/pii/collections/${cid}`));
  $("#p-out").innerHTML = html`<div class="row"><span class="small">전체:</span> ${countList(r.total)} <span class="small muted">개인정보가 든 문서 ${r.documents.filter(d => Object.keys(d.counts).length).length}개</span></div>
    ${r.documents.length ? html`<div class="table-wrap scroll-md"><table><tr><th>문서</th><th>개인정보</th><th>가림</th></tr>
      ${r.documents.map(d => html`<tr><td class="small">${d.filename} <span class="muted">#${d.document_id}</span></td><td>${countList(d.counts)}</td>
        <td>${d.masked ? html`<span class="badge ok" title="${JSON.stringify(d.masked)}">✓ 가림</span>` : html`<span class="muted small">—</span>`}</td></tr>`)}</table></div>`
      : html`<div class="empty">개인정보를 찾지 못했습니다.</div>`}`;
}
$("#p-scan").onclick = e => scan(e.target);
$("#p-mask").onclick = async e => {
  const cid = $("#p-col").value;
  if (!cid) return toast("컬렉션을 고르세요", "err");
  const name = $("#p-col").selectedOptions[0]?.textContent || cid;
  const ok = await ui.confirm(`'${name}' 의 문서 글에서 개인정보를 [이름] · [전화번호] 처럼 바꿉니다. 원본 파일은 남지만 문서 글은 되돌릴 수 없고, 청크 · 벡터는 증분 갱신으로 다시 만들어야 합니다.`,
    { ok: "가리기", danger: true, title: "개인정보 가리기" });
  if (!ok) return;
  const r = await busy(e.target, () => api(`/api/guardrails/pii/collections/${cid}/mask`, { method: "POST" }));
  toast(`문서 ${r.changed_documents}개를 가렸습니다. ${r.next}`, "ok");
  await scan(null);
};

loadPolicies();
loadCols();
