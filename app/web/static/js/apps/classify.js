// apps/classify.html 화면 스크립트 (템플릿에서 옮김 — 화면 JS 는 static/js/<영역>/<화면>.js)
let trSrc, zsSrc, trModel, zsModel;
const pctf = v => (v * 100).toFixed(1) + "%";

function metricsHtml(m, labels) {
  const max = Math.max(1, ...m.confusion.flat());
  return `<div class="grid cols-2">
    <div><h3>라벨별 성능</h3><div class="table-wrap"><table><tr><th>라벨</th><th class="num">정밀도</th><th class="num">재현율</th><th class="num">F1</th><th class="num">개수</th></tr>
      ${m.per_class.map(c => `<tr><td>${esc(c.label)}</td><td class="num">${pctf(c.precision)}</td><td class="num">${pctf(c.recall)}</td><td class="num ${c.f1 < 0.7 ? "rank-bad" : ""}">${pctf(c.f1)}</td><td class="num">${c.support}</td></tr>`).join("")}</table></div></div>
    <div><h3>혼동행렬 <span class="small muted">행 = 정답, 열 = 예측</span></h3><div class="scroll"><table class="heatmap"><tr><th></th>${labels.map(l => `<th title="${esc(l)}">${esc(l)}</th>`).join("")}</tr>
      ${m.confusion.map((row, i) => `<tr><th>${esc(labels[i])}</th>${row.map((v, j) => `<td style="background:${v ? `color-mix(in srgb, ${i === j ? "var(--series-1)" : "var(--status-critical)"} ${Math.round(15 + 70 * v / max)}%, transparent)` : "transparent"}" title="정답 ${esc(labels[i])} → 예측 ${esc(labels[j])}">${v || ""}</td>`).join("")}</tr>`).join("")}</table></div></div>
  </div>`;
}
function errorsHtml(errs) {
  if (!errs?.length) return "";
  return `<details class="mt-3"><summary>틀린 예시 ${errs.length}개</summary><div class="table-wrap mt-2"><table><tr><th>텍스트</th><th>정답</th><th>예측</th></tr>
    ${errs.map(e => `<tr><td class="small">${esc(e.text)}</td><td><span class="badge muted">${esc(e.gold)}</span></td><td><span class="badge err">${esc(e.pred)}</span></td></tr>`).join("")}</table></div></details>`;
}

