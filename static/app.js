// Voice client: push-to-talk -> one binary blob per turn over the WebSocket; plays agent audio chunks in order.
(() => {
  const $ = (id) => document.getElementById(id);
  const MAX_REC_MS = 30000;
  let ws = null, sessionId = null, ended = false, reconnects = 0;
  let stream = null, recorder = null, recChunks = [], recTimer = null, recording = false, mime = '';
  // playback queue: audio for the current turn, played strictly in seq order
  let playTurn = -1, skipBefore = -1, pending = {}, nextSeq = 0, playing = false, lastTurnEnded = true;
  const player = new Audio();

  // ---------- UI helpers ----------
  function status(kind, text) {
    $('dot').className = 'dot ' + (kind || '');
    $('statusText').textContent = text;
  }
  function addMsg(role, text) {
    const d = document.createElement('div');
    d.className = 'msg ' + (role === 'agent' ? 'agent' : 'user');
    const who = document.createElement('small');
    who.textContent = role === 'agent' ? 'Asha' : 'You';
    d.append(who, document.createTextNode(text));
    $('transcript').append(d);
    $('transcript').scrollTop = $('transcript').scrollHeight;
  }
  function renderState(s) {
    $('stage').textContent = s.stage.replace('_', ' ');
    const rows = Object.entries(s.profile || {});
    if (s.selected_product) rows.push(['selected', s.selected_product]);
    if (s.callback_time) rows.push([s.callback_confirmed ? 'callback' : 'callback (pending)',
                                    new Date(s.callback_time).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' })]);
    if (s.outcome) rows.push(['outcome', s.outcome]);
    const dl = $('profile'); dl.innerHTML = '';
    for (const [k, v] of rows) {
      const dt = document.createElement('dt'); dt.textContent = k.replace(/_/g, ' ');
      const dd = document.createElement('dd'); dd.textContent = v;
      dl.append(dt, dd);
    }
    const ol = $('shortlist'); ol.innerHTML = '';
    if (!s.shortlist || !s.shortlist.length) {
      const li = document.createElement('li'); li.style.color = 'var(--muted)'; li.textContent = 'not yet'; ol.append(li);
    }
    for (const p of s.shortlist || []) {
      const li = document.createElement('li'); li.textContent = `${p.insurer} — ${p.name}`; ol.append(li);
    }
  }
  function addLatency(l) {
    const tr = document.createElement('tr');
    for (const v of [l.turn, l.stt_ms, l.llm_ms, l.tts_first_ms, l.total_first_audio_ms]) {
      const td = document.createElement('td'); td.textContent = v == null ? '—' : v; tr.append(td);
    }
    $('lat').append(tr);
  }
  function showLink(ev) {
    const c = $('linkCard'); c.innerHTML = '';
    const box = document.createElement('div'); box.className = 'linkcard';
    const t = document.createElement('div'); t.textContent = `${ev.insurer} — ${ev.name}`; t.style.fontWeight = '600';
    const a = document.createElement('a'); a.href = ev.url; a.target = '_blank'; a.rel = 'noopener'; a.textContent = 'Open the official product page ↗';
    const n = document.createElement('div'); n.className = 'hint'; n.style.textAlign = 'left';
    n.textContent = 'Purchase and payment happen only on the insurer\'s official website.';
    box.append(t, a, n); c.append(box);
  }
  function endCall(outcome) {
    ended = true;
    $('talk').disabled = true; $('sendTyped').disabled = true; $('typed').disabled = true; $('hangup').disabled = true;
    const e = $('ended'); e.style.display = 'block';
    e.textContent = 'Call ended' + (outcome ? ` · ${outcome.replace(/_/g, ' ')}` : '') + '. Reload the page to start again.';
    if (!playing) status('', 'Call ended');
    if (stream) stream.getTracks().forEach((t) => t.stop());
  }

  // ---------- playback ----------
  function b64ToBlob(b64, type) {
    const bin = atob(b64); const buf = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
    return new Blob([buf], { type });
  }
  function onAudio(m) {
    if (m.turn < skipBefore) return;            // interrupted turn
    if (m.turn !== playTurn) { playTurn = m.turn; pending = {}; nextSeq = 0; }
    pending[m.seq] = m;
    pump();
  }
  function pump() {
    if (playing) return;
    const m = pending[nextSeq];
    if (!m) { if (lastTurnEnded && !recording && !ended) status('', 'Your turn — hold to talk'); return; }
    delete pending[nextSeq]; nextSeq++;
    playing = true; status('speaking', 'Asha is speaking…');
    const url = URL.createObjectURL(b64ToBlob(m.data, m.mime));
    player.src = url;
    player.onended = player.onerror = () => { URL.revokeObjectURL(url); playing = false; pump(); if (ended && !playing) status('', 'Call ended'); };
    player.play().catch(() => { playing = false; pump(); });
  }
  function stopPlayback() {
    skipBefore = playTurn + 1; pending = {}; player.pause(); playing = false;
  }

  // ---------- WebSocket ----------
  function send(obj) { if (ws && ws.readyState === 1) ws.send(typeof obj === 'string' || obj instanceof Blob ? obj : JSON.stringify(obj)); }
  function connect() {
    const proto = location.protocol === 'https:' ? 'wss://' : 'ws://';
    ws = new WebSocket(`${proto}${location.host}/ws/${sessionId}`);
    ws.onopen = () => { reconnects = 0; send({ type: 'hello', mime }); $('talk').disabled = false; $('callErr').textContent = ''; };
    ws.onmessage = (e) => {
      const m = JSON.parse(e.data);
      switch (m.type) {
        case 'transcript': if (!m.replay) addMsg(m.role, m.text); break;  // replays after a reconnect: page already has them
        case 'state': renderState(m); break;
        case 'thinking': status('thinking', 'Thinking…'); lastTurnEnded = false; break;
        case 'audio': onAudio(m); break;
        case 'audio_end': lastTurnEnded = true; pump(); break;
        case 'latency': addLatency(m); break;
        case 'purchase_link': showLink(m); break;
        case 'callback_booked': break;
        case 'notice': $('callErr').textContent = m.message; break;
        case 'error': $('callErr').textContent = m.message; if (m.fatal) endCall(); break;
        case 'end': endCall(m.outcome); break;
      }
    };
    ws.onclose = () => {
      $('talk').disabled = true;
      if (ended) return;
      if (reconnects < 5) {
        reconnects++; status('thinking', 'Reconnecting…');
        setTimeout(connect, 1000 * reconnects);
      } else { $('callErr').textContent = 'Connection lost. Reload the page to start again.'; }
    };
  }

  // ---------- recording ----------
  function pickMime() {
    for (const t of ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus']) {
      if (window.MediaRecorder && MediaRecorder.isTypeSupported(t)) return t;
    }
    return '';
  }
  function startRec() {
    if (recording || ended || !stream || $('talk').disabled) return;
    stopPlayback();
    recChunks = [];
    recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
    recorder.ondataavailable = (e) => { if (e.data.size) recChunks.push(e.data); };
    recorder.onstop = () => {
      const blob = new Blob(recChunks, { type: recorder.mimeType || mime });
      if (blob.size > 1500) { send(blob); status('thinking', 'Thinking…'); lastTurnEnded = false; }
      else status('', 'Too short — hold the button while you speak');
    };
    recorder.start();
    recording = true; $('talk').classList.add('rec'); $('talk').textContent = 'Release to send';
    status('listening', 'Listening…');
    recTimer = setTimeout(stopRec, MAX_REC_MS);
  }
  function stopRec() {
    if (!recording) return;
    clearTimeout(recTimer); recording = false;
    $('talk').classList.remove('rec'); $('talk').textContent = 'Hold to talk';
    if (recorder && recorder.state !== 'inactive') recorder.stop();
  }

  // ---------- wiring ----------
  $('startForm').onsubmit = async (e) => {
    e.preventDefault();
    $('startErr').textContent = ''; $('startBtn').disabled = true;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    } catch (err) {
      $('startErr').textContent = 'Microphone permission is needed for the voice call.'; $('startBtn').disabled = false; return;
    }
    mime = pickMime();
    player.play().catch(() => {}); // unlock audio playback on this user gesture
    try {
      const r = await fetch('/api/session', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: $('name').value, phone: $('phone').value, access_code: $('code').value }),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail || 'Could not start the session.');
      sessionId = j.session_id;
    } catch (err) {
      $('startErr').textContent = err.message; $('startBtn').disabled = false;
      stream.getTracks().forEach((t) => t.stop()); return;
    }
    $('start').style.display = 'none'; $('call').style.display = 'block';
    status('thinking', 'Connecting…');
    connect();
  };
  const talk = $('talk');
  talk.addEventListener('pointerdown', (e) => { e.preventDefault(); talk.setPointerCapture(e.pointerId); startRec(); });
  talk.addEventListener('pointerup', stopRec);
  talk.addEventListener('pointercancel', stopRec);
  document.addEventListener('keydown', (e) => {
    if (e.code !== 'Space' || e.repeat || document.activeElement.tagName === 'INPUT' || $('call').style.display !== 'block') return;
    e.preventDefault(); startRec();
  });
  document.addEventListener('keyup', (e) => {
    if (e.code !== 'Space' || document.activeElement.tagName === 'INPUT') return;
    e.preventDefault(); stopRec();
  });
  function sendTyped() {
    const v = $('typed').value.trim();
    if (!v || ended) return;
    stopPlayback(); send({ type: 'text', text: v }); $('typed').value = '';
  }
  $('sendTyped').onclick = sendTyped;
  $('typed').addEventListener('keydown', (e) => { if (e.key === 'Enter') sendTyped(); });
  $('hangup').onclick = () => { stopPlayback(); send({ type: 'hangup' }); };
})();
