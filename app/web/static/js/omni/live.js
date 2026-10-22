// omni/live.html 화면 스크립트 — 영상 통화 프레임 · 장면 색인(OM3), 말 + 화면 융합(OM4), 인식 확정(OM2), 키프레임 채점(OM3)
let sid = null;
let camTimer = null;
let stream = null;
let seq = 0;
const llmRef = () => ({ provider: $("#c-provider").value || null, model: $("#c-model").value.trim() || null });
const phone = () => $("#c-phone").value.trim();

function sceneList(scenes) {
  return scenes.length ? html`<div class="thumbs">${scenes.map(sc => html`<figure><img src="/api/omni/frames/${sid}/${sc.frame}" alt="${sc.caption || "장면"}" loading="lazy">
    <figcaption>${sc.t}초 ${sc.code ? html`<b>${sc.code}</b>` : ""} ${sc.caption}</figcaption></figure>`)}</div>` : html`<div class="small muted">아직 장면이 없습니다.</div>`;
}

async function refresh() {
  const s = await api(`/api/omni/sessions/${sid}`);
  $("#c-scenes").innerHTML = sceneList(s.scenes);
}

// 통화 시작 = 글 없는 영상 메시지 하나(세션 만들기 · 같은 번호의 세션에 잇기)
$("#c-start").onclick = e => busy(e.target, () => api("/api/omni/send", { method: "POST", body: { channel: "video", address: phone(), text: "", external_id: `start-${Date.now()}`,
  collection_id: +$("#c-col").value || null, ...llmRef() } })).then(r => {
  sid = r.session_id;
  $("#c-info").innerHTML = html`세션 <b>#${sid}</b> · 고객 ${r.customer} · ${r.same_session ? "열린 세션에 이어짐" : "새 세션"}`;
  ["#c-cam", "#c-upload", "#q-ask"].forEach(s => { $(s).disabled = false; });
  return refresh();
}).catch(err => ui.error($("#c-info"), err));

async function sendFrame() {
  const v = $("#c-view"), cv = $("#c-canvas");
  if (!v.videoWidth) return;
  cv.width = v.videoWidth; cv.height = v.videoHeight;
  cv.getContext("2d").drawImage(v, 0, 0);
  const blob = await new Promise(res => cv.toBlob(res, "image/jpeg", 0.85));
  const form = new FormData();
  form.append("file", blob, "frame.jpg");
  const ref = llmRef();
  if (ref.provider) form.append("provider", ref.provider);
  if (ref.model) form.append("model", ref.model);
  const r = await api(`/api/omni/sessions/${sid}/frame`, { method: "POST", form });
  $("#c-gate").textContent = `받은 프레임 ${r.seen ?? "-"} · 읽은 장면 ${r.described ?? "-"} · 직전과 밝기 차 ${r.diff ?? "-"}${r.kept ? " → 새 장면" : ""}`;
  if (r.kept) await refresh();
}

$("#c-cam").onclick = async () => {
  if (camTimer) {
    clearInterval(camTimer); camTimer = null;
    stream?.getTracks().forEach(t => t.stop());
    $("#c-view").hidden = true; $("#c-cam").textContent = "카메라 켜기";
    return;
  }
  try {
    stream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480 } });
  } catch (err) { toast(`카메라를 열 수 없습니다: ${err.message}`, "err"); return; }
  $("#c-view").srcObject = stream; $("#c-view").hidden = false; $("#c-cam").textContent = "카메라 끄기";
  let sending = false;
  // 앞 프레임의 비전 읽기가 끝나기 전에는 다음 프레임을 보내지 않는다 — 읽기가 간격보다 길면 요청이 쌓여 지연만 늘어난다
  camTimer = setInterval(() => { if (sending) return; sending = true; sendFrame().catch(err => toast(err.message, "err")).finally(() => { sending = false; }); },
    Math.max(300, +$("#c-interval").value * 1000));
};

$("#c-upload").onclick = e => {
  const f = $("#c-file").files[0];
  if (!f) { toast("영상 파일을 고르세요", "err"); return; }
  const form = new FormData();
  form.append("file", f);
  form.append("interval", $("#c-interval").value);
  const ref = llmRef();
  if (ref.provider) form.append("provider", ref.provider);
  if (ref.model) form.append("model", ref.model);
  busy(e.target, () => api(`/api/omni/sessions/${sid}/video`, { method: "POST", form })).then(async job => {
    $("#c-progress").hidden = false;
    const done = await pollJob(job.id, j => { $("#c-progress").innerHTML = ui.jobProgress(j); }, 1500);
    $("#c-progress").hidden = true;
    if (done.status !== "done") { ui.error($("#c-gate"), done.error || done.status); return; }
    const r = done.result;
    $("#c-gate").textContent = `프레임 ${r.frames}장 중 장면 ${r.kept}장만 읽음(읽기 ${Math.round(r.saved * 100)}% 절약) · ${r.seconds}초`;
    await refresh();
  }).catch(err => ui.error($("#c-gate"), err));
};

