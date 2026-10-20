// D1 수집 소스 · D6 메타데이터 · 증분 갱신: 폴더 소스 목록 · 동기화, 청크 세트 '최신 아님' 상태 · 증분 갱신, 문서 메타데이터 고치기
let dMeta = null;  // 마지막으로 불러온 메타데이터(검색 칸으로 거를 때 다시 부르지 않으려고)

const colId = () => +$("#d-col").value || null;
const n0 = v => (v ? html`<b>${fmtNum(v)}</b>` : html`<span class="muted">0</span>`);

// ── 수집 소스 ────────────────────────────────────────────────────────────
async function sLoad() {
  const box = $("#s-list");
  if (!colId()) return ui.empty(box, "컬렉션이 없습니다", { href: "/rag/collections", label: "컬렉션 만들기" });
  ui.loading(box);
  try {
    const r = await api(`/api/docintel/sources?collection_id=${colId()}`);
    $("#s-roots").textContent = `허용된 폴더: ${r.roots.join(" · ")} — 이 아래 폴더만 소스로 쓸 수 있습니다.`;
    if (!r.sources.length) return ui.empty(box, "이 컬렉션에 등록한 수집 소스가 없습니다. 위에서 폴더를 추가하세요.");
    box.innerHTML = html`<div class="table-wrap"><table><tr><th>#</th><th>폴더</th><th>패턴</th><th class="num">주기</th><th>마지막 동기화</th><th>결과</th><th></th></tr>
      ${r.sources.map(s => html`<tr><td>${s.id}</td><td class="small break-all">${s.path}</td><td><code>${s.pattern}</code></td>
        <td class="num">${s.interval_min ? `${s.interval_min}분` : html`<span class="muted">손으로</span>`}</td>
        <td class="small">${fmtDate(s.last_run_at)}</td><td class="small">${s.last_stats?.n_files != null ? syncLine(s.last_stats) : html`<span class="muted">-</span>`}</td>
        <td class="nowrap"><button class="btn sm primary" data-sync="${s.id}">지금 동기화</button> <button class="btn sm" data-del="${s.id}" data-path="${s.path}">삭제</button></td></tr>`)}</table></div>`;
  } catch (e) { ui.error(box, e); }
}
const syncLine = st => html`파일 ${fmtNum(st.n_files)} · 새 ${n0(st.new)} · 바뀜 ${n0(st.changed)} · 지움 ${n0(st.deleted)} · 같음 ${fmtNum(st.unchanged)}${st.skipped?.length ? html` · <span class="badge warn">건너뜀 ${st.skipped.length}</span>` : ""}`;

$("#s-add").onclick = async e => {
  if (!colId()) return toast("컬렉션을 고르세요", "err");
  const path = $("#s-path").value.trim();
  if (!path) return toast("폴더 경로를 입력하세요", "err");
  await busy(e.target, () => api("/api/docintel/sources", { method: "POST", body: { collection_id: colId(), path, pattern: $("#s-pattern").value.trim() || "*", interval_min: +$("#s-interval").value || 0 } }));
  toast("소스를 추가했습니다", "ok");
  $("#s-path").value = "";
  sLoad();
};

$("#s-list").addEventListener("click", async e => {
  const del = e.target.closest("[data-del]");
  if (del) {
    if (!(await ui.confirm(`수집 소스 #${del.dataset.del} (${del.dataset.path}) 를 삭제할까요? 이미 가져온 문서는 컬렉션에 그대로 남습니다(주기 동기화만 멈춤).`, { ok: "소스 삭제", danger: true }))) return;
    await busy(del, () => api(`/api/docintel/sources/${del.dataset.del}`, { method: "DELETE" }));
    toast("삭제했습니다", "ok");
    return sLoad();
  }
  const sync = e.target.closest("[data-sync]");
  if (sync) {
    await runJobInto(sync, `/api/docintel/sources/${sync.dataset.sync}/sync`, { refresh: $("#s-refresh").checked }, $("#s-progress"), r => {
      sRenderSync(r);
      sLoad(); cLoad(); mLoad();
    }).catch(() => {});
  }
});

