(() => {
  const api = PlainOS, message = document.getElementById('message');
  let terminal, identity, offset = 0, queue = Promise.resolve();
  function error(e) { message.textContent = e.message; message.className = 'os-error'; }
  function dimensions() { return {cols: Math.max(10, Math.min(200, Math.floor((document.getElementById('terminal').clientWidth - 24) / 8.4))), rows: Math.max(2, Math.min(80, Math.floor((document.getElementById('terminal').clientHeight - 24) / 17)))}; }
  function resize() { if (!identity) return; const size = dimensions(); terminal.resize(size.cols, size.rows); queue = queue.then(() => api.call('terminal-write', {id: identity, ...size})).catch(error); }
  document.getElementById('open').onclick = async () => {
    try {
      const result = await api.call('terminal-open'); identity = result.id; offset = 0;
      if (terminal) terminal.dispose();
      terminal = new Terminal({fontSize: 14, fontFamily: 'monospace', cursorBlink: true, scrollback: 2000, theme: {background: '#101b20'}, linkHandler: {activate: () => {}}});
      terminal.open(document.getElementById('terminal')); resize(); terminal.focus();
      terminal.onData(data => { const id = identity; if (id) queue = queue.then(() => api.call('terminal-write', {id, data})).catch(error); });
      document.getElementById('open').disabled = true; document.getElementById('close').disabled = false;
      message.textContent = 'Root terminal connected.'; message.className = '';
    } catch (e) { error(e); }
  };
  document.getElementById('close').onclick = async () => {
    if (!identity) return;
    try { await api.call('terminal-close', {id: identity}); identity = null; terminal.write('\r\nSession closed.\r\n'); document.getElementById('open').disabled = false; document.getElementById('close').disabled = true; }
    catch (e) { error(e); }
  };
  let polling = false;
  setInterval(async () => {
    if (!identity || polling || document.hidden) return;
    polling = true;
    try {
      const result = await api.call('terminal-read', {id: identity, offset}); offset = result.offset;
      if (result.dropped) terminal.write('\r\n[Older output discarded while disconnected]\r\n');
      if (result.data) terminal.write(Uint8Array.from(atob(result.data), c => c.charCodeAt(0)));
      if (result.exited) document.getElementById('close').click();
    } catch (e) { error(e); identity = null; document.getElementById('open').disabled = false; document.getElementById('close').disabled = true; }
    finally { polling = false; }
  }, 200);
  window.addEventListener('resize', resize);
})();
