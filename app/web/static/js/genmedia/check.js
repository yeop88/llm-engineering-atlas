// genmedia/check.html 화면 스크립트 — 자동 품질 검사(GM7), 출처 · 워터마크 붙이기 · 확인 · 남는지 평가(GM8)
const pct = v => (v == null ? "-" : `${Math.round(v * 100)}%`);
const ok = b => html`<span class="badge ${b ? "ok" : "err"}">${b ? "통과" : "걸림"}</span>`;
const ATTACK = { none: "그대로", png_resave: "PNG 다시 저장", jpeg90: "JPEG 90", jpeg70: "JPEG 70", jpeg50: "JPEG 50", resize50: "반으로 줄이기", crop70: "70% 자르기" };

function fd(extra) {
  const f = new FormData();
  for (const [k, v] of Object.entries(extra)) f.append(k, v);
  return f;
}

$("#q-run").onclick = e => busy(e.target, () => api("/api/genmedia/qa/sample", { method: "POST", form: fd({ seed: $("#q-seed").value, defect: $("#q-defect").value }) })).then(r => {
  $("#q-out").innerHTML = html`<div class="small">지시의 물체: ${r.wanted.join(", ")} — 전체 ${ok(r.pass)}</div>
    <ul class="small"><li>지시 준수 ${ok(r.prompt.ok)}${r.prompt.missing.length ? ` 빠짐: ${r.prompt.missing.join(", ")}` : ""}</li>
      <li>스타일 ${ok(r.style.ok)} 색 분포 차 ${r.style.distance}</li>
      <li>시간 ${ok(r.temporal.ok)}${r.temporal.flicker.length ? ` 깜빡임 프레임 ${r.temporal.flicker.join(", ")}` : ""}${r.temporal.jumps.length ? ` 순간 이동 ${r.temporal.jumps.map(j => `${j.frame}번 ${j.object}`).join(", ")}` : ""}</li></ul>
    <div class="row">${r.frames.map((src, i) => html`<img src="${src}" alt="프레임 ${i}" class="w-xl">`)}</div>`;
}).catch(err => ui.error($("#q-out"), err));

$("#q-eval").onclick = e => busy(e.target, () => api("/api/genmedia/qa/evaluate", { method: "POST", form: fd({ n: 20 }) })).then(r => {
  $("#q-out").innerHTML = html`<div class="small muted">결함 종류마다 ${r.n}묶음 · ${r.seconds}초 · run #${r.run_id} — 결함 없는 샷 통과 ${pct(r.clean_pass)} · 거짓 경보(지시 · 스타일 · 시간) ${pct(r.false_alarm.prompt_flag)} · ${pct(r.false_alarm.style_flag)} · ${pct(r.false_alarm.temporal_flag)}</div>
    <div class="table-wrap"><table><tr><th>넣은 결함</th><th>맞는 검사가 잡음</th><th>전체 판정이 걸러냄</th></tr>
      ${html.join(Object.entries(r.by_defect).map(([k, v]) => html`<tr><td>${k}</td><td>${pct(v.caught_by_its_check)}</td><td>${pct(v.rejected)}</td></tr>`), "")}</table></div>`;
}).catch(err => ui.error($("#q-out"), err));

$("#p-embed").onclick = e => busy(e.target, () => {
  const f = fd({ key: $("#p-key").value, prompt: $("#p-prompt").value, generator: $("#p-gen").value, visible: $("#p-visible").checked });
  if ($("#p-file").files[0]) f.append("file", $("#p-file").files[0]);
  return api("/api/genmedia/provenance/embed", { method: "POST", form: f });
}).then(r => {
  $("#p-img").src = r.png;
  $("#p-img").hidden = false;
  $("#p-out").innerHTML = html`<div>붙인 매니페스트 (${Math.round(r.bytes / 1024)} KB PNG — 그림을 저장해 아래 '올린 그림 확인'으로 시험)</div><pre class="pre small">${JSON.stringify(r.manifest, null, 1)}</pre>`;
}).catch(err => ui.error($("#p-out"), err));

$("#p-detect").onclick = e => {
  if (!$("#p-file").files[0]) { ui.error($("#p-out"), new Error("확인할 그림 파일을 고르세요")); return; }
  busy(e.target, () => api("/api/genmedia/provenance/detect", { method: "POST", form: fd({ key: $("#p-key").value, file: $("#p-file").files[0] }) })).then(r => {
    $("#p-out").innerHTML = html`<ul><li>메타데이터: ${r.metadata ? (r.manifest_intact ? "있음 · 바뀌지 않음" : "있음 · 바뀜") : "없음"}</li>
      <li>워터마크: ${r.watermark ? html`<span class="badge ok">찾음</span>` : html`<span class="badge">못 찾음</span>`} (z ${r.watermark_z} · 어긋남 최대 ${r.watermark_z_shift})</li></ul>`;
  }).catch(err => ui.error($("#p-out"), err));
};

$("#p-eval").onclick = e => busy(e.target, () => api("/api/genmedia/provenance/evaluate", { method: "POST", form: fd({ n: 12 }) })).then(r => {
  $("#p-out").innerHTML = html`<div class="muted">그림 ${r.n}장 · ${r.seconds}초 · run #${r.run_id} — 거짓 검출 ${pct(r.false_detection)} (무늬 없는 그림 · 다른 열쇠의 최대 z ${r.null_z_max})</div>
    <div class="table-wrap"><table><tr><th>겪은 일</th><th>메타데이터 남음</th><th>워터마크 찾음</th></tr>
      ${html.join(Object.entries(r.attacks).map(([k, v]) => html`<tr><td>${ATTACK[k] || k}</td><td>${pct(v.metadata)}</td><td><b>${pct(v.watermark)}</b></td></tr>`), "")}</table></div>`;
}).catch(err => ui.error($("#p-out"), err));
