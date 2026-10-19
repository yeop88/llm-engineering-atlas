// rag/collections.html 화면 스크립트 (템플릿에서 옮김 — 화면 JS 는 static/js/<영역>/<화면>.js)
const DOMAINS = { general: "일반", internal: "사내 문서", legal: "법률", support: "고객·AS 문의", product: "제품·매뉴얼", other: "기타" };
let cols = [];
async function load() {
  let stores;
  [cols, stores] = await Promise.all([api("/api/collections"), api("/api/vector-stores")]);
  $("#rows").innerHTML = cols.map(c => `<tr>
    <td><a href="/rag/collections/${c.id}"><b>${esc(c.name)}</b></a><div class="small muted">${esc(c.description)}</div></td>
    <td><span class="badge muted">${DOMAINS[c.domain] || c.domain}</span></td>
    <td class="num">${c.n_documents}</td><td class="num">${fmtNum(c.n_chars)}</td><td class="num">${c.n_chunk_sets}</td><td class="num">${c.n_indexes}</td>
    <td class="small nowrap">${fmtDate(c.created_at)}</td>
    <td class="right nowrap"><a class="btn sm primary" href="/rag/collections/${c.id}#t-search">검색</a> <a class="btn sm" href="/rag/collections/${c.id}">관리</a>
      <button class="btn sm danger" onclick="del(${c.id})">삭제</button></td></tr>`).join("")
    || '<tr><td colspan="8" class="empty">컬렉션이 없습니다. 위에서 새 컬렉션을 만든 뒤, 문서를 올리거나 공개 자료(법령 · 판례)를 가져오세요.</td></tr>';
  $("#stores").innerHTML = stores.map(s => `<div class="row between">
    <span><b>${esc(s.label)}</b> ${s.default ? '<span class="badge">기본</span>' : ""}</span>
    <span>${s.ok ? `<span class="badge ok">연결됨</span> <span class="muted">${esc(s.version)}</span>` : `<span class="badge ${s.configured ? "err" : "muted"}">${s.configured ? "연결 실패" : "설정 안 됨"}</span>`}</span></div>
    <div class="muted" style="margin:-6px 0 4px">${esc(s.detail)}</div>`).join("");
}
// 이름을 onclick 글자로 넘기면 작은따옴표가 든 이름에서 스크립트가 깨져, 목록에서 찾는다
async function del(id) {
  const name = cols.find(c => c.id === id)?.name ?? `#${id}`;
  if (!(await ui.confirm(`컬렉션 '${name}' 과 그 안의 문서·청크·인덱스(벡터 DB 데이터 포함)를 모두 삭제할까요?`, { ok: "삭제", danger: true, title: "삭제" }))) return;
  await api(`/api/collections/${id}`, { method: "DELETE" });
  toast("삭제했습니다", "ok"); load();
}
$("#c-create").onclick = async e => {
  const name = $("#c-name").value.trim();
  if (!name) return toast("이름을 입력하세요", "err");
  const r = await busy(e.target, () => api("/api/collections", { method: "POST", body: { name, domain: $("#c-domain").value, description: $("#c-desc").value } }));
  location.href = `/rag/collections/${r.id}`;
};
load();
