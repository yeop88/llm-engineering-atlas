// 컬렉션 상세 ⑤ 평가: 평가 세트 만들기·검토 (rag.js 의 col · load 를 함께 쓴다)
let evSets = [];
let evTimer = null;
const EV_METHOD = { llm: "LLM 생성", sentence: "문장 추출", manual: "직접 입력", import: "가져오기" };
const EV_TYPE = { fact: "사실 확인", paraphrase: "다른 표현", situation: "상황 설명형", sentence: "문장 그대로", manual: "직접 입력" };
const EV_HINT = {
  llm: "청크 세트에서 문서마다 골고루 지문을 골라, 지문마다 고른 유형별로 질문 하나와 근거 문장을 만듭니다. 정답은 문서와 근거 문장으로 기록하므로 다른 청크 세트·인덱스 평가에도 그대로 씁니다. 만든 뒤 검토해서 이상한 질문은 지우세요.",
  sentence: "지문의 문장 하나를 그대로 질문으로 씁니다. 단어가 그대로 겹쳐 매우 쉬운 세트라서 파이프라인이 동작하는지 점검하는 용도입니다. 모델 비교에는 LLM 생성이나 실제 질문을 쓰세요.",
  manual: "실제 사용자 질문과 정답 문서를 적습니다. 가장 믿을 만한 평가 세트입니다. 근거 문장을 적으면 '근거를 담은 청크를 찾았는지'도 평가합니다.",
  import: "다른 곳에서 만든 평가 세트나 내보내기한 파일을 가져옵니다. doc_ids 는 이 컬렉션의 문서 id 여야 합니다.",
};

function evMethodChanged() {
  const m = $("#e-method").value;
  $("#e-gen").hidden = !["llm", "sentence"].includes(m);
  $("#e-llm").hidden = m !== "llm";
  $("#e-manual").hidden = m !== "manual";
  $("#e-import").hidden = m !== "import";
  $("#e-hint").textContent = EV_HINT[m];
}
$("#e-method").addEventListener("change", evMethodChanged);

async function evLlmStatus() {
  const s = await api("/api/llm/status");
  $("#e-llm-status").innerHTML = s.default.error
    ? `<span class="badge warn">LLM 미설정</span> ${esc(s.default.error)}`
    : `<span class="badge ok">사용 가능</span> 기본: ${s.default.provider === "openai" ? "OpenAI 호환" : "Claude"} · <span class="mono">${esc(s.default.model)}</span>${s.default.base_url ? ` · ${esc(s.default.base_url)}` : ""}`;
}

function evRenderForm() {
  const ready = col.chunk_sets.filter(c => c.status === "ready");
  const cur = $("#e-cs").value;
  $("#e-cs").innerHTML = ready.map(c => `<option value="${c.id}">#${c.id} ${esc(c.name)} (${c.n_chunks})</option>`).join("") || '<option value="">준비된 청크 세트 없음</option>';
  if (cur && ready.some(c => String(c.id) === cur)) $("#e-cs").value = cur;
}

async function evLoad() {
  evSets = await api(`/api/collections/${COLLECTION_ID}/eval-sets`);
  $("#e-rows").innerHTML = evSets.map(s => `<tr>
    <td>${s.id}</td><td><b>${esc(s.name)}</b>${s.stats?.generation?.failed ? ` <span class="badge warn" title="${esc((s.stats.generation.errors || []).join("\n"))}">실패 ${s.stats.generation.failed}</span>` : ""}</td>
    <td class="small">${EV_METHOD[s.method] || s.method}${s.config?.llm ? `<div class="mono muted">${esc(s.config.llm.model)}</div>` : ""}</td>
    <td class="num">${s.n_items}</td><td class="num">${s.stats?.lexical_overlap ?? "-"}</td>
    <td>${statusBadge(s.status, s.error)}</td>
    <td class="right nowrap">${s.status === "ready" ? `<button class="btn sm" onclick="evView(${s.id})">검토</button><a class="btn sm" href="/api/eval-sets/${s.id}/export">내보내기</a>` : ""}<button class="btn sm danger" onclick="evDelete(${s.id})">삭제</button></td></tr>`).join("")
    || '<tr><td colspan="7" class="empty">평가 세트가 없습니다</td></tr>';
  clearTimeout(evTimer);
  if (evSets.some(s => s.status === "building")) evTimer = setTimeout(evLoad, 1500);
  if (typeof evRenderRunner === "function") evRenderRunner();
}

// 직접 입력: "질문 | 파일1, 파일2 | 근거"
function evParseManual() {
  const byName = Object.fromEntries(col.documents.map(d => [d.filename.toLowerCase(), d.id]));
  const items = [], errors = [];
  $("#e-lines").value.split("\n").map(s => s.trim()).filter(Boolean).forEach((line, i) => {
    const [q, files = "", ev = ""] = line.split("|").map(s => s.trim());
    const ids = files.split(",").map(f => f.trim().toLowerCase()).filter(Boolean).map(f => byName[f] ?? (/^\d+$/.test(f) ? +f : null));
    if (!q || !ids.length || ids.includes(null)) errors.push(`${i + 1}번째 줄: 질문과 이 컬렉션의 파일 이름이 필요합니다`);
    else items.push({ query: q, doc_ids: ids, evidence: ev });
  });
  return { items, errors };
}