$("#q-ask").onclick = e => busy(e.target, () => api("/api/omni/send", { method: "POST", body: { channel: "video", address: phone(), text: $("#q-text").value,
  external_id: `live-${Date.now()}-${seq++}`, ...llmRef() } })).then(r => {
  const f = r.fuse || {};
  $("#q-out").innerHTML = html`<div class="small">${f.pointer ? html`<span class="badge">${{ now: "지금 장면", past: "앞 장면", implicit: "가리킴 없음 → 지금 장면 참고" }[f.pointer]}</span>` : html`<span class="badge muted">화면 안 씀</span>`}
      ${f.scene ? html` ${f.scene.t}초 장면 ${f.scene.code ? html`<b>${f.scene.code}</b>` : ""} ${f.scene.caption}` : ""}</div>
    ${f.changed ? html`<div class="small muted">검색 질문: ${f.query}</div>` : ""}
    ${r.reply ? html`<div class="pre">${r.reply.text}</div>${r.reply.spoken ? html`<div class="small"><b>읽는 글</b> ${r.reply.spoken}</div>` : ""}` : html`<div class="small muted">${r.error || "답 없음"}</div>`}
    <div class="small muted">${r.seconds}초</div>${ui.aiNotice(r.notice, r.trace_id)}`;
}).catch(err => ui.error($("#q-out"), err));

function stabHtml(r) {
  return html`<div class="row small"><span>가설 ${r.hypotheses}개</span><span>확정 오류 <b>${r.commit_errors}</b></span><span>깜빡임 ${r.flicker}</span>
      <span>확정 지연 평균 ${r.mean_lag ?? "-"} 가설</span><span>${r.early_at ? `가설 ${r.early_at} 에서 문장 끝 확정 → 미리 검색` : "끝날 때까지 기다림"}</span></div>
    <div class="table-wrap"><table><tr><th>#</th><th>확정</th><th>잠정</th></tr>
    ${html.join(r.steps.map(s => html`<tr><td>${s.n}</td><td>${s.committed}${s.new ? html` <span class="badge ok">+${s.new}</span>` : ""}</td><td class="muted">${s.tentative}</td></tr>`), "")}</table></div>`;
}

$("#r-run").onclick = e => busy(e.target, () => api("/api/omni/stabilize", { method: "POST", body: { text: $("#r-text").value, agree: +$("#r-agree").value,
  noise: +$("#r-noise").value, seed: Date.now() % 1000 } })).then(r => { $("#r-out").innerHTML = stabHtml(r); }).catch(err => ui.error($("#r-out"), err));

// 브라우저 음성 인식(있으면)의 중간 결과를 가설로 모아 같은 확정 규칙에 넣는다
$("#r-mic").onclick = () => {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { toast("이 브라우저에는 음성 인식이 없습니다 — 글로 시험하세요", "err"); return; }
  const rec = new SR();
  rec.lang = "ko-KR"; rec.interimResults = true; rec.continuous = false;
  const hyps = [];
  rec.onresult = ev => { const t = [...ev.results].map(x => x[0].transcript).join(""); if (t && t !== hyps.at(-1)) hyps.push(t.trim()); };
  rec.onend = () => {
    if (!hyps.length) return;
    api("/api/omni/stabilize", { method: "POST", body: { hypotheses: hyps, agree: +$("#r-agree").value } }).then(r => { $("#r-out").innerHTML = stabHtml(r); }).catch(err => ui.error($("#r-out"), err));
  };
  rec.start();
  toast("말씀하세요 — 말이 끝나면 확정 과정을 보여 줍니다");
};

$("#k-run").onclick = e => busy(e.target, () => api("/api/omni/keyframes", { method: "POST", body: { codes: $("#k-codes").value.split(",").map(s => s.trim()).filter(Boolean),
  scene_seconds: +$("#k-sec").value, threshold: +$("#k-th").value, min_gap: +$("#k-gap").value } })).then(r => {
  $("#k-out").innerHTML = html`<div class="table-wrap"><table><tr><th>프레임</th><th>장면</th><th>읽은 프레임</th><th>놓친 장면</th><th>더 남긴 프레임</th><th>읽기 절약</th></tr>
    <tr><td>${r.frames}</td><td>${r.scenes}</td><td>${r.kept}</td><td><b>${r.missed}</b></td><td>${r.extra}</td><td>${Math.round(r.saved * 100)}%</td></tr></table></div>
    <div class="small muted">키프레임 시각: ${r.keyframes.map(k => `${k[0]}초(장면 ${k[1] + 1})`).join(", ")}</div>`;
}).catch(err => ui.error($("#k-out"), err));

setupCollectionPickers({ col: $("#c-col") }).catch(e => ui.error($("#c-info"), e));
