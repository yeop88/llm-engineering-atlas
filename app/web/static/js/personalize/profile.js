// personalize/profile.html 화면 스크립트 — 동의(PS1) · 선호(PS2) · 신호(PS3) · 프로필 · 전략(PS4 · PS5) · 개인화 응답(PS6) · 평가(PS7)
let OPT = null;
const key = () => encodeURIComponent($("#k-key").value.trim());
const SRC = { "명시": "ok", "행동 추정": "warn", "기본": "" };

function show(v) {
  $("#k-scopes").innerHTML = html`${Object.entries(OPT.scopes).map(([s, label]) => {
    const c = v.consent[s];
    return html`<label class="row m-0"><input type="checkbox" data-scope="${s}" ${c?.granted ? "checked" : ""}> <b>${s}</b> ${label}
      <span class="muted">${c ? `(${c.granted ? "동의" : "거부"} · ${c.at} · ${c.version})` : "(받은 적 없음)"}</span></label>`;
  })}`;
  for (const [k] of Object.entries(OPT.prefs)) { const el = $(`#p-${k}`); if (el) el.value = v.prefs[k]?.value || ""; }
  const t = v.traits, st = v.strategy;
  $("#f-out").innerHTML = html`<div class="table-wrap"><table><tr><th>특성</th><th>값</th><th>출처</th><th>확신</th></tr>
      ${html.join(Object.entries(t).map(([k, x]) => html`<tr><td>${k}</td><td>${x.value}</td><td><span class="badge ${SRC[x.source] ?? ""}">${x.source}</span></td><td>${x.confidence}${x.evidence != null ? ` (근거 ${x.evidence})` : ""}</td></tr>`), "")}</table></div>
    <div>전략: 최대 ${st.max_steps >= 99 ? "전부" : `${st.max_steps}단계`} · 설명 ${st.explain ? "유지" : "빼기"} · 해 본 조치 건너뛰기 · ${st.voice ? "음성 형식" : "글 형식"} — ${st.why.join(" · ")}</div>
    <div class="muted">신호 ${v.n_signals}개 · 해 본 조치 ${v.tried.map(x => `${x.topic} ${x.step}단계`).join(", ") || "없음"}</div>`;
}

const load = () => api(`/api/personalize/profiles/${key()}`).then(show);

$("#k-load").onclick = e => busy(e.target, load).catch(err => ui.error($("#f-out"), err));
$("#k-save").onclick = e => busy(e.target, () => api(`/api/personalize/profiles/${key()}/consent`, { method: "POST",
  body: { scopes: Object.fromEntries([...document.querySelectorAll("[data-scope]")].map(x => [x.dataset.scope, x.checked])) } })).then(r => {
  show(r);
  const rm = Object.entries(r.removed || {}).filter(([, n]) => n);
  if (rm.length) toast(`철회한 범위의 기록을 지웠습니다: ${rm.map(([k, n]) => `${k} ${n}`).join(", ")}`);
}).catch(err => ui.error($("#f-out"), err));
$("#k-withdraw").onclick = async () => {
  if (!(await ui.confirm("이 고객의 개인화 기록(동의 · 선호 · 신호 · 해 본 조치)을 모두 지울까요? 보유 제품 · 문의 요약은 대화 맵의 보관 규칙을 따릅니다.", { ok: "지우기", danger: true, title: "개인화 기록 지우기" }))) return;
  api(`/api/personalize/profiles/${key()}`, { method: "DELETE" }).then(load).catch(err => ui.error($("#f-out"), err));
};
$("#p-save").onclick = e => busy(e.target, () => api(`/api/personalize/profiles/${key()}/prefs`, { method: "POST",
  body: { prefs: Object.fromEntries(Object.keys(OPT.prefs).map(k => [k, $(`#p-${k}`).value]).filter(([, v]) => v)) } })).then(show).catch(err => ui.error($("#f-out"), err));