function sRenderSync(r) {
  const st = r.sync;
  $("#s-out").innerHTML = html`<div class="grid cols-4 mt-2">
      ${[["새 파일", st.new], ["바뀐 파일", st.changed], ["지운 파일", st.deleted], ["같음 (건너뜀)", st.unchanged]].map(([k, v]) => html`<div class="stat"><div class="label">${k}</div><div class="value">${fmtNum(v)}</div></div>`)}
    </div>
    ${st.skipped?.length ? html`<div class="warnbox mt-2">넣지 못한 파일 ${st.skipped.length}개<ul class="small">${st.skipped.map(s => html`<li><code>${s.file}</code> — ${s.reason}</li>`)}</ul></div>` : ""}
    ${r.refresh?.length ? refreshTable(r.refresh) : html`<div class="small muted mt-2">${st.new || st.changed || st.deleted ? "증분 갱신은 하지 않았습니다(옵션 꺼짐 또는 준비된 청크 세트 없음)." : "바뀐 파일이 없어 갱신할 것이 없습니다."}</div>`}`;
}

// ── 청크 세트 상태 · 증분 갱신 ────────────────────────────────────────────
function refreshTable(rows) {
  return html`<div class="table-wrap mt-2"><table><tr><th>청크 세트</th><th class="num">추가 문서</th><th class="num">바뀐 문서</th><th class="num">삭제 문서</th><th class="num">지운 청크</th><th class="num">새 청크</th><th class="num">전체 청크</th><th>인덱스</th><th class="num">걸린 시간</th></tr>
    ${rows.map(r => html`<tr><td>#${r.chunk_set_id}</td><td class="num">${r.plan.added.length}</td><td class="num">${r.plan.changed.length}</td><td class="num">${r.plan.removed.length}</td>
      <td class="num">${fmtNum(r.removed_chunks)}</td><td class="num">${fmtNum(r.added_chunks)}</td><td class="num">${fmtNum(r.n_chunks)}</td>
      <td class="small">${r.indexes.length ? html.join(r.indexes.map(i => `#${i}`), ", ") : html`<span class="muted">없음</span>`}</td><td class="num">${r.seconds}초</td></tr>`)}</table></div>`;
}

async function cLoad() {
  const box = $("#c-list");
  if (!colId()) return box.replaceChildren();
  ui.loading(box);
  try {
    const r = await api(`/api/docintel/collections/${colId()}/status`);
    if (!r.chunk_sets.length) return ui.empty(box, "준비된 청크 세트가 없습니다", { href: `/rag/collections/${colId()}`, label: "청크 세트 만들기" });
    box.innerHTML = html`<div class="table-wrap"><table><tr><th>청크 세트</th><th class="num">청크</th><th>마지막 갱신</th><th>상태</th><th class="num">추가</th><th class="num">바뀜</th><th class="num">삭제</th><th></th></tr>
      ${r.chunk_sets.map(c => html`<tr><td>#${c.id} ${c.name}</td><td class="num">${fmtNum(c.n_chunks)}</td><td class="small">${c.refreshed_at ? fmtDate(c.refreshed_at) : html`<span class="muted">만든 뒤 갱신 안 함</span>`}</td>
        <td>${c.up_to_date ? html`<span class="badge ok">최신</span>` : html`<span class="badge warn">최신 아님</span>`}</td>
        <td class="num">${n0(c.added.length)}</td><td class="num">${n0(c.changed.length)}</td><td class="num">${n0(c.removed.length)}</td>
        <td><button class="btn sm${c.up_to_date ? "" : " primary"}" data-refresh="${c.id}">증분 갱신</button></td></tr>`)}</table></div>`;
  } catch (e) { ui.error(box, e); }
}
$("#c-reload").onclick = () => cLoad();
$("#c-list").addEventListener("click", async e => {
  const b = e.target.closest("[data-refresh]");
  if (!b) return;
  await runJobInto(b, `/api/docintel/chunk-sets/${b.dataset.refresh}/refresh`, undefined, $("#c-progress"), r => {
    $("#c-out").innerHTML = refreshTable([r]);
    toast(`증분 갱신 완료 · ${r.seconds}초`, "ok");
    cLoad();
  }).catch(() => {});
});

// ── 문서 메타데이터 ────────────────────────────────────────────────────
const LISTS = new Set(["acl", "product_model"]);
const shown = (k, v) => (LISTS.has(k) ? (v || []).join(", ") : v ?? "");

async function mLoad() {
  const box = $("#m-list");
  if (!colId()) { box.replaceChildren(); $("#m-facets").replaceChildren(); return; }
  ui.loading(box);
  try {
    dMeta = await api(`/api/docintel/collections/${colId()}/meta`);
    mFacets(dMeta.facets);
    mRender();
  } catch (e) { ui.error(box, e); }
}

