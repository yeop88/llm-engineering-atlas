// platform/registry.html 화면 스크립트 — 프롬프트 버전 · 활성(PF3), 기능 플래그 기본값 · 규칙 · 시험 · 기록(PF4)
async function loadPrompts() {
  const r = await api("/api/platform/prompts");
  const vs = r.versions.filter(v => v.name === "answer_system");
  const active = vs.find(v => v.active);
  if (!$("#p-text").value) $("#p-text").value = active?.text || r.code_default.answer_system;
  $("#p-list").innerHTML = html`<div class="small">지금 활성: ${active ? html`<b>answer_system@${active.version}</b>` : html`<b>코드 기본값</b>`}
      ${active ? html` <button class="btn sm" data-act="">코드 기본값으로</button>` : ""}</div>
    ${vs.length ? html`<div class="table-wrap"><table><tr><th>버전</th><th>메모</th><th>만든 이</th><th></th></tr>${html.join(vs.map(v => html`<tr><td class="small">@${v.version}${v.active ? html` <span class="badge ok">활성</span>` : ""}</td>
      <td class="small">${v.note}<details><summary>글</summary><pre class="pre small">${v.text}</pre></details></td><td class="small">${v.by} · ${v.at.slice(0, 10)}</td>
      <td>${v.active ? "" : html`<button class="btn sm" data-act="${v.version}">활성으로</button>`}</td></tr>`), "")}</table></div>` : html`<div class="small muted">버전이 없습니다 — 코드 기본값을 씁니다.</div>`}`;
  $$("[data-act]", $("#p-list")).forEach(b => b.onclick = () => busy(b, () => api("/api/platform/prompts/answer_system/activate", { method: "POST", body: { version: b.dataset.act ? +b.dataset.act : null } }))
    .then(() => { toast("바꿨습니다 — 10초 안에 적용"); loadPrompts(); }).catch(e => toast(e.message, "err")));
}

async function loadFlags() {
  const r = await api("/api/platform/flags");
  $("#f-list").innerHTML = html.join(r.flags.map(f => html`<div class="card stack mt-2" data-key="${f.key}">
    <div class="row"><b class="mono">${f.key}</b> <span class="small muted">${f.description}</span></div>
    <div class="row">
      <div class="field"><label for="f-d-${f.key}">기본값 (JSON, 비우면 설정값)</label><input id="f-d-${f.key}" data-default class="mono w-md" value="${f.default === null ? "" : JSON.stringify(f.default)}"></div>
      <div class="field grow"><label for="f-r-${f.key}">규칙 (JSON 목록 — 첫 번째로 맞는 것)</label><input id="f-r-${f.key}" data-rules class="mono" value="${JSON.stringify(f.rules)}" placeholder='[{"tenant": "법무", "value": "enforce"}, {"pct": 10, "value": "enforce"}]'></div>
      <div class="self-end"><button class="btn sm" data-save>저장</button></div>
    </div>
    <div class="row small"><div class="field"><label for="f-u-${f.key}">시험: 사용자</label><input id="f-u-${f.key}" data-user class="w-md" value="local"></div>
      <div class="field"><label for="f-g-${f.key}">그룹(쉼표)</label><input id="f-g-${f.key}" data-groups class="w-md" placeholder="tenant:법무"></div>
      <div class="self-end"><button class="btn sm" data-eval>값 보기</button> <span data-val></span></div></div>
    ${f.history.length ? html`<details class="small"><summary>바꾼 기록 ${f.history.length}</summary><ul>${html.join(f.history.map(h => html`<li>${h.at.slice(0, 16).replace("T", " ")} ${h.by} — ${JSON.stringify(h.after)}</li>`), "")}</ul></details>` : ""}</div>`), "");
  $$("[data-key]", $("#f-list")).forEach(card => {
    const key = card.dataset.key;
    $("[data-save]", card).onclick = e => {
      let def, rules;
      try { def = $("[data-default]", card).value.trim() ? JSON.parse($("[data-default]", card).value) : null; rules = JSON.parse($("[data-rules]", card).value || "[]"); }
      catch { return toast("기본값 · 규칙은 JSON 이어야 합니다", "err"); }
      busy(e.target, () => api(`/api/platform/flags/${key}`, { method: "POST", body: { default: def, rules } })).then(() => { toast("저장했습니다 — 10초 안에 적용"); loadFlags(); }).catch(err => toast(err.message, "err"));
    };
    $("[data-eval]", card).onclick = e => busy(e.target, () => api(`/api/platform/flags/${key}/eval`, { method: "POST", body: { user: $("[data-user]", card).value, groups: $("[data-groups]", card).value.split(",").map(s => s.trim()).filter(Boolean) } }))
      .then(r => { $("[data-val]", card).innerHTML = html`<span class="badge">${r.value === null ? "설정값" : JSON.stringify(r.value)}</span>`; }).catch(err => toast(err.message, "err"));
  });
}

$("#p-add").onclick = e => busy(e.target, () => api("/api/platform/prompts", { method: "POST", body: { name: "answer_system", text: $("#p-text").value, note: $("#p-note").value, activate: $("#p-act").checked } }))
  .then(r => { toast(`@${r.version} 을 추가했습니다`); loadPrompts(); }).catch(err => toast(err.message, "err"));
loadPrompts().catch(e => ui.error($("#p-list"), e));
loadFlags().catch(e => ui.error($("#f-list"), e));
