// tokenizer/compare.html 화면 스크립트 — 모델별 토큰 효율 · 표시 쪼개짐 · 어휘 · 정규화 · 설정 비용(TK1~TK6)
$("#t-run").onclick = e => runJobInto(e.target, "/api/tokenizer/compare", { hf_ids: $("#t-ids").value.split("\n").map(s => s.trim()).filter(Boolean) }, $("#t-progress"), r => {
  const ok = r.models.filter(m => m.efficiency);
  const kinds = Object.keys(r.samples);
  $("#t-out").innerHTML = html`<div class="small muted">${r.seconds}초 · run #${r.run_id}</div>
    ${html.join(r.models.filter(m => m.error).map(m => html`<div class="errbox small">${m.hf_id}: ${m.error}</div>`), "")}
    <h3>1,000자당 토큰 (TK2) — 괄호는 가장 적은 모델 대비</h3>
    <div class="table-wrap"><table><tr><th>모델</th>${kinds.map(k => html`<th>${k}</th>`)}</tr>
    ${html.join(ok.map(m => html`<tr><td class="small">${m.hf_id}</td>${kinds.map(k => html`<td>${m.efficiency[k].per_1000_chars} <span class="small muted">(×${m.efficiency[k].vs_best})</span></td>`)}</tr>`), "")}</table></div>
    <h3>표시가 쪼개지는 모양</h3>
    <div class="table-wrap"><table><tr><th>모델</th>${ok[0] ? ok[0].marks.map(x => html`<th class="mono">${x.mark}</th>`) : ""}</tr>
    ${html.join(ok.map(m => html`<tr><td class="small">${m.hf_id}</td>${m.marks.map(x => html`<td class="small mono">${x.tokens}${x.byte_split ? html` <span class="badge warn">바이트 조각</span>` : ""}<div class="muted">${x.pieces.join("|")}</div></td>`)}</tr>`), "")}</table></div>
    <h3>어휘 · 정규화 · 설정 (TK1 · TK3~TK6)</h3>
    <div class="table-wrap"><table><tr><th>모델</th><th>어휘</th><th>한글 조각</th><th>한 글자 조각</th><th>NFD · 전각 · 보이지 않는 문자</th><th>임베딩 · 출력층(M)</th><th>위치 θ · 확장 · 최대</th><th>이미지 한 장 토큰</th></tr>
    ${html.join(ok.map(m => html`<tr><td class="small">${m.hf_id}</td><td>${m.vocab.size}</td><td>${m.vocab.hangul_pieces} (${(m.vocab.hangul_share * 100).toFixed(1)}%)</td><td>${m.vocab.hangul_single_syllables}</td>
      <td class="small">×${m.normalization["NFD(자모 분리)"].vs_nfc} · ×${m.normalization["전각 숫자"].vs_nfc} · ×${m.normalization["보이지 않는 문자"].vs_nfc}</td>
      <td class="small">${m.config.error || html`${m.config.embedding_params_m}${m.config.tied ? " (같이 씀)" : ` + ${m.config.head_params_m}`}`}</td>
      <td class="small">${m.config.rope ? html`${m.config.rope.theta ?? "-"} · ${m.config.rope.scaling ? JSON.stringify(m.config.rope.scaling) : "없음"} · ${m.config.rope.max_positions ?? "-"}` : "-"}</td>
      <td>${m.config.image_tokens ?? "-"}</td></tr>`), "")}</table></div>`;
}).catch(err => ui.error($("#t-out"), err));