function mFacets(f) {
  const chips = (label, vals) => (vals?.length ? html`<div class="small"><span class="muted">${label}:</span> ${html.join(vals.map(v => html`<span class="badge muted">${v}</span>`), " ")}</div>` : "");
  // 입력 칸의 자동 완성 — 같은 값을 다르게 적어(인사팀 · 인사) 필터가 갈라지지 않게
  const dl = (k, vals) => html`<datalist id="m-dl-${k}">${(vals || []).map(v => html`<option value="${v}"></option>`)}</datalist>`;
  $("#m-facets").innerHTML = html`<div class="stack gap-1">
    <div class="small">문서 ${fmtNum(f.n_docs)}개 · 새 판에 밀린 문서 ${fmtNum(f.n_superseded)}개${f.date_min ? html` · 날짜 ${f.date_min} ~ ${f.date_max}` : ""}</div>
    ${chips("종류", f.doc_type)}${chips("부서", f.dept)}${chips("제품 모델", f.product_model)}${chips("권한 그룹", f.acl)}${chips("판 묶음", f.version_group)}
    ${["doc_type", "dept", "product_model", "acl", "version_group"].map(k => dl(k, f[k]))}</div>`;
}

function mRender() {
  const box = $("#m-list");
  const q = $("#m-q").value.trim().toLowerCase();
  const docs = dMeta.documents.filter(d => !q || d.filename.toLowerCase().includes(q));
  if (!dMeta.documents.length) return ui.empty(box, "문서가 없습니다", { href: `/rag/collections/${colId()}`, label: "문서 올리기" });
  if (!docs.length) return ui.empty(box, "찾는 이름의 문서가 없습니다");
  const fields = Object.entries(dMeta.fields);
  const cell = (d, k, label) => {
    if (k === "superseded") return html`<td><input type="checkbox" data-k="${k}" aria-label="${d.filename} ${label}"${d[k] ? html` checked` : ""}></td>`;
    const ph = k === "date" ? html` placeholder="YYYY-MM-DD"` : "";
    return html`<td><input class="${k === "date" ? "w-lg" : "w-xl"}" data-k="${k}" value="${shown(k, d[k])}" list="m-dl-${k}" aria-label="${d.filename} ${label}"${ph}></td>`;
  };
  box.innerHTML = html`<div class="table-wrap scroll-lg"><table><tr><th>#</th><th>파일</th>${fields.map(([, label]) => html`<th>${label}</th>`)}<th></th></tr>
    ${docs.slice(0, 300).map(d => html`<tr data-doc="${d.document_id}"><td>${d.document_id}</td><td class="small break-all">${d.filename}</td>
      ${fields.map(([k, label]) => cell(d, k, label))}<td><button class="btn sm" data-save="${d.document_id}">저장</button></td></tr>`)}</table></div>
    ${docs.length > 300 ? html`<div class="small muted">앞의 300개만 보입니다 — 이름으로 찾아 좁히세요.</div>` : ""}`;
}
$("#m-q").addEventListener("input", () => dMeta && mRender());

$("#m-list").addEventListener("click", async e => {
  const b = e.target.closest("[data-save]");
  if (!b) return;
  const tr = b.closest("tr");
  const values = Object.fromEntries($$("[data-k]", tr).map(el => [el.dataset.k, el.type === "checkbox" ? el.checked : el.value]));
  const r = await busy(b, () => api(`/api/docintel/documents/${b.dataset.save}/meta`, { method: "PATCH", body: { values } }));
  // 다시 불러와 저장된 값(정규화 결과: 쉼표 목록 · 앞뒤 공백)으로 표를 맞추고, 값 목록(facet)도 새로
  toast(`문서 #${r.document_id} 메타데이터를 저장했습니다`, "ok");
  dMeta = await api(`/api/docintel/collections/${colId()}/meta`);
  mFacets(dMeta.facets);
  mRender();
});

// 컬렉션이 하나도 없으면 onDetail 이 불리지 않는다 — 그때도 '컬렉션 만들기' 안내가 보이게
setupCollectionPickers({ col: $("#d-col"), onDetail: () => { sLoad(); cLoad(); mLoad(); } }).then(d => { if (!d) sLoad(); });
