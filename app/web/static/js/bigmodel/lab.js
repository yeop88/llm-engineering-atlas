// bigmodel/lab.html 화면 스크립트 — 극저비트 사후 양자화 · GGUF 실제 비트(BM6), 여러 기기 나누기 계획(BM7)
const NAME = { fp: "원래(16비트)", rtn8: "8비트", rtn4: "4비트", rtn3: "3비트", rtn2: "2비트", ternary: "삼진(1.58비트)" };
const pct = v => (v == null ? "-" : `${Math.round(v * 100)}%`);

$("#w-run").onclick = e => runJobInto(e.target, "/api/bigmodel/lowbit", { max_tokens: +$("#w-tokens").value }, $("#w-progress"), r => {
  $("#w-out").innerHTML = html`<div class="small muted">${r.model} · 선형층 ${r.linear_params_m}M 파라미터 · 글 ${r.tokens}토큰 · ${r.seconds}초 · run #${r.run_id}</div>
    <div class="table-wrap"><table><tr><th>방법</th><th>가중치당 비트(눈금 포함)</th><th>선형층 크기</th><th>혼란도</th><th>원래와 1위 일치</th><th>KL</th></tr>
    ${html.join(r.rows.map(x => html`<tr><td>${NAME[x.method] || x.method}</td><td>${x.bits}</td><td>${x.linear_gb} GB</td><td><b>${x.ppl}</b></td><td>${pct(x.top1_agree)}</td><td>${x.kl}</td></tr>`), "")}</table></div>
    <div class="small muted">학습 없이 줄이면 2비트 · 삼진에서 무너지는 것이 정상입니다 — 처음부터 저비트로 학습한 모델만 버팁니다.</div>`;
}).catch(err => ui.error($("#w-out"), err));

$("#w-gguf").onclick = e => busy(e.target, () => api("/api/bigmodel/lowbit/gguf")).then(r => {
  $("#w-gguf-out").innerHTML = r.files.length ? html`<div class="table-wrap"><table><tr><th>파일</th><th>구조</th><th>파라미터</th><th>크기</th><th>가중치당 비트</th><th>형식 구성(바이트 몫)</th></tr>
    ${html.join(r.files.map(f => html`<tr><td class="small">${f.name}</td><td>${f.arch || "-"}</td><td>${f.params_b ?? "-"}B</td><td>${f.gb ?? "-"} GB</td><td><b>${f.bpw ?? f.error}</b></td>
      <td class="small">${Object.entries(f.types || {}).map(([k, v]) => `${k} ${pct(v)}`).join(" · ")}</td></tr>`), "")}</table></div>` : html`<div class="small muted">LLM_MODELS_DIR 에 GGUF 가 없습니다.</div>`;
}).catch(err => ui.error($("#w-gguf-out"), err));

function parseDevices() {
  return $("#t-devices").value.split("\n").map(l => l.split(",").map(s => s.trim())).filter(p => p.length >= 3 && p[0])
    .map(([name, mem, bw]) => ({ name, mem_gb: +mem, bw_gbs: +bw }));
}

$("#t-run").onclick = e => busy(e.target, () => api("/api/bigmodel/dist", { method: "POST", body: { ...($("#t-gguf").value ? { gguf: $("#t-gguf").value } : { hf_id: $("#t-hf").value.trim() }),
  devices: parseDevices(), link_gbps: +$("#t-link").value, latency_ms: +$("#t-lat").value, ctx: +$("#t-ctx").value } })).then(r => {
  const p = r.pipeline, t = r.tensor;
  $("#t-out").innerHTML = html`<div class="small">${r.model.arch.name || r.model.arch.arch} · 가중치 ${Math.round(r.model.weights_bytes / 2 ** 30 * 10) / 10} GB · 기기 하나로 ${r.single_device_tok_s ? `${r.single_device_tok_s} 토큰/초(들어가는 가장 빠른 기기)` : "들어가는 기기 없음"}</div>
    <h3>파이프라인 — ${p.fits ? html`<span class="badge ok">들어감</span>` : html`<span class="badge err">안 들어감</span>`} 토큰/초 <b>${p.tok_s}</b> · 전송 몫 ${pct(p.link_share)}</h3>
    <div class="table-wrap"><table><tr><th>기기</th><th>층</th><th>가중치</th><th>KV</th><th>들어가나</th><th>토큰당 ms</th></tr>
    ${html.join(p.stages.map(s => html`<tr><td>${s.device}</td><td>${s.layers}</td><td>${s.weights_gb} GB</td><td>${s.kv_gb} GB</td><td>${s.fits ? "예" : html`<span class="badge err">아니오</span>`}</td><td>${s.ms_per_token}</td></tr>`), "")}</table></div>
    <h3>텐서 — ${t.fits ? html`<span class="badge ok">들어감</span>` : html`<span class="badge err">안 들어감</span>`} 토큰/초 <b>${t.tok_s}</b> · 읽기 ${t.read_ms} ms + 결과 모으기 ${t.allreduce_ms} ms (전송 몫 ${pct(t.link_share)})</h3>
    <div class="small muted">경계마다 넘기는 은닉 벡터 ${r.per_hop_bytes} 바이트 · 링크 ${r.link_gbps} Gbit/s · 지연 ${r.latency_ms} ms. 파이프라인은 한 요청을 빠르게 하지 않고(기기들이 차례로 일함) 메모리를 늘립니다 — 동시 요청이 있어야 처리량이 늡니다.</div>`;
}).catch(err => ui.error($("#t-out"), err));

api("/api/bigmodel/machine").then(m => {
  $("#t-gguf").innerHTML = html`<option value="">(HF 모델로 어림)</option>${m.gguf.map(f => html`<option value="${f.name}">${f.name} · ${f.gb} GB</option>`)}`;
}).catch(err => ui.error($("#t-out"), err));
