// apps/keywords.html 화면 스크립트 (템플릿에서 옮김 — 화면 JS 는 static/js/<영역>/<화면>.js)
let kSrc, kModel, sModel, kwResult = null;
const bindRange = (id, out) => { const f = () => ($(out).textContent = $(id).value); $(id).addEventListener("input", f); f(); };
bindRange("#k-div", "#k-div-v"); bindRange("#s-div", "#s-div-v");
const reEsc = s => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
// 키워드를 본문에서 강조 (긴 키워드부터, 대소문자 무시)
function highlight(text, words) {
  const ws = [...new Set(words)].sort((a, b) => b.length - a.length).filter(Boolean);
  if (!ws.length) return esc(text);
  const re = new RegExp(`(${ws.map(reEsc).join("|")})`, "gi");
  return text.split(re).map((part, i) => (i % 2 ? `<mark>${esc(part)}</mark>` : esc(part))).join("");
}

$("#k-run").onclick = async e => {
  const r = await Apps.run(e.target, $("#k-progress"), "/api/apps/keywords", {
    ...kModel(), source: kSrc.get(), top_n: +$("#k-n").value, diversity: +$("#k-div").value, max_words: +$("#k-words").value, min_freq: +$("#k-freq").value,
  });
  if (!r) return;
  kwResult = r;
  $("#k-out").innerHTML = `<div class="card stack">
    <div class="row between"><h2>결과</h2><span class="small muted">문서 ${r.n_items}개 · 후보 ${r.summary.vocab}개 · ${r.seconds}s <button class="btn sm" onclick="downloadKw()">CSV</button></span></div>
    ${r.top_tags.length ? `<div><div class="small muted" style="margin-bottom:4px">여러 문서에 공통으로 뽑힌 키워드</div>${r.top_tags.filter(t => t.docs > 1).map(t => `<span class="badge">${esc(t.keyword)} ×${t.docs}</span>`).join(" ") || '<span class="small muted">없음 (문서마다 주제가 다름)</span>'}</div>` : ""}
    ${r.items.map(it => `<div class="card" style="padding:12px">
      <div class="row between"><b>${esc(it.label || it.filename || "#" + it.key)}</b><span class="small muted">후보 ${it.n_candidates}개</span></div>
      <div style="margin:6px 0">${it.keywords.map(k => `<span class="badge ok" title="문서와 유사도 ${k.score} · 등장 ${k.freq}회">${esc(k.keyword)} <span class="mono">${k.score.toFixed(2)}</span></span>`).join(" ") || '<span class="small muted">후보 없음</span>'}</div>
      <div class="small" style="line-height:1.8">${highlight(it.text.slice(0, 600), it.keywords.map(k => k.keyword))}${it.text.length > 600 ? "…" : ""}</div>
    </div>`).join("")}
  </div>`;
};
function downloadKw() {
  const q = v => `"${String(v).replace(/"/g, '""')}"`;
  const lines = ["key,label,rank,keyword,score,freq", ...kwResult.items.flatMap(it => it.keywords.map((k, i) => [q(it.key), q(it.label || it.filename || ""), i + 1, q(k.keyword), k.score, k.freq].join(",")))];
  const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob(["﻿" + lines.join("\n")], { type: "text/csv" })); a.download = "keywords.csv"; a.click();
}

const countSum = () => { const t = $("#s-text").value; $("#s-count").textContent = t ? `${t.length.toLocaleString()}자` : ""; };
$("#s-text").addEventListener("input", countSum);
$("#s-example").onclick = async () => { const p = await api("/api/apps/presets/summary_article"); $("#s-text").value = p.text; countSum(); };
$("#s-run").onclick = async e => {
  const text = $("#s-text").value.trim();
  if (!text) return toast("요약할 글을 입력하세요", "err");
  const r = await Apps.run(e.target, $("#s-progress"), "/api/apps/summary", {
    ...sModel(), text, n: +$("#s-n").value, diversity: +$("#s-div").value, lead_bonus: $("#s-lead").checked ? 0.3 : 0,
  });
  if (!r) return;
  const pc = v => (v * 100).toFixed(1) + "%";
  $("#s-out").innerHTML = `<div class="card stack">
    <div class="row between"><h2>요약</h2><span class="small muted">문장 ${r.n_items}개 중 ${r.picked.length}개 · ${r.seconds}s <button class="btn sm" onclick="navigator.clipboard.writeText(${esc(JSON.stringify(r.picked.join(" ")))}).then(() => toast('복사했습니다', 'ok'))">복사</button></span></div>
    <ol>${r.picked.map(s => `<li style="margin:4px 0">${esc(s)}</li>`).join("")}</ol>
    <div class="grid cols-3">
      <div class="stat"><div class="label">의미 대표성</div><div class="value">${r.coverage.toFixed(3)}</div><div class="small muted">요약 벡터와 전체 글 벡터의 유사도</div></div>
      <div class="stat"><div class="label">압축률</div><div class="value">${pc(r.compression)}</div><div class="small muted">요약 글자 수 ÷ 전체</div></div>
    </div>
    <h3>문장별 중심성 <span class="small muted">막대 = 다른 문장들과 얼마나 닮았는지 (최댓값 1), 강조 = 요약에 고른 문장</span></h3>
    <table>${r.sentences.map(s => `<tr${s.selected ? ' style="background:color-mix(in srgb, var(--accent) 10%, transparent)"' : ""}>
      <td class="num small muted">${s.index + 1}</td><td class="small">${s.selected ? "<b>" : ""}${esc(s.text)}${s.selected ? "</b>" : ""}</td>
      <td style="width:160px"><div style="background:var(--code);border-radius:4px"><div class="bar" style="width:${Math.max(2, s.centrality * 100)}%"></div></div></td>
      <td class="num mono small">${s.centrality.toFixed(2)}</td></tr>`).join("")}</table>
  </div>`;
};

(async () => {
  initTabs();
  kSrc = await Apps.sourcePicker($("#k-src"), { app: "keywords", labels: "optional", placeholder: "문서 하나를 한 줄에 (라벨은 [이름] 텍스트)" });
  kModel = await Apps.modelPicker($("#k-model"), $("#k-dim"));
  sModel = await Apps.modelPicker($("#s-model"), $("#s-dim"));
})();
