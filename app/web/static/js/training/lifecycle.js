// training/lifecycle.html 화면 스크립트 — 모델 원장(TL1~TL8), 학습 데이터 감사(TL2)
const STATE = { done: ["ok", "했다"], check: ["warn", "확인 필요"], missing: ["err", "안 했다"], skipped: ["", "하지 않음"] };

$("#l-run").onclick = e => busy(e.target, () => api(`/api/training/lifecycle/${$("#l-model").value}`)).then(r => {
  $("#l-out").innerHTML = html`<div class="small">${r.model.name} · ${r.model.endpoint} · 기본 ${r.model.base} — 했다 ${r.done} · 확인 필요 ${r.check} · 안 했다 ${r.missing}</div>
    <div class="small muted">만든 순서: ${r.chain.map(c => `#${c.id} ${c.name}(${c.method})`).join(" → ")}</div>
    <div class="table-wrap"><table><tr><th>단계</th><th>상태</th><th>기록</th><th>확인할 것</th></tr>
      ${html.join(r.steps.map(s => html`<tr><td>${s.no} ${s.title}</td><td><span class="badge ${STATE[s.state][0]}">${STATE[s.state][1]}</span></td>
        <td class="small">${s.facts.length ? html`<ul>${s.facts.map(f => html`<li>${f}</li>`)}</ul>` : "-"}</td>
        <td class="small">${s.warnings.length ? html`<ul>${s.warnings.map(w => html`<li>${w}</li>`)}</ul>` : ""} ${s.links.map(l => html`<a href="${l}">${l}</a> `)}</td></tr>`), "")}</table></div>`;
}).catch(err => ui.error($("#l-out"), err));

$("#d-run").onclick = e => busy(e.target, () => api(`/api/training/datasets/${encodeURIComponent($("#d-name").value)}/audit`)).then(a => {
  const rows = a.kind === "sft"
    ? [["같은 답 반복", `${a.same_answer.rows}행 · ${a.same_answer.groups}종`, a.same_answer.top.map(t => `${t.n}× ${t.answer}`).join(" / ")],
       ["답 길이(글자)", a.answer_chars ? `최소 ${a.answer_chars.min} · 중앙 ${a.answer_chars.median} · 최대 ${a.answer_chars.max}` : "-", ""],
       ["짧은 답", `${a.short.n}건`, a.short.examples.join(" / ")], ["거절 답 몫", `${Math.round(a.refusal_share * 100)}%`, ""],
       ["한글 몫", `${Math.round(a.hangul_share * 100)}%`, ""], ["평균 메시지 수", a.turns, ""]]
    : [["고른 답 = 버린 답", `${a.same_pair}쌍`, ""], ["고른 답이 더 긴 몫", a.chosen_longer_share, "0.5 근처가 좋음"], ["고른 답이 거절인 몫", a.chosen_refusal_share, ""]];
  rows.push(["비슷한 질문 쌍", a.near_dup_questions.pairs, a.near_dup_questions.examples.map(p => p.join(" ↔ ")).join(" / ")],
    ["채팅 틀 조각", `${a.template_leak.n}건`, (a.template_leak.examples || []).join(" / ")]);
  $("#d-out").innerHTML = html`<div class="small">${a.name} · ${a.kind.toUpperCase()} · ${a.n}건</div>
    ${a.warnings.length ? html`<div class="errbox small"><ul>${a.warnings.map(w => html`<li>${w}</li>`)}</ul></div>` : html`<div class="small"><span class="badge ok">경고 없음</span></div>`}
    <div class="table-wrap"><table><tr><th>항목</th><th>값</th><th class="small">예</th></tr>
      ${html.join(rows.map(([k, v, x]) => html`<tr><td>${k}</td><td>${v}</td><td class="small muted">${x}</td></tr>`), "")}</table></div>`;
}).catch(err => ui.error($("#d-out"), err));

api("/api/training/models").then(r => {
  $("#l-model").innerHTML = r.models.length ? html`${r.models.map(m => html`<option value="${m.id}">#${m.id} ${m.name} · ${m.method} · ${m.base}</option>`)}` : html`<option value="">(학습한 모델 없음 — 후학습 화면에서 학습)</option>`;
  $("#d-name").innerHTML = r.datasets.length ? html`${r.datasets.map(d => html`<option value="${d.name}">${d.name} · ${d.kind} · ${d.n}건</option>`)}` : html`<option value="">(학습 데이터 없음)</option>`;
}).catch(err => ui.error($("#l-out"), err));
