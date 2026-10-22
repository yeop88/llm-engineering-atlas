// bigmodel/plan.html 화면 스크립트 — 메모리 계획(BM1), 층 단위 스트리밍 실측(BM2), 설정별 서버 실측 · 전문가 캐시(BM3)
let lastPlan = null;
const gb = v => (v == null ? "-" : `${v} GB`);
const pct = v => (v == null ? "-" : `${Math.round(v * 100)}%`);

function devices() {
  return { gpu_gb: +$("#d-gpu").value, gpu_bw: +$("#d-gpubw").value, cpu_gb: +$("#d-cpu").value, cpu_bw: +$("#d-cpubw").value,
    disk_bw: +$("#d-disk").value, shared: $("#d-shared").checked };
}

function src() {
  return $("#p-gguf").value ? { gguf: $("#p-gguf").value } : { hf_id: $("#p-hf").value.trim(), bits: $("#p-bits").value };
}

$("#p-run").onclick = e => busy(e.target, () => api("/api/bigmodel/plan", { method: "POST", body: { ...src(), ctx: +$("#p-ctx").value, parallel: +$("#p-par").value,
  kv_type: $("#p-kv").value, devices: devices() } })).then(r => {
  lastPlan = r;
  const m = r.model, a = m.arch;
  $("#p-out").innerHTML = html`<div class="small">${a.name || a.arch} · 층 ${a.layers} · 은닉 ${a.hidden}${a.experts ? ` · 전문가 ${a.experts}개 중 ${a.experts_used}개(쓰는 몫 ${pct(r.active_frac)})` : ""}
      · 파라미터 ${m.params_b}B · ${m.exact ? "GGUF 텐서별 정확" : `HF 설정 × ${m.bits} 어림`}</div>
    <div class="grid cols-2"><div><b>가중치 ${gb(r.weights_gb)}</b><ul class="small">${html.join(Object.entries(m.by_kind_gb).filter(([, v]) => v > 0).map(([k, v]) => html`<li>${k} ${v} GB</li>`), "")}</ul></div>
      <div><b>KV ${gb(r.kv.total_gb)}</b> <span class="small muted">(맥락 ${r.kv.ctx} × 동시 ${r.kv.parallel} · ${r.kv.kv_type})</span>
        <ul class="small"><li>전체 어텐션 층 ${r.kv.full_layers} · 슬라이딩 창 층 ${r.kv.swa_layers} · KV 없는 층 ${r.kv.no_kv_layers}</li><li>토큰당 ${Math.round(r.kv.per_token_bytes / 1024)} KB</li>
        ${r.kv.state_bytes ? html`<li>고정 상태(선형 어텐션) ${Math.round(r.kv.state_bytes / 2 ** 20)} MB</li>` : ""}<li>계산 버퍼 ${gb(r.compute_gb)}</li></ul></div></div>
    <div class="table-wrap"><table><tr><th>배치</th><th>GPU</th><th>CPU(RAM)</th><th>디스크</th><th>들어가나</th><th>토큰/초 어림</th><th>시간 몫 GPU · CPU · 디스크</th><th>서버 인자</th></tr>
      ${html.join(r.options.map(o => html`<tr><td>${o.label}${o.name === r.best ? html` <span class="badge ok">추천</span>` : ""}</td><td>${o.gpu_gb}</td><td>${o.cpu_gb}</td><td>${o.disk_gb}</td>
        <td>${o.fits ? html`<span class="badge ok">예</span>` : html`<span class="badge err">아니오</span>`}</td><td><b>${o.tok_s ?? "-"}</b></td>
        <td class="small">${pct(o.time_split.gpu)} · ${pct(o.time_split.cpu)} · ${pct(o.time_split.disk)}</td><td class="mono small">${o.args.join(" ")}</td></tr>`), "")}</table></div>
    <div class="small muted">토큰/초는 '쓰는 가중치 ÷ 메모리 대역폭' 지붕선 어림입니다(계산 · 동기화 비용 제외 — 실측은 아래 BM3).</div>`;
  const ggufOk = !!$("#p-gguf").value;
  $("#o-configs").innerHTML = ggufOk ? html`${r.options.filter(o => !o.args[0]?.startsWith("(")).map((o, i) => html`<label class="row small m-0"><input type="checkbox" value="${i}" ${o.fits ? "checked" : ""}>
      ${o.label} <span class="mono muted">${o.args.join(" ")}</span> · 어림 ${o.tok_s ?? "-"} 토큰/초</label>`)}` : html`<span class="muted">실측은 가지고 있는 GGUF 로 계획했을 때 할 수 있습니다.</span>`;
  $("#o-run").disabled = !ggufOk;
}).catch(err => ui.error($("#p-out"), err));

