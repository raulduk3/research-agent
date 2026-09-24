// The digest globe: one mark per digest entry on the page, a soft radial body, slow rotation.
// window.GLOBE.react(key, value, kind) pulses a ring on the entry's mark once a rating is stored.
// The marks come from the cards already rendered; the forms still post without this script.
(function(){
  let cv, ctx, N = [];
  const pulses = [];  // {k: mark index, t0, color}
  let a = 0, last = 0, running = false, W = 0, H = 0, dpr;
  const TILT = 0.38, ct = Math.cos(TILT), st = Math.sin(TILT);
  // spread the marks evenly over the sphere, in page order, so a card keeps its place across loads
  function place(i, n){ const y = n > 1 ? 1 - 2 * (i + 0.5) / n : 0, r = Math.sqrt(1 - y * y), lo = i * 2.39996; return {x: Math.cos(lo) * r * 0.82, y: y * 0.82, z: Math.sin(lo) * r * 0.82}; }
  function marks(){ const cards = Array.from(document.querySelectorAll('.feed[data-key]')); return cards.map((c, i) => Object.assign(place(i, cards.length), {n: {t: 'd', k: c.dataset.key, s: c.dataset.state || ''}})); }
  function size(){ dpr = window.devicePixelRatio || 1; W = cv.clientWidth; H = cv.clientHeight; cv.width = W * dpr; cv.height = H * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0); }
  function radius(){ return Math.max(1, Math.min(W, H) / 2 - Math.min(16, Math.min(W, H) * 0.06)); }
  function proj(p){ const ca = Math.cos(a), sa = Math.sin(a); const x = p.x * ca - p.z * sa, z0 = p.x * sa + p.z * ca; const y = p.y * ct - z0 * st, z = p.y * st + z0 * ct; const R = radius(); return {x: W / 2 + x * R, y: H / 2 - y * R, z}; }
  function draw(){
    if (!(W > 40 && H > 40)) { size(); }  // a zero-sized canvas (before layout, or mid-resize) would give a negative radius
    if (!(W > 40 && H > 40)) return;
    ctx.clearRect(0, 0, W, H);
    const R = radius(), cx = W / 2, cy = H / 2; const S = Math.max(0.55, Math.min(1, R / 140));  // mark scale: smaller globe, smaller marks
    // soft body
    const g = ctx.createRadialGradient(cx - R * 0.35, cy - R * 0.4, R * 0.1, cx, cy, R);
    g.addColorStop(0, 'rgba(255,255,255,0.55)'); g.addColorStop(0.7, 'rgba(255,255,255,0.10)'); g.addColorStop(1, 'rgba(43,40,34,0.06)');
    ctx.fillStyle = g; ctx.beginPath(); ctx.arc(cx, cy, R, 0, 6.283); ctx.fill();
    ctx.strokeStyle = 'rgba(43,40,34,0.35)'; ctx.lineWidth = 1.2; ctx.stroke();
    // graticule: latitude rings and meridians, front half only
    ctx.strokeStyle = 'rgba(43,40,34,0.12)';
    for (let lat = -60; lat <= 60; lat += 30) { const la = lat * Math.PI / 180; ctx.beginPath(); for (let i = 0; i <= 90; i++) { const lo = i / 90 * 6.283; const p = proj({x: Math.cos(la) * Math.cos(lo), y: Math.sin(la), z: Math.cos(la) * Math.sin(lo)}); if (p.z < 0) { ctx.moveTo(p.x, p.y); continue; } ctx.lineTo(p.x, p.y); } ctx.stroke(); }
    for (let lon = 0; lon < 180; lon += 30) { const lo = lon * Math.PI / 180; ctx.beginPath(); let pen = false; for (let i = 0; i <= 90; i++) { const la = -Math.PI / 2 + i / 90 * Math.PI; const p = proj({x: Math.cos(la) * Math.cos(lo), y: Math.sin(la), z: Math.cos(la) * Math.sin(lo)}); if (p.z < 0) { pen = false; continue; } if (!pen) { ctx.moveTo(p.x, p.y); pen = true; } else ctx.lineTo(p.x, p.y); } ctx.stroke(); }
    const P = N.map(proj);
    const order = P.map((p, k) => k).sort((u, v) => P[u].z - P[v].z);
    order.forEach(k => { const p = P[k], n = N[k].n; const depth = (p.z + 1) / 2; const rr = (3.2 + 1.6 * depth) * S; ctx.lineWidth = 1.3 * S;
      if (n.s === 'like') { ctx.fillStyle = 'rgba(43,40,34,' + (0.6 + 0.4 * depth).toFixed(2) + ')'; ctx.beginPath(); ctx.arc(p.x, p.y, rr, 0, 6.283); ctx.fill(); }
      else if (n.s === 'dislike') { ctx.strokeStyle = 'rgba(43,40,34,' + (0.15 + 0.2 * depth).toFixed(2) + ')'; ctx.beginPath(); ctx.arc(p.x, p.y, rr * 0.8, 0, 6.283); ctx.stroke(); }
      else if (n.s === 'skip') { ctx.fillStyle = 'rgba(43,40,34,' + (0.12 + 0.15 * depth).toFixed(2) + ')'; ctx.beginPath(); ctx.arc(p.x, p.y, rr * 0.6, 0, 6.283); ctx.fill(); }
      else { ctx.strokeStyle = 'rgba(43,40,34,' + (0.45 + 0.5 * depth).toFixed(2) + ')'; ctx.beginPath(); ctx.arc(p.x, p.y, rr, 0, 6.283); ctx.stroke(); }
      ctx.lineWidth = 1; });
  }
  function drawPulses(){ const now = performance.now(); const P = N.map(proj);
    for (let i = pulses.length - 1; i >= 0; i--) { const q = pulses[i]; const f = (now - q.t0) / 1400; if (f >= 1) { pulses.splice(i, 1); continue; } const p = P[q.k]; ctx.strokeStyle = q.color.replace('A', (0.9 * (1 - f)).toFixed(2)); ctx.lineWidth = 2 - f; ctx.beginPath(); ctx.arc(p.x, p.y, 4 + 34 * f, 0, 6.283); ctx.stroke(); }
    ctx.lineWidth = 1; }
  function frame(t){ if (!running || !cv) return; if (t - last > 33) { a += 0.0035; last = t; draw(); drawPulses(); } requestAnimationFrame(frame); }
  function start(){ if (running || !cv) return; running = true; requestAnimationFrame(frame); }
  function stop(){ running = false; }
  window.GLOBE = { react(key, value, kind){ const k = N.findIndex(m => m.n.k === key); if (k < 0) return; N[k].n.s = value;
      pulses.push({k, t0: performance.now(), color: 'rgba(43,40,34,A)'});  // one ring for every call: the globe marks a call, not a particular call
      start(); } };
  // A stored rating answers 303 (seen here as an opaque redirect): pulse the mark, then load the settled digest.
  // A refused one answers with the digest page and its error: swap it in, and nothing pulses.
  function rate(form, e){
    const b = e.submitter; if (!b || form.dataset.native || !window.fetch || !window.DOMParser) return;
    e.preventDefault();
    const body = new FormData(form); body.append(b.name, b.value);
    const key = form.closest('.feed').dataset.key;
    form.querySelectorAll('button').forEach(x => x.disabled = true);
    fetch(form.action, {method: 'POST', body, credentials: 'same-origin', redirect: 'manual'}).then(r => {
      if (r.type === 'opaqueredirect') { window.GLOBE.react(key, b.value, 'entry'); setTimeout(() => window.location.assign('/'), 1400); return; }
      return r.text().then(html => { const main = new DOMParser().parseFromString(html, 'text/html').querySelector('main'); if (!main) throw new Error('no page'); document.querySelector('main').replaceWith(main); mount(); });
    }).catch(() => { form.dataset.native = '1'; form.querySelectorAll('button').forEach(x => x.disabled = false);form.requestSubmit(b); });  // fall back to the plain post
  }
  function mount(){
    stop(); cv = document.getElementById('hero'); if (!cv) return;
    ctx = cv.getContext('2d'); N = marks(); pulses.length = 0; W = 0; H = 0;
    document.querySelectorAll('.feed[data-key] form[action="/ratings"]').forEach(f => f.addEventListener('submit', e => rate(f, e)));
    cv.addEventListener('click', () => running ? stop() : start());
    size(); draw(); start();
  }
  window.addEventListener('resize', () => { if (cv) { size(); draw(); } });
  document.addEventListener('visibilitychange', () => document.hidden ? stop() : start());
  mount();
})();
