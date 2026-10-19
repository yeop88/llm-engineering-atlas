// apps/dedup.html 화면 스크립트 (템플릿에서 옮김 — 화면 JS 는 static/js/<영역>/<화면>.js)
let dSrc, pSrc, dModel, pModel, dedupResult = null;
const KIND = { copy: ["완전 중복", "err"], paraphrase: ["의역", "warn"] };
const PKIND = { copy: ["복사", "err", "var(--status-critical)"], paraphrase: ["의역", "warn", "#fab219"], original: ["독창", "muted", "transparent"] };
const bindRange = (id, out) => { const f = () => ($(out).textContent = $(id).value); $(id).addEventListener("input", f); f(); };
bindRange("#d-th", "#d-th-v"); bindRange("#p-th", "#p-th-v"); bindRange("#p-cl", "#p-cl-v");

$("#d-run").onclick = async e => {
  const r = await Apps.run(e.target, $("#d-progress"), "/api/apps/dedup", { ...dModel(), source: dSrc.get(), threshold: +$("#d-th").value, keep: $("#d-keep").value });
  if (!r) return;
  dedupResult = r;
  $("#d-out").innerHTML = `<div class="card stack">
    <div class="row between"><h2>결과</h2><span class="small muted">${r.n_items}개 · ${r.seconds}s <button class="btn sm" onclick="downloadKept()">중복 제거 목록 받기</button></span></div>
    <div class="grid cols-4">
      <div class="stat"><div class="label">중복 그룹</div><div class="value">${r.n_groups}</div></div>
      <div class="stat"><div class="label">지울 수 있는 항목</div><div class="value">${r.n_remove}</div><div class="small muted">전체의 ${(r.summary.dedup_ratio * 100).toFixed(1)}%</div></div>
      <div class="stat"><div class="label">남는 항목</div><div class="value">${r.n_keep}</div></div>
      <div class="stat"><div class="label">유형</div><div class="value text-lg mt-2">완전 중복 ${r.kinds.copy || 0} · 의역 ${r.kinds.paraphrase || 0}</div></div>
    </div>
    <details><summary>임계값 정하기 참고 — 가장 가까운 이웃 유사도 분포 (중앙값 ${r.nn_similarity.median}, 하위 10% ${r.nn_similarity.p10}, 상위 10% ${r.nn_similarity.p90})</summary>
      <div class="small muted my-2">각 텍스트와 가장 비슷한 다른 텍스트의 유사도입니다. 모델마다 분포가 크게 달라서(어떤 모델은 관계없는 문장끼리도 0.8 안팎) 같은 임계값이 모델마다 다른 의미가 됩니다. 중복이 거의 없는 데이터라면 중앙값보다 충분히 높은 값을 임계값으로 잡으세요. 막대 = 현재 임계값 이상.</div>
      ${(() => { const mx = Math.max(1, ...r.nn_similarity.hist.map(h => h.n)); return r.nn_similarity.hist.map(h => `<div class="row small nowrap-row gap-2"><span class="mono w-md">${h.from.toFixed(2)}–${h.to.toFixed(2)}</span>
        <div class="grow bg-code"><div class="bar" style="width:${Math.max(h.n ? 2 : 0, h.n / mx * 100)}%;${h.from + 1e-9 >= r.threshold || h.to > r.threshold ? "" : "opacity:.35"}"></div></div><span class="mono w-xs text-right">${h.n}</span></div>`).join(""); })()}
    </details>
    ${r.groups.map((g, n) => `<div class="card p-2"><div class="small muted">그룹 ${n + 1} · ${g.size}개</div>
      ${g.members.map(m => `<div class="row small nowrap-row gap-2" style="padding:3px 0">
        ${m.keep ? '<span class="badge ok">남김</span>' : `<span class="badge ${KIND[m.kind][1]}">${KIND[m.kind][0]}</span>`}
        <span class="grow">${esc(m.text)}${m.filename ? ` <span class="muted">(${esc(m.filename)})</span>` : ""}</span>
        ${m.keep ? "" : `<span class="mono muted nowrap">의미 ${m.similarity.toFixed(3)} · 글자 ${m.lexical.toFixed(2)}</span>`}</div>`).join("")}</div>`).join("") || '<div class="empty">이 임계값에서는 중복이 없습니다. 임계값을 낮춰 보세요.</div>'}
  </div>`;
};
function downloadKept() {
  const keep = new Set(dedupResult.keep_keys);
  const src = dSrc.get();
  const lines = src.type === "texts" ? src.items.filter(it => keep.has(it.id)).map(it => it.text) : dedupResult.keep_keys;
  const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob(["﻿" + lines.join("\n")], { type: "text/plain" })); a.download = "deduplicated.txt"; a.click();
}

$("#p-run").onclick = async e => {
  const suspect = $("#p-suspect").value.trim();
  if (!suspect) return toast("검사할 글을 입력하세요", "err");
  const r = await Apps.run(e.target, $("#p-progress"), "/api/apps/plagiarism", { ...pModel(), suspect, reference: pSrc.get(), threshold: +$("#p-th").value, copy_lex: +$("#p-cl").value });
  if (!r) return;
  const pc = v => (v * 100).toFixed(1) + "%";
  $("#p-out").innerHTML = `<div class="card stack">
    <div class="row between"><h2>결과</h2><span class="small muted">문장 ${r.n_suspect}개 · 참고 문장 ${r.n_reference}개 · ${r.seconds}s</span></div>
    <div class="grid cols-3">
      <div class="stat"><div class="label">표절 의심 비율 (글자 기준)</div><div class="value">${pc(r.ratio.total)}</div></div>
      <div class="stat"><div class="label">복사</div><div class="value">${pc(r.ratio.copy)}</div></div>
      <div class="stat"><div class="label">의역</div><div class="value">${pc(r.ratio.paraphrase)}</div></div>
    </div>
    <h3>문장별 판정 <span class="small muted">마우스를 올리면 가장 비슷한 원문</span></h3>
    <div style="line-height:2">${r.sentences.map(s => `<span title="${esc(`원문(${s.source}): ${s.match}\n의미 유사도 ${s.similarity} · 글자 일치 ${s.lexical}`)}"
      style="background:color-mix(in srgb, ${PKIND[s.kind][2]} ${s.kind === "original" ? 0 : 22}%, transparent);border-radius:4px;padding:2px 2px">${s.kind !== "original" ? `<span class="badge ${PKIND[s.kind][1]}">${PKIND[s.kind][0]}</span> ` : ""}${esc(s.text)}</span> `).join("")}</div>
    ${r.sources.length ? `<h3>출처별</h3><table><tr><th>원문</th><th class="num">문장</th><th class="num">글자</th></tr>${r.sources.map(x => `<tr><td>${x.label ? `<b>${esc(x.label)}</b> ` : ""}${x.filename ? `<b>${esc(x.filename)}</b> ` : ""}<span class="small muted">${esc(x.text.slice(0, 80))}…</span></td><td class="num">${x.sentences}</td><td class="num">${x.chars}</td></tr>`).join("")}</table>` : ""}
  </div>`;
};

(async () => {
  initTabs();
  dSrc = await Apps.sourcePicker($("#d-src"), { app: "dedup", labels: "none" });
  pSrc = await Apps.sourcePicker($("#p-src"), { app: "plagiarism", labels: "optional" });
  pSrc.root.addEventListener("preset", e => { if (e.detail.suspect) $("#p-suspect").value = e.detail.suspect; });
  dModel = await Apps.modelPicker($("#d-model"), $("#d-dim"));
  pModel = await Apps.modelPicker($("#p-model"), $("#p-dim"));
})();
