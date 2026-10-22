// architecture/layers.html 화면 스크립트 — 층 구조 · 요약 · KV 곡선(TA2~TA6), 맥락 길이별 미리 채우기 실측(TA3)
const pct = v => (v == null ? "-" : `${Math.round(v * 100)}%`);

function src() {
  return $("#a-gguf").value ? { gguf: $("#a-gguf").value } : { hf_id: $("#a-hf").value.trim(), bits: $("#a-bits").value };
}

$("#a-run").onclick = e => busy(e.target, () => api("/api/architecture/layers", { method: "POST", body: src() })).then(r => {
  const s = r.summary, a = r.model;
  $("#a-out").innerHTML = html`<div class="small">${a.name || a.arch} · 층 ${a.layers} · 은닉 ${a.hidden} · ${r.exact ? "GGUF 텐서별 정확" : "HF 설정 어림"}
      ${s.experts ? ` · 전문가 ${s.experts}개 중 ${s.experts_used}개` : ""}</div>
    <div class="grid cols-2"><div><b>어텐션 종류</b><ul class="small">${html.join(Object.entries(s.attention_kinds).map(([k, v]) => html`<li>${k} ${v}층</li>`), "")}</ul></div>
      <div><b>가중치 ${s.weights_gb} GB</b><ul class="small"><li>전문가 몫 ${pct(s.expert_share)}</li><li>토큰마다 읽는 양 ${s.read_per_token_gb} GB (${pct(s.read_share)})</li>
        <li>임베딩 표 몫 ${pct(s.embed_share)} — 토큰마다 한 줄만 읽음</li><li>읽는 양 중 출력층 ${pct(s.head_share_of_read)}</li></ul></div></div>
    <h3>맥락 길이별 KV (f16 · 요청 하나)</h3>
    <div class="table-wrap"><table><tr><th>맥락</th><th>KV MB</th><th>'층 수 × 맥락' 어림 MB</th><th>줄어든 몫</th></tr>
      ${html.join(r.kv_curve.map(c => html`<tr><td>${c.ctx}</td><td><b>${c.kv_mb}</b></td><td>${c.naive_mb}</td><td>${pct(c.saving)}</td></tr>`), "")}</table></div>
    <h3>층마다</h3>
    <div class="table-wrap"><table><tr><th>층</th><th>어텐션</th><th>KV 차원</th><th>FFN</th><th>MB</th><th>전문가 MB</th></tr>
      ${html.join(r.layers.map(l => html`<tr><td>${l.layer}</td><td>${l.attention}</td><td>${l.kv_dim || "-"}</td><td>${l.ffn}</td><td>${l.mb}</td><td>${l.experts_mb || "-"}</td></tr>`), "")}</table></div>`;
}).catch(err => ui.error($("#a-out"), err));

$("#s-run").onclick = e => runJobInto(e.target, "/api/architecture/scaling", { lengths: $("#s-lens").value.split(",").map(x => +x.trim()).filter(Boolean) }, $("#s-progress"), r => {
  $("#s-out").innerHTML = html`<div class="small muted">${r.model} · 층 ${r.layers} · 은닉 ${r.hidden} · ${r.device} · ${r.dtype} · ${r.seconds}초 · run #${r.run_id}</div>
    <div class="table-wrap"><table><tr><th>토큰</th><th>초</th><th>토큰당 ms</th><th>KV MB</th><th>길이 배율 → 시간 배율</th></tr>
      ${html.join(r.rows.map(x => html`<tr><td>${x.tokens}</td><td>${x.seconds}</td><td>${x.ms_per_token}</td><td>${x.kv_mb}</td><td>${x.time_ratio == null ? "-" : `×${x.len_ratio} → ×${x.time_ratio}`}</td></tr>`), "")}</table></div>`;
}).catch(err => ui.error($("#s-out"), err));

api("/api/bigmodel/machine").then(m => {
  $("#a-gguf").innerHTML = html`<option value="">(HF 모델로 어림)</option>${m.gguf.map(f => html`<option value="${f.name}">${f.name} · ${f.gb} GB</option>`)}`;
}).catch(() => {});
