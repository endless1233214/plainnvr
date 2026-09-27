(() => {
  const api = PlainOS, $ = id => document.getElementById(id); let current = '/var/lib/plainnvr', parent = '/var/lib';
  const join = name => (current === '/' ? '' : current) + '/' + name;
  function error(e) { $('message').textContent = e.message; $('message').className = 'os-error'; }
  async function act(fn) { try { await fn(); } catch (e) { error(e); } }
  async function list(directory) {
    $('message').textContent = 'Loading…'; $('message').className = '';
    const result = await api.call('files-list', {path: directory}); current = result.path; parent = result.parent; $('path').value = current;
    $('entries').replaceChildren();
    for (const entry of result.entries) {
      const row = document.createElement('tr'), name = document.createElement('td');
      if (entry.directory || entry.symlink) { const button = api.text('button', entry.name + (entry.directory ? '/' : ' →')); button.onclick = () => act(() => list(join(entry.name))); name.append(button); }
      else name.textContent = entry.name;
      row.append(name, api.text('td', entry.directory ? '—' : (entry.bytes / 1024).toFixed(1) + ' KiB'), api.text('td', `${entry.mode} · ${entry.uid}:${entry.gid}`));
      const actions = document.createElement('td');
      function button(label, fn) { const control = api.text('button',label); control.onclick = () => act(fn); actions.append(control,document.createTextNode(' ')); }
      if (!entry.directory && !entry.symlink) button('Download', async () => {
        const file = await api.call('files-read', {path: join(entry.name)});
        const raw = Uint8Array.from(atob(file.data), c => c.charCodeAt(0)); const url = URL.createObjectURL(new Blob([raw]));
        const link = document.createElement('a'); link.href = url; link.download = file.name; link.click(); setTimeout(() => URL.revokeObjectURL(url),1000);
      });
      button('Rename', async () => { const name = prompt('New filename',entry.name); if (!name || name.includes('/') || name === '.' || name === '..') return; await api.call('files-rename',{path:join(entry.name),destination:join(name)}); await list(current); });
      button('Delete', async () => { const confirmation = prompt(`Type DELETE ${entry.name} to delete this item.`); if (!confirmation) return; await api.call('files-delete',{path:join(entry.name),confirmation}); await list(current); });
      row.append(actions); $('entries').append(row);
    }
    $('message').textContent = `${result.entries.length} items`;
  }
  $('location').onsubmit = event => { event.preventDefault(); act(() => list($('path').value)); };
  $('up').onclick = () => act(() => list(parent));
  $('mkdir').onclick = () => act(async () => { const name = prompt('New directory name'); if (!name || name.includes('/') || name === '.' || name === '..') return; await api.call('files-mkdir',{path:join(name)}); await list(current); });
  $('upload').onchange = () => act(async () => {
    const file = $('upload').files[0]; if (!file) return; if (file.size > 512 * 1024) throw Error('Use SFTP for files larger than 512 KiB.');
    const data = await new Promise((resolve,reject) => { const reader = new FileReader(); reader.onload = () => resolve(reader.result.split(',')[1]); reader.onerror = reject; reader.readAsDataURL(file); });
    await api.call('files-upload',{path:join(file.name),data}); $('upload').value = ''; await list(current);
  });
  // Opening a directory asks for the administrator password; no automatic prompt on page load.
})();
