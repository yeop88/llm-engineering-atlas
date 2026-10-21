// voice/call.html · voice/assist.html 공용 통화 줄 — 마이크(16kHz PCM16 조각 전송, VC1) · 소리 재생 대기열(VC4) · 끼어들기 감지(VC2)
// MediaRecorder(webm) 조각은 앞 조각 없이 풀 수 없어, 마이크 소리를 직접 16kHz 정수로 줄여 250ms 마다 보낸다.
// 끼어들기는 서버를 기다리지 않고 여기서 바로 멈춘다(왕복 지연이 끼어들기를 늦춘다) — 문턱은 서버 턴 관리와 같은 값(/api/voice/config).
const VoiceLine = {
  callId: null, params: null, onEvents: null, onBarge: null,
  ctx: null, stream: null, proc: null, src: null, timer: null, buf: [], busy: false,
  noise: -55, voiceMs: 0,
  queue: [], playing: null, current: null, spokenChars: 0, turn: null, pendingBarge: null,

  async start(callId, params, onEvents, onBarge) {
    Object.assign(this, { callId, params, onEvents, onBarge });
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 } });
    this.ctx = new AudioContext({ sampleRate: 16000 });
    this.src = this.ctx.createMediaStreamSource(this.stream);
    this.proc = this.ctx.createScriptProcessor(1024, 1, 1);
    this.proc.onaudioprocess = e => this.onAudio(e.inputBuffer.getChannelData(0));
    this.src.connect(this.proc);
    this.proc.connect(this.ctx.destination);
    this.timer = setInterval(() => this.flush(), 250);
  },

  stop() {
    clearInterval(this.timer);
    this.proc?.disconnect(); this.src?.disconnect();
    this.stream?.getTracks().forEach(t => t.stop());
    this.ctx?.close();
    Object.assign(this, { ctx: null, stream: null, proc: null, src: null, buf: [] });
  },

  onAudio(x) {
    // 브라우저가 16kHz 를 못 주면(일부 환경) 표본을 건너뛰어 줄인다 — 말소리 대역(8kHz 이하)이면 인식에 충분
    const step = (this.ctx?.sampleRate || 16000) / 16000;
    const n = Math.floor(x.length / step), pcm = new Int16Array(n);
    let sum = 0;
    for (let i = 0; i < n; i++) { const v = Math.max(-1, Math.min(1, x[Math.floor(i * step)])); pcm[i] = v * 32767; sum += v * v; }
    this.buf.push(pcm);
    const db = 20 * Math.log10(Math.sqrt(sum / Math.max(1, n)) + 1e-6), ms = n / 16;
    if (db > this.noise + this.params.margin_db) this.voiceMs += ms;
    else { this.voiceMs = 0; if (db < this.noise + 3) this.noise = 0.98 * this.noise + 0.02 * db; }
    if (this.speaking() && this.voiceMs >= this.params.barge_ms) this.barge();
  },

  async flush() {
    if (!this.buf.length || this.busy) return;
    const len = this.buf.reduce((a, b) => a + b.length, 0), all = new Int16Array(len);
    let o = 0;
    for (const b of this.buf) { all.set(b, o); o += b.length; }
    this.buf = [];
    this.busy = true;  // 서버가 인식하는 동안 온 조각은 쌓였다가 다음에 한꺼번에 — 순서가 바뀌지 않게 한 번에 하나만 보낸다
    try {
      const r = await fetch(`/api/voice/calls/${this.callId}/audio?speaking=${this.speaking() ? "true" : "false"}`, { method: "POST", body: all.buffer, headers: { "Content-Type": "application/octet-stream" } });
      if (r.ok) this.onEvents((await r.json()).events);
      else toast((await r.json()).detail || "음성 전송 실패", "err");
    } finally { this.busy = false; }
  },

  // ── 재생 ──
  speaking() { return !!this.playing; },
  say(ev) { this.queue.push(ev); if (!this.playing) this.next(); },
  next() {
    const ev = this.queue.shift();
    this.playing = null; this.current = ev || null;
    if (!ev) return;
    const done = () => { this.spokenChars += ev.text.length; this.next(); };
    if (ev.audio) {
      const a = new Audio(`/api/voice/tts/${ev.audio}`);
      a.onended = done; a.onerror = done;
      this.playing = a; a.play().catch(done);
    } else if (window.speechSynthesis) {  // 합성 서버(TTS_URL)가 없으면 브라우저 음성으로 같은 '읽는 글'을 읽는다
      const u = new SpeechSynthesisUtterance(ev.spoken);
      u.lang = "ko-KR"; u.onend = done; u.onerror = done;
      this.playing = u; speechSynthesis.speak(u);
    } else done();
  },
  newTurn() { this.spokenChars = 0; this.turn = null; },
  setTurn(n) {
    this.turn = n;
    if (this.pendingBarge) { this.postBarge({ ...this.pendingBarge, turn: n }); this.pendingBarge = null; }
  },
  barge() {
    if (this.playing instanceof Audio) this.playing.pause();
    if (window.speechSynthesis) speechSynthesis.cancel();
    const info = { spoken_chars: this.spokenChars, sentence: this.current?.n ?? null, at_ms: Math.round(performance.now()) };
    this.queue = []; this.playing = null; this.voiceMs = 0;
    this.onBarge?.(info);
    // 답 턴 번호는 스트림 끝(done)에서 오므로, 그 전에 끊기면 번호를 받은 뒤 보낸다
    if (this.turn != null) this.postBarge({ ...info, turn: this.turn }); else this.pendingBarge = info;
  },
  postBarge(b) { api(`/api/voice/calls/${this.callId}/barge`, { method: "POST", body: b }).catch(() => {}); },
};

// NDJSON 스트림 읽기 — 한 줄(사건)마다 onEvent
async function readLines(resp, onEvent) {
  const reader = resp.body.getReader(), dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n")) >= 0) { const line = buf.slice(0, i); buf = buf.slice(i + 1); if (line.trim()) onEvent(JSON.parse(line)); }
  }
}

const EMO = s => (s >= 0.75 ? "err" : s >= 0.5 ? "warn" : s >= 0.3 ? "" : "ok");
function budgetHtml(rep) {
  if (!rep) return "";
  return html`<div class="row small">${html.join(rep.stages.map(s => html`<span class="badge ${s.ms == null ? "" : s.over ? "warn" : "ok"}">${s.label} ${s.ms ?? "-"}/${s.budget}ms</span>`), " ")}
    <b>첫 소리 ${rep.first_audio_ms}ms</b> ${rep.within ? html`<span class="badge ok">예산 안</span>` : html`<span class="badge err">예산 ${rep.budget_ms}ms 초과</span>`}</div>`;
}