$("#e-create").onclick = async e => {
  const m = $("#e-method").value;
  const name = $("#e-name").value.trim();
  if (m === "llm" || m === "sentence") {
    if (!$("#e-cs").value) return toast("청크 세트를 먼저 만드세요", "err");
    const styles = [...document.querySelectorAll('input[name="e-style"]:checked')].map(x => x.value);
    if (m === "llm" && !styles.length) return toast("질문 유형을 하나 이상 고르세요", "err");
    await busy(e.target, () => api(`/api/collections/${COLLECTION_ID}/eval-sets/generate`, { method: "POST", body: {
      method: m, name, chunk_set_id: +$("#e-cs").value, n_passages: +$("#e-n").value, min_chars: +$("#e-min").value,
      styles: m === "llm" ? styles : undefined, provider: $("#e-provider").value || null, model: $("#e-model").value.trim() || null, concurrency: +$("#e-conc").value,
    } }));
    toast("생성을 시작했습니다", "ok");
  } else if (m === "manual") {
    const { items, errors } = evParseManual();
    if (errors.length) return toast(errors.slice(0, 3).join("\n"), "err");
    if (!items.length) return toast("질문을 입력하세요", "err");
    await busy(e.target, () => api(`/api/collections/${COLLECTION_ID}/eval-sets`, { method: "POST", body: { name: name || "직접 입력", method: "manual", items } }));
    $("#e-lines").value = "";
  } else {
    const f = $("#e-file").files[0];
    if (!f) return toast("파일을 고르세요", "err");
    let data;
    try { data = JSON.parse(await f.text()); } catch { return toast("JSON 형식이 아닙니다", "err"); }
    const items = (data.items || data).map(it => ({ query: it.query, doc_ids: it.doc_ids, evidence: it.evidence || "", type: it.type || "manual" }));
    await busy(e.target, () => api(`/api/collections/${COLLECTION_ID}/eval-sets`, { method: "POST", body: { name: name || data.name || f.name, method: "import", items } }));
  }
  evLoad();
};

async function evDelete(id) {
  if (!confirm(`평가 세트 #${id} 를 삭제할까요?`)) return;
  await api(`/api/eval-sets/${id}`, { method: "DELETE" }); toast("삭제했습니다", "ok"); evLoad();
}

// 검토: 질문을 읽고 이상한 것은 체크 해제 후 저장
let evEditing = null;
async function evView(id) {
  evEditing = await api(`/api/eval-sets/${id}`);
  const s = evEditing;
  const g = s.stats.generation;
  $("#dlg-title").textContent = `평가 세트 #${s.id} · ${s.name}`;
  $("#dlg-body").innerHTML = `<div class="small muted" style="margin-bottom:8px">질문 ${s.n_items}개 · 문서 ${s.stats.documents}개 · 유형 ${Object.entries(s.stats.by_type || {}).map(([k, v]) => `${EV_TYPE[k] || k} ${v}`).join(", ")}
      ${g?.calls != null ? ` · LLM 호출 ${g.calls}회, 토큰 입력 ${fmtNum(g.input_tokens)} / 출력 ${fmtNum(g.output_tokens)}${g.empty ? `, 질문 없음 ${g.empty}` : ""}${g.evidence_fixed ? `, 근거 보정 ${g.evidence_fixed}` : ""}` : ""}</div>
    <div class="table-wrap" style="max-height:60vh"><table>
      <tr><th><input type="checkbox" checked onchange="document.querySelectorAll('.ev-keep').forEach(c => c.checked = this.checked)" aria-label="전체"></th><th>질문</th><th>유형</th><th>정답 문서</th><th>근거 문장</th><th class="num">겹침</th></tr>
      ${s.items.map((it, i) => `<tr><td><input type="checkbox" class="ev-keep" data-i="${i}" checked></td><td>${esc(it.query)}</td><td class="small nowrap">${EV_TYPE[it.type] || esc(it.type || "")}</td>
        <td class="small">${esc(it.filename || it.doc_ids.join(","))}</td><td class="small muted">${esc((it.evidence || "").slice(0, 120))}${it.evidence_exact === false ? ' <span class="badge warn" title="LLM 이 적은 근거가 원문과 달라 가장 비슷한 원문 문장으로 바꿨습니다">보정</span>' : ""}</td>
        <td class="num mono small">${it.lexical_overlap ?? "-"}</td></tr>`).join("")}
    </table></div>
    <div class="row" style="margin-top:10px"><span class="small muted">체크 해제한 질문을 빼고 저장합니다.</span><span class="spacer"></span><button class="btn primary" onclick="evSaveReview(this)">저장</button></div>`;
  $("#dlg").showModal();
}
async function evSaveReview(btn) {
  const keep = [...document.querySelectorAll(".ev-keep")].filter(c => c.checked).map(c => evEditing.items[+c.dataset.i]);
  if (!keep.length) return toast("질문이 하나 이상 있어야 합니다", "err");
  await busy(btn, () => api(`/api/eval-sets/${evEditing.id}`, { method: "PATCH", body: { items: keep.map(({ query, doc_ids, evidence, type }) => ({ query, doc_ids, evidence: evidence || "", type: type || "manual" })) } }));
  $("#dlg").close(); toast(`${keep.length}개로 저장했습니다`, "ok"); evLoad();
}

// rag.js 의 load() 가 다시 불릴 때(청크 세트·인덱스 변경) 평가 탭도 갱신
const _ragLoad = load;
load = async () => { await _ragLoad(); evRenderForm(); if (typeof evRenderRunner === "function") evRenderRunner(); };
(async () => {
  while (!col) await new Promise(r => setTimeout(r, 100));
  evMethodChanged(); evRenderForm(); evLlmStatus(); evLoad();
})();