$("#o-run").onclick = e => {
  const opts = lastPlan.options.filter(o => !o.args[0]?.startsWith("("));
  const configs = [...document.querySelectorAll("#o-configs input:checked")].map(x => opts[+x.value]).map(o => ({ label: o.name, args: o.args, est: o.tok_s }));
  if (!configs.length) { toast("배치를 하나 이상 고르세요", "err"); return; }
  runJobInto(e.target, "/api/bigmodel/offload/sweep", { gguf: $("#p-gguf").value, configs: configs.map(({ label, args }) => ({ label, args })), ctx: +$("#o-ctx").value }, $("#o-progress"), r => {
    const est = Object.fromEntries(configs.map(c => [c.label, c.est]));
    $("#o-out").innerHTML = html`<div class="small muted">${r.gguf} · ${r.seconds}초 · run #${r.run_id}</div>
      <div class="table-wrap"><table><tr><th>배치</th><th>생성 토큰/초</th><th>어림</th><th>미리 채우기 토큰/초</th><th>KV MiB</th><th>RSS MiB</th><th>올리기(초)</th><th>상태</th></tr>
      ${html.join(r.rows.map(x => html`<tr><td>${x.label}</td><td><b>${x.gen_tok_s ?? "-"}</b></td><td class="muted">${est[x.label] ?? "-"}</td><td>${x.prompt_tok_s ?? "-"}</td><td>${x.kv_cache_mib ?? "-"}</td>
        <td>${x.rss_mib ?? "-"}</td><td>${x.load_s ?? "-"}</td><td>${x.status === "ok" ? html`<span class="badge ok">ok</span>` : html`<span class="badge err small">${x.error}</span>`}</td></tr>`), "")}</table></div>`;
  }).catch(err => ui.error($("#o-out"), err));
};

$("#l-run").onclick = e => runJobInto(e.target, "/api/bigmodel/layered", { hf_id: $("#l-hf").value.trim() || null, prompt: $("#l-prompt").value, max_new: +$("#l-new").value },
  $("#l-progress"), r => {
    const row = (name, x) => html`<tr><td>${name}</td><td>${x.stream.peak_resident_mb} MB</td><td>${x.full.resident_mb} MB</td><td>${pct(x.memory_saved)}</td>
      <td>${x.stream.decode_tok_s ?? "-"}</td><td>${x.full.decode_tok_s ?? "-"}</td><td>${x.slowdown ?? "-"}배</td><td>${x.stream.read_mb_per_token} MB</td>
      <td>${x.stream.read_s} / ${x.stream.compute_s}</td><td>${x.max_logit_diff} · ${x.same_tokens}/${x.of}</td></tr>`;
    $("#l-out").innerHTML = html`<div class="small muted">${r.hf_id} · 층 ${r.prefetch.layers}개(층 하나 ${r.prefetch.layer_mb} MB · 층 밖 ${r.prefetch.base_mb} MB) · 프롬프트 ${r.prompt_tokens}토큰 · ${r.seconds}초 · run #${r.run_id}</div>
      <div class="table-wrap"><table><tr><th></th><th>최대 상주(스트리밍)</th><th>통째</th><th>메모리 절약</th><th>생성 토큰/초</th><th>통째 토큰/초</th><th>느려짐</th><th>토큰당 읽기</th><th>읽기 / 계산(초)</th><th>로짓 차 · 같은 토큰</th></tr>
        ${row("미리 읽기 켬", r.prefetch)}${row("미리 읽기 끔", r.no_prefetch)}</table></div>
      <div class="pre small">${r.answer}</div>`;
  }).catch(err => ui.error($("#l-out"), err));

$("#x-run").onclick = e => busy(e.target, () => api("/api/bigmodel/offload/experts", { method: "POST", body: { source: $("#x-src").value, hf_id: $("#x-hf").value.trim() || null,
  skew: +$("#x-skew").value, experts: +$("#x-experts").value, used: +$("#x-used").value, expert_mb: +$("#x-mb").value,
  gpu_bw: +$("#d-gpubw").value, cpu_bw: +$("#d-cpubw").value } })).then(r => {
  const u = r.usage;
  $("#x-out").innerHTML = html`<div class="small">층 ${r.layers} · 전문가 ${r.experts} 중 ${r.used} · 상위 10% 전문가가 쓰임의 <b>${pct(u.mean_top10_share)}</b>(고르게면 ${pct(u.uniform_top10_share)})</div>
    <div class="table-wrap"><table><tr><th>GPU 에 둘 비율</th><th>개수</th><th>고정(인기)</th><th>LRU</th><th>LFU</th><th>전문가 읽기 ms(고정)</th><th>LRU ms</th></tr>
      ${html.join(r.curve.map(c => html`<tr><td>${pct(c.gpu_frac)}</td><td>${c.capacity}</td><td><b>${pct(c.static)}</b></td><td>${pct(c.lru)}</td><td>${pct(c.lfu)}</td><td>${c.static_ms}</td><td>${c.lru_ms}</td></tr>`), "")}</table></div>`;
}).catch(err => ui.error($("#x-out"), err));

api("/api/bigmodel/machine").then(m => {
  $("#p-gguf").innerHTML = html`<option value="">(HF 모델로 어림)</option>${m.gguf.map(f => html`<option value="${f.name}">${f.name} · ${f.gb} GB</option>`)}`;
  const dev = m.accelerator?.devices?.[0];
  if (dev) { $("#d-gpu").value = dev.total_gb; $("#d-shared").checked = false; }
  $("#d-cpu").value = Math.max(1, Math.floor(m.ram_free_gb));
  $("#p-machine").textContent = `이 기기: RAM ${m.ram_gb} GB(지금 빈 ${m.ram_free_gb} GB) · CPU ${m.cpus}코어 · ${dev ? `GPU ${dev.name} ${dev.total_gb} GB` : "PyTorch 가 보는 GPU 없음(내장 GPU 는 llama.cpp Vulkan 으로 — 메모리 · 대역폭을 직접 넣으세요)"} · llama-server ${m.llama_server ? "설정됨" : "미설정"}`;
}).catch(err => ui.error($("#p-machine"), err));