$("#s-add").onclick = e => busy(e.target, () => api(`/api/personalize/profiles/${key()}/signals`, { method: "POST",
  body: { events: [{ type: $("#s-type").value, step: +$("#s-step").value, topic: $("#s-topic").value.trim() }] } })).then(r => {
  $("#s-msg").textContent = r.dropped ? `버림 ${r.dropped}개 — ${r.reason}` : `넣음 ${r.kept}개${r.masked ? ` · 개인정보 ${r.masked}곳 가림` : ""}`;
  show(r);
}).catch(err => ui.error($("#s-msg"), err));

$("#r-scn").onchange = () => {
  const s = OPT.scenarios[+$("#r-scn").value];
  $("#r-base").value = s.answer;
  $("#r-topic").value = s.topic;
};
$("#r-run").onclick = e => busy(e.target, () => api("/api/personalize/respond", { method: "POST", body: { key: $("#k-key").value.trim(), topic: $("#r-topic").value.trim(),
  answer: $("#r-base").value.trim() || null, question: $("#r-q").value.trim() || null, collection_id: +$("#r-col").value || null } })).then(r => {
  const c = r.check;
  $("#r-out").innerHTML = html`<div class="small">${r.strategy.why.join(" · ")}${r.personalized.skipped.length ? ` · 건너뜀 ${r.personalized.skipped.join(", ")}단계` : ""}
      — 사실 보존 ${c.preserved ? html`<span class="badge ok">예</span>` : html`<span class="badge err">아니오</span>`}
      ${c.new_marks.length ? html` 새 표시 <span class="mono">${c.new_marks.join(", ")}</span>` : ""}</div>
    <div class="grid cols-2"><div><b>기본 답</b> <span class="small muted">${r.base.length}자</span><pre class="pre small">${r.base}</pre></div>
      <div><b>개인화 답</b> <span class="small muted">${r.personalized.text.length}자</span><pre class="pre small">${r.personalized.text}</pre></div></div>`;
}).catch(err => ui.error($("#r-out"), err));

$("#e-run").onclick = e => busy(e.target, () => api("/api/personalize/evaluate", { method: "POST" })).then(r => {
  const pct = v => `${Math.round(v * 100)}%`;
  $("#e-out").innerHTML = html`<div class="small">${r.n}건 · run #${r.run_id} — 형식 일치 <b>${pct(r.length_ok)}</b>(명시 선호만 ${pct(r.explicit_only_length_ok)} · 개인화 없음 ${pct(r.baseline_length_ok)})
      · 건너뛰기 ${pct(r.skip_ok)} · 사실 보존 ${pct(r.preserved)} · 길이 ${pct(r.char_ratio)}</div>
    <div class="table-wrap"><table><tr><th>인물</th><th>상담</th><th>단계</th><th>기대</th><th>건너뜀</th><th>보존</th><th>글자</th><th>이유</th></tr>
      ${html.join(r.rows.map(x => html`<tr><td>${x.persona}</td><td>${x.scenario}</td><td>${x.max_steps >= 99 ? "전부" : x.max_steps}${x.ok_length ? "" : html` <span class="badge err">틀림</span>`}</td>
        <td>${x.expect_steps >= 99 ? "전부" : x.expect_steps}</td><td>${x.skipped.join(", ") || "-"}${x.ok_skip ? "" : html` <span class="badge err">틀림</span>`}</td>
        <td>${x.preserved ? "예" : html`<span class="badge err">아니오</span>`}</td><td>${x.chars} / ${x.base_chars}</td><td class="small muted">${x.why.join(" · ")}</td></tr>`), "")}</table></div>`;
}).catch(err => ui.error($("#e-out"), err));

api("/api/personalize/options").then(o => {
  OPT = o;
  $("#p-fields").innerHTML = html`${Object.entries(o.prefs).map(([k, vs]) => html`<div class="field"><label for="p-${k}">${k}</label><select id="p-${k}"><option value="">(고르지 않음)</option>${vs.map(v => html`<option>${v}</option>`)}</select></div>`)}`;
  $("#s-type").innerHTML = html`${o.events.map(v => html`<option>${v}</option>`)}`;
  $("#r-scn").innerHTML = html`${o.scenarios.map((s, i) => html`<option value="${i}">${s.name}</option>`)}`;
  $("#r-scn").onchange();
  return load();
}).catch(err => ui.error($("#f-out"), err));
setupCollectionPickers({ col: $("#r-col") }).catch(() => {});
