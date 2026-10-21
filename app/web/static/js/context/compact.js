// context/compact.html 화면 스크립트 — 기록 압축 방법 비교(CX3), 세션 노트 쓰기 · 읽기(CX5)
const pct = v => (v == null ? "-" : `${(v * 100).toFixed(1)}%`);

$("#k-run").onclick = e => runJobInto(e.target, "/api/context/compact", {
  eval_set_id: +$("#k-set").value, max_queries: +$("#k-n").value || 20, provider: $("#k-provider").value || null, model: $("#k-model").value.trim() || null,
  steps: +$("#k-steps").value || 6, keep: +$("#k-keep").value, gold_at: +$("#k-gold").value, max_chars: +$("#k-chars").value || 6000,
}, $("#k-progress"), r => {
  $("#k-out").innerHTML = html`<div class="small muted">${r.eval_set} · ${r.model} · 질문 ${r.n} · 단계 ${r.steps} (정답 ${r.gold_at + 1}번째 · 최근 ${r.keep}단계 유지) · ${r.seconds}초 · run #${r.run_id}</div>
    <div class="table-wrap"><table><tr><th>방법</th><th>질문</th><th>정답률</th><th>맥락 글자</th><th>답 시간(초)</th><th>압축 시간(초)</th></tr>
    ${html.join(Object.values(r.results).map(d => html`<tr><td>${d.label}</td><td>${d.n}</td><td><b>${pct(d.quality)}</b></td><td>${d.context_chars}</td><td>${d.seconds}</td><td>${d.compact_seconds}</td></tr>`), "")}</table></div>`;
}).catch(err => ui.error($("#k-out"), err));

const sess = () => encodeURIComponent($("#n-session").value.trim());
function showNotes(r) {
  $("#n-out").innerHTML = r.notes.length ? html`<ul class="small">${html.join(r.notes.map(n => html`<li>#${n.id} ${n.text} <span class="muted">· ${n.source || "-"} · ${n.at}</span></li>`), "")}</ul>` : html`<p class="small muted">노트 없음</p>`;
}
$("#n-add").onclick = e => busy(e.target, () => api(`/api/context/notes/${sess()}`, { method: "POST", body: { text: $("#n-text").value, source: $("#n-source").value } }))
  .then(() => api(`/api/context/notes/${sess()}`)).then(showNotes).catch(err => ui.error($("#n-out"), err));
$("#n-read").onclick = e => busy(e.target, () => api(`/api/context/notes/${sess()}?q=${encodeURIComponent($("#n-q").value)}`)).then(showNotes).catch(err => ui.error($("#n-out"), err));
$("#n-clear").onclick = async () => {
  if (!(await ui.confirm(`세션 ${$("#n-session").value} 의 노트를 모두 지울까요?`))) return;
  api(`/api/context/notes/${sess()}`, { method: "DELETE" }).then(() => showNotes({ notes: [] })).catch(err => ui.error($("#n-out"), err));
};

setupCollectionPickers({ col: $("#k-col"), set: $("#k-set") }).catch(e => ui.error($("#k-out"), e));
