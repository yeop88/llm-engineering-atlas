// compress/prompt.html 화면 스크립트 — 토큰 단위 · 질문을 아는 압축 미리 보기 · 문장 대조 점수(KC1 · KC2)
const pct = v => (v == null ? "-" : `${(v * 100).toFixed(1)}%`);

$("#p-run").onclick = e => busy(e.target, () => api("/api/compress/preview", { method: "POST", body: { text: $("#p-text").value, question: $("#p-q").value,
  method: $("#p-method").value, ratio: +$("#p-ratio").value || 0.5 } })).then(r => {
  $("#p-out").innerHTML = html`<div class="small">${r.orig_chars}자 → <b>${r.chars}자</b> (${pct(r.char_ratio)}) · 숫자 · 조항 보존 ${pct(r.preserved)}
    ${r.kept != null ? ` · 토큰 ${r.kept}/${r.total}` : ""}${r.protected != null ? ` · 보호 토큰 ${r.protected}` : ""} · ${r.seconds}초 · 압축 모델 ${r.model}</div><pre class="pre small">${r.text}</pre>`;
  $("#p-sents").innerHTML = r.sentences ? html`<div class="table-wrap"><table><tr><th>문장</th><th>대조 점수</th><th></th></tr>
    ${html.join([...r.sentences].sort((a, b) => b.score - a.score).map(s => html`<tr><td class="small">${s.text}</td><td>${s.score}</td><td>${s.kept ? html`<span class="badge ok">남김</span>` : html`<span class="badge">뺌</span>`}</td></tr>`), "")}</table></div>` : "";
}).catch(err => ui.error($("#p-out"), err));
