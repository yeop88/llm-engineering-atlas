// vision/look.html 화면 스크립트 — 영역 · 읽기(VL1~VL5 · VL7), 사진 + 질문 + 매뉴얼(VL6 · VL7), VLM 하나에 vs 나눠서
const pct = v => (v == null ? "-" : `${Math.round(v * 100)}%`);

function form(extra = {}) {
  const fd = new FormData();
  const f = $("#v-file").files[0];
  if (f) fd.append("file", f);
  else {
    fd.append("code", $("#v-code").value.trim());
    fd.append("seed", $("#v-seed").value);
    fd.append("hard", $("#v-hard").checked);
    fd.append("far", $("#v-far").checked);
  }
  if ($("#v-provider").value) fd.append("provider", $("#v-provider").value);
  if ($("#v-model").value.trim()) fd.append("model", $("#v-model").value.trim());
  for (const [k, v] of Object.entries(extra)) fd.append(k, v);
  return fd;
}

$("#v-run").onclick = e => busy(e.target, () => api("/api/vision/look", { method: "POST", form: form({ read: $("#v-read").checked }) })).then(r => {
  $("#v-img").src = r.overlay;
  $("#v-img").hidden = false;
  const t = r.truth;
  $("#v-out").innerHTML = html`<ul>
    <li>입력: ${r.input.format} · ${r.input.size.join("×")}${r.input.gps_removed ? " · 위치 정보 지움" : ""}</li>
    <li>전처리: ${r.steps.join(" · ") || "-"}</li>
    <li>표시창: ${r.display ? `${r.display.box.join(", ")} (기울기 ${r.display.angle}도)` : "못 찾음"}</li>
    <li>읽은 코드: <b>${r.code ?? "-"}</b>${r.snapped ? ` (읽은 글 ${r.raw_code} → 알려진 코드에 맞춤)` : ""}${r.read_on ? ` · ${r.read_on}에서` : ""}${t ? html` <span class="badge ${r.code === t.code ? "ok" : "err"}">정답 ${t.code}</span>` : ""}</li>
    <li>호스: ${r.hose ? `${r.kinked ? "꺾임" : "곧음"} (최대 방향 변화 ${r.hose.max_turn_deg}도)` : "못 찾음"}${t ? html` <span class="badge ${r.kinked === t.kinked ? "ok" : "err"}">정답 ${t.kinked ? "꺾임" : "곧음"}</span>` : ""}</li>
    <li>${r.seconds}초</li></ul>`;
}).catch(err => ui.error($("#v-out"), err));

$("#q-run").onclick = e => busy(e.target, () => api("/api/vision/answer", { method: "POST", form: form({ question: $("#q-text").value.trim(), collection_id: $("#q-col").value }) })).then(r => {
  $("#v-img").src = r.overlay;
  $("#v-img").hidden = false;
  $("#q-out").innerHTML = html`<div class="small muted">보낸 질문: ${r.question} · 답 ${r.answer_seconds}초</div>
    <ol class="small">${r.grounding.map(g => html`<li>${g.sentence} ${g.regions.length ? html`<span class="badge ok">영역 ${g.regions.map(k => `[${k}]`).join(" ")}</span>` : html`<span class="badge">매뉴얼 근거</span>`}</li>`)}</ol>
    ${r.sources.length ? html`<div class="small muted">근거: ${r.sources.map(s => s.filename || s.title || s.doc_id).join(" · ")}</div>` : ""}`;
}).catch(err => ui.error($("#q-out"), err));

$("#c-run").onclick = e => runJobInto(e.target, "/api/vision/evaluate", { n: +$("#c-n").value, llm: { provider: $("#v-provider").value || null, model: $("#v-model").value.trim() || null } }, $("#c-progress"), r => {
  $("#c-out").innerHTML = html`<div class="small muted">${r.model} · ${r.seconds}초 · run #${r.run_id}</div>
    <div class="table-wrap"><table><tr><th>조건</th><th>장</th><th>코드: 하나에</th><th>코드: 나눠서</th><th>꺾임: 하나에</th><th>꺾임: 나눠서(규칙)</th><th>표시창 찾음</th><th>초: 하나에 · 나눠서</th></tr>
      ${html.join(Object.entries(r.by_condition).map(([k, v]) => html`<tr><td>${k}</td><td>${v.n}</td><td>${pct(v.whole_code)}</td><td><b>${pct(v.split_code)}</b></td>
        <td>${pct(v.whole_kink)}</td><td><b>${pct(v.split_kink)}</b></td><td>${pct(v.display_found)}</td><td>${v.whole_s} · ${v.split_s}</td></tr>`), "")}</table></div>`;
}).catch(err => ui.error($("#c-out"), err));

setupCollectionPickers({ col: $("#q-col") }).catch(() => {});