// ── 학습 ──
$("#tr-method").addEventListener("change", e => ($("#tr-k-wrap").hidden = e.target.value !== "knn"));
$("#tr-run").onclick = async e => {
  const body = { ...trModel(), source: trSrc.get(), method: $("#tr-method").value, k: +$("#tr-k").value, save: $("#tr-save").checked, name: $("#tr-name").value };
  const r = await Apps.run(e.target, $("#tr-progress"), "/api/apps/classify/train", body);
  if (!r) return;
  const m = r.metrics;
  $("#tr-out").innerHTML = `<div class="card stack">
    <div class="row between"><h2>결과 · ${esc({ logreg: "로지스틱 회귀", centroid: "중심점", knn: "kNN" }[r.method])}</h2><span class="small muted">${r.n_items}개 · ${r.seconds}s</span></div>
    ${r.warning ? `<div class="warnbox">${esc(r.warning)}</div>` : ""}
    ${m ? `<div class="grid cols-3"><div class="stat"><div class="label">정확도 (${m.folds}겹 교차검증)</div><div class="value">${pctf(m.accuracy)}</div></div>
      <div class="stat"><div class="label">Macro F1</div><div class="value">${pctf(m.macro_f1)}</div></div>
      <div class="stat"><div class="label">라벨 수</div><div class="value">${r.labels.length}</div><div class="small muted">${Object.entries(r.counts).map(([k, v]) => `${esc(k)} ${v}`).join(" · ")}</div></div></div>
      ${metricsHtml(m, r.labels)}${errorsHtml(r.errors)}` : ""}
    ${r.saved ? `<div class="warnbox" style="border-color:var(--ok)">분류기 #${r.saved.id} "${esc(r.saved.name)}" 저장됨 — <a href="#t-saved">저장된 분류기</a>에서 예측하거나 API 로 호출하세요.</div>` : ""}
  </div>`;
  loadSaved();
};

// ── 제로샷 ──
function parseLabels() {
  return $("#zs-labels").value.split("\n").map(s => s.trim()).filter(Boolean).map(l => {
    const i = l.indexOf(":");
    return i > 0 ? { name: l.slice(0, i).trim(), description: l.slice(i + 1).trim() } : { name: l, description: "" };
  });
}
$("#zs-run").onclick = async e => {
  const labels = parseLabels();
  if (labels.length < 2) return toast("라벨을 2개 이상 적으세요", "err");
  const r = await Apps.run(e.target, $("#zs-progress"), "/api/apps/classify/zero-shot", { ...zsModel(), source: zsSrc.get(), labels });
  if (!r) return;
  const m = r.metrics;
  $("#zs-out").innerHTML = `<div class="card stack"><div class="row between"><h2>제로샷 결과</h2><span class="small muted">${r.n_items}개 · ${r.seconds}s</span></div>
    ${m ? `<div class="grid cols-2"><div class="stat"><div class="label">정확도</div><div class="value">${pctf(m.accuracy)}</div></div><div class="stat"><div class="label">Macro F1</div><div class="value">${pctf(m.macro_f1)}</div></div></div>${metricsHtml(m, r.labels)}${errorsHtml(r.errors)}` : ""}
    <details ${m ? "" : "open"}><summary>항목별 예측</summary><div class="table-wrap mt-2"><table><tr><th>텍스트</th><th>예측</th><th class="num">확신도</th><th>다른 후보</th></tr>
      ${r.items.map(it => `<tr><td class="small">${esc(it.text)}</td><td><span class="badge ${it.label && it.label !== it.top[0].label ? "err" : "ok"}">${esc(it.top[0].label)}</span></td><td class="num">${pctf(it.confidence)}</td>
        <td class="small muted">${it.top.slice(1).map(t => `${esc(t.label)} ${pctf(t.p)}`).join(" · ")}</td></tr>`).join("")}</table></div></details></div>`;
};

// ── 저장된 분류기 ──
async function loadSaved() {
  const rows = await api("/api/apps/models?kind=classifier");
  $("#sv-rows").innerHTML = rows.map(m => `<tr><td>${m.id}</td><td><b>${esc(m.name)}</b></td><td class="small">${m.labels.map(esc).join(", ")}</td>
    <td class="small">${esc(m.method)} · <span class="mono">${esc(m.model_hf_id)}</span>${m.truncate_dim ? ` · ${m.truncate_dim}d` : ""}</td><td class="num">${m.n_train}</td>
    <td class="num">${m.metrics.accuracy != null ? pctf(m.metrics.accuracy) : "-"}</td><td class="small nowrap">${fmtDate(m.created_at)}</td>
    <td class="right"><button class="btn sm danger" onclick="delSaved(${m.id})">삭제</button></td></tr>`).join("") || '<tr><td colspan="8" class="empty">저장된 분류기가 없습니다. 퓨샷 학습 탭에서 만드세요.</td></tr>';
  $("#pd-model").innerHTML = rows.map(m => `<option value="${m.id}">#${m.id} ${esc(m.name)}</option>`).join("");
  updateApi();
}
function updateApi() {
  const id = $("#pd-model").value || "{id}";
  $("#pd-api").textContent = `curl -X POST ${location.origin}/api/apps/classifiers/${id}/predict \\\n  -H "Content-Type: application/json" \\\n  -d '{"texts": ["택배가 아직 안 왔어요"]}'`;
}
$("#pd-model").addEventListener("change", updateApi);
async function delSaved(id) {
  if (!(await ui.confirm(`분류기 #${id} 를 삭제할까요?`, { ok: "삭제", danger: true, title: "삭제" }))) return;
  await api(`/api/apps/models/${id}`, { method: "DELETE" }); toast("삭제했습니다", "ok"); loadSaved();
}
$("#pd-run").onclick = async e => {
  if (!$("#pd-model").value) return toast("저장된 분류기가 없습니다", "err");
  const texts = $("#pd-text").value.split("\n").map(s => s.trim()).filter(Boolean);
  const r = await busy(e.target, () => api(`/api/apps/classifiers/${$("#pd-model").value}/predict`, { method: "POST", body: { texts } }));
  $("#pd-out").innerHTML = `<div class="small muted">${r.seconds}s</div><table><tr><th>텍스트</th><th>예측</th><th class="num">확신도</th><th>다른 후보</th></tr>
    ${r.results.map(x => `<tr><td>${esc(x.text)}</td><td><span class="badge ok">${esc(x.label)}</span></td><td class="num">${pctf(x.confidence)}</td><td class="small muted">${x.top.slice(1).map(t => `${esc(t.label)} ${pctf(t.p)}`).join(" · ")}</td></tr>`).join("")}</table>`;
};

(async () => {
  initTabs();
  trSrc = await Apps.sourcePicker($("#tr-src"), { app: "classify", labels: "required", placeholder: "[긍정] 배송이 빨라요\n[부정] 일주일 만에 고장 났어요" });
  zsSrc = await Apps.sourcePicker($("#zs-src"), { app: "classify", labels: "optional" });
  zsSrc.root.addEventListener("preset", e => {
    if (e.detail.labels) $("#zs-labels").value = e.detail.labels.map(l => `${l.name}: ${l.description}`).join("\n");
  });
  trModel = await Apps.modelPicker($("#tr-model"), $("#tr-dim"));
  zsModel = await Apps.modelPicker($("#zs-model"), $("#zs-dim"));
  loadSaved();
})();
