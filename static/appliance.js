/* OS features are shown only when the appliance broker is installed. */
(() => {
  const api = window.PlainOS;
  let host, system = {}, inventory = {}, keys = [];
  const el = id => document.getElementById('os-' + id);
  const fmt = n => (Number(n || 0) / 1e9).toFixed(1) + ' GB';
  function notice(value, error = false) { el('message').textContent = value; el('message').className = error ? 'os-error' : 'os-status'; }
  async function action(fn) {
    notice('Working…');
    try { const result = await fn(); notice(result?.message || 'Saved.'); return result; }
    catch (error) { notice(error.message, true); }
  }
  function field(id, label, value = '', type = 'text') {
    return `<label>${label}<input id="os-${id}" type="${type}" value="${value}" autocomplete="off"></label>`;
  }
  function pane(id, title, body) { return `<section class="os-pane" id="os-${id}" hidden><h3>${title}</h3>${body}</section>`; }
  function render() {
    host = document.createElement('section'); host.className = 'panel os-settings';
    host.innerHTML = `<h2>PlainNVR OS</h2><p>Manage this appliance, its access, network and recording storage.</p><div class="os-tabs" role="tablist">${['System','Network','SSH','Storage','Updates','Tools','Logs'].map((name, i) => `<button type="button" role="tab" data-os-tab="${name.toLowerCase()}" aria-selected="${i === 0}">${name}</button>`).join('')}</div><p id="os-message" role="status" aria-live="polite"></p>` +
      pane('system', 'System', `<pre id="os-summary"></pre><div class="os-grid"><form id="os-hostname-form">${field('hostname','Hostname')}<button>Save hostname</button></form><form id="os-clock-form">${field('timezone','Timezone','America/New_York')}<label><input id="os-ntp" type="checkbox">Synchronize time automatically</label><button>Save time settings</button></form></div><div class="os-actions"><button type="button" id="os-reboot">Restart appliance</button><button type="button" id="os-poweroff">Shut down</button></div>`) +
      pane('network', 'Network', `<pre id="os-addresses"></pre><form id="os-network-form"><div class="os-grid"><label>Interface<select id="os-interface"></select></label><label>Addressing<select id="os-network-mode"><option value="dhcp">Automatic (DHCP)</option><option value="static">Static</option></select></label></div><div id="os-static"><div class="os-grid">${field('address','IP address / prefix','', 'text')}${field('gateway','Gateway')}${field('dns','DNS servers (space separated)')}</div></div><p class="os-warning">A network change may disconnect this browser. Reconnect at the new address and confirm within two minutes, or the previous settings return automatically.</p><button>Apply network settings</button></form><div id="os-network-pending" hidden><p id="os-network-deadline"></p><button id="os-network-confirm">Connection works — keep settings</button> <button id="os-network-revert">Revert now</button></div>`) +
      pane('ssh', 'SSH access', `<p>Key-only login as <code>plainnvr-admin</code>. This account can use sudo to administer the appliance. Password and root SSH login are disabled.</p><label><input id="os-ssh-enabled" type="checkbox">Enable SSH</label><div id="os-keys"></div><fieldset><legend>Add a public key</legend>${field('key-label','Key name')}<label>Public key<textarea id="os-key-public" placeholder="ssh-ed25519 AAAA…"></textarea></label><label>Or select a public key file<input id="os-key-file" type="file" accept=".pub,text/plain"></label><button type="button" id="os-key-add">Add to list</button></fieldset><button id="os-ssh-save">Save SSH settings</button>`) +
      pane('storage', 'Storage', `<button id="os-storage-refresh">Refresh disks and pools</button><p class="os-note">OS drives are protected from the guided formatting and pool creation controls.</p><div class="os-table-scroll"><table><thead><tr><th>Device</th><th>Size</th><th>Filesystem / mount</th></tr></thead><tbody id="os-devices"></tbody></table></div><pre id="os-pools"></pre><div class="os-actions">${field('scrub-pool','Pool name')}<button id="os-scrub">Start scrub</button><button id="os-scrub-stop">Stop scrub</button></div><fieldset><legend>Prepare a blank recording disk</legend><label>Blank, unused disk<select id="os-format-disk"></select></label><button id="os-format">Format as ext4</button><button id="os-gparted" hidden>Open GParted on this monitor</button></fieldset><form id="os-storage-form"><h3>Recording destination</h3><label>Destination<select id="os-target"><option value="">Add a destination</option></select></label><div id="os-new-target">${field('storage-label','Destination name')}<label>Storage type<select id="os-storage-mode"><option value="default">Installed data filesystem</option><option value="filesystem">Existing ext4 / XFS partition</option><option value="smb">SMB network share</option><option value="zfs-create">Create ZFS pool</option><option value="zfs-import">Import ZFS pool</option></select></label><div id="os-filesystem-fields"><label>Filesystem<select id="os-filesystem"></select></label></div><div id="os-smb-fields"><p class="os-warning">SMB may reduce performance. Network/NAS interruptions can stop recording. The configuration database stays local.</p><div class="os-grid">${field('smb-host','Server IP or hostname')}${field('smb-share','Share name')}${field('smb-username','SMB username')}${field('smb-password','SMB password','','password')}${field('smb-domain','Domain (optional)')}</div><label><input id="os-smb-ack" type="checkbox">I understand the performance and availability tradeoff.</label></div><div id="os-zfs-fields">${field('pool','Pool name','recordings')}<label>Layout<select id="os-layout"><option value="mirror">Mirror</option><option value="raidz1">RAIDZ1</option><option value="raidz2">RAIDZ2</option><option value="single">Single disk</option></select></label><div id="os-blank-disks"></div><label>Exported pool<select id="os-import-pool"></select></label>${field('dataset','New dataset','plainnvr')}${field('pool-confirmation','Type CREATE poolname or IMPORT poolname')}</div>${field('recording-directory','New, empty recording directory','recordings')}</div><p class="os-warning">Changing destinations briefly stops recording. Existing recordings stay on their old destination and become visible again when you switch back. Files are not migrated automatically.</p><button>Use recording destination</button></form>`) +
      pane('updates', 'OS updates', '') +
      pane('tools', 'Files and terminal', `<p>Browser tools work from this monitor or another computer after unlocking appliance controls.</p><a class="os-link" href="/appliance-files.html" target="_blank" rel="noopener">Open file manager</a><a class="os-link" href="/appliance-terminal.html" target="_blank" rel="noopener">Open terminal</a><div id="os-local-tools" hidden><h3>Desktop tools on this monitor</h3><p>Closing the tool returns to PlainNVR.</p><button data-local-tool="files">Debian file manager</button> <button data-local-tool="terminal">Debian terminal</button></div>`) +
      pane('logs', 'Service logs', `<label>Service<select id="os-log-unit">${['plainnvr.service','plainnvr-control.service','systemd-networkd.service','ssh.service','plainnvr-boot-mirror.service','plainnvr-update.service','plainnvr-ab-health.service','rauc.service'].map(name => `<option>${name}</option>`).join('')}</select></label><button id="os-logs-refresh">Load recent logs</button><pre id="os-log-text"></pre>`);
    document.querySelector('[data-page="settings"]').append(host);
    host.querySelectorAll('[data-os-tab]').forEach(button => button.onclick = () => {
      host.querySelectorAll('[data-os-tab]').forEach(item => item.setAttribute('aria-selected', String(item === button)));
      host.querySelectorAll('.os-pane').forEach(item => item.hidden = item.id !== 'os-' + button.dataset.osTab);
    });
    el('system').hidden = false;
    el('hostname-form').onsubmit = e => { e.preventDefault(); action(() => api.call('hostname-save', {hostname: el('hostname').value})); };
    el('clock-form').onsubmit = e => { e.preventDefault(); action(() => api.call('clock-save', {timezone: el('timezone').value, ntp: el('ntp').checked})); };
    for (const name of ['reboot','poweroff']) el(name).onclick = () => {
      const confirmation = prompt(`Type ${name.toUpperCase()} to confirm. Recording will stop.`);
      if (confirmation) action(() => api.call('power', {action: name, confirmation}));
    };
    el('network-mode').onchange = () => el('static').hidden = el('network-mode').value !== 'static';
    el('network-form').onsubmit = e => { e.preventDefault(); action(async () => {
      const result = await api.call('network-apply', {interface: el('interface').value, mode: el('network-mode').value, address: el('address').value, gateway: el('gateway').value, dns: el('dns').value});
      system.network_pending = result.pending; pending();
      return {message: result.network.mode === 'static' ? `Reconnect at http://${result.network.address.split('/')[0]}:8787/ and confirm the network change.` : 'Reconnect using the address on the appliance and confirm the network change.'};
    }); };
    el('network-confirm').onclick = () => action(async () => { await api.call('network-confirm', {id: system.network_pending.id}); system.network_pending = {}; pending(); });
    el('network-revert').onclick = () => action(() => api.call('network-revert'));
    el('key-file').onchange = async () => { const file = el('key-file').files[0]; if (file && file.size <= 16384) el('key-public').value = await file.text(); else notice('Choose a public key file under 16 KiB.', true); };
    el('key-add').onclick = () => { keys.push({label: el('key-label').value, public_key: el('key-public').value, enabled: true}); renderKeys(); el('key-public').value = ''; el('key-label').value = ''; };
    el('ssh-save').onclick = () => action(async () => { await api.call('ssh-save', {enabled: el('ssh-enabled').checked, keys}); const next = await api.status(); keys = next.ssh.keys; renderKeys(); });
    el('storage-refresh').onclick = () => action(loadStorage);
    el('storage-mode').onchange = storageFields; el('target').onchange = storageFields;
    el('format').onclick = () => { const disk = inventory.disks?.find(d => d.id === el('format-disk').value); if (!disk) return notice('Refresh and choose a blank disk.', true); const confirmation = prompt(`This creates ext4 on ${disk.device}. Type FORMAT ${disk.device} to confirm.`); if (confirmation) action(async () => { await api.call('disk-format', {disk: disk.id, confirmation}); await loadStorage(); }); };
    for (const stop of [false,true]) el(stop ? 'scrub-stop' : 'scrub').onclick = () => action(() => api.call('pool-scrub', {pool: el('scrub-pool').value, stop}));
    el('storage-form').onsubmit = e => { e.preventDefault(); const confirmation = prompt('Type CHANGE RECORDING STORAGE to confirm. Existing recordings will remain on their previous destination.'); if (!confirmation) return; action(async () => { await api.call('storage-switch', {confirmation, label: el('storage-label').value, target_id: el('target').value, selection: storageSelection()}); el('smb-password').value = ''; return {message: 'Preparing storage. Progress will appear here.'}; }); };
    el('gparted').onclick = () => action(() => api.call('local-tool', {tool: 'gparted'}));
    host.querySelectorAll('[data-local-tool]').forEach(button => button.onclick = () => action(() => api.call('local-tool', {tool: button.dataset.localTool})));
    el('logs-refresh').onclick = () => action(async () => { el('log-text').textContent = (await api.call('logs', {unit: el('log-unit').value})).text; });
    window.PlainOSUpdates.mount(el('updates'), notice);
    storageFields();
  }
  function renderKeys() {
    el('keys').replaceChildren();
    keys.forEach((key, index) => {
      const row = api.text('div', '', 'os-key'), label = api.text('label', ''), checkbox = document.createElement('input'); checkbox.type = 'checkbox'; checkbox.checked = key.enabled;
      checkbox.onchange = () => key.enabled = checkbox.checked; label.append(checkbox, document.createTextNode(key.label || 'Unnamed key'));
      const remove = api.text('button','Remove'); remove.onclick = () => { keys.splice(index,1); renderKeys(); };
      row.append(label, api.text('code', key.fingerprint || key.public_key.slice(0,60)), document.createTextNode(' '), remove); el('keys').append(row);
    });
  }
  function pending() {
    const change = system.network_pending || {}; el('network-pending').hidden = !change.id;
    if (change.id) el('network-deadline').textContent = `Confirm connectivity before ${new Date(change.deadline * 1000).toLocaleTimeString()}; otherwise this change rolls back.`;
  }
  function showSystem() {
    el('summary').textContent = `${system.hostname} · ${system.kernel}\nUptime: ${(system.uptime_seconds / 3600).toFixed(1)} hours\nLoad: ${system.load.join(' / ')}\n${system.memory.join('\n')}\n\nBoot RAID\n${system.raid}`;
    el('hostname').value = system.hostname; el('timezone').value = system.timezone; el('ntp').checked = system.ntp;
    el('addresses').textContent = system.interfaces.map(i => `${i.ifname} (${i.operstate})\n` + i.addr_info.map(a => `  ${a.local}/${a.prefixlen}`).join('\n')).join('\n\n');
    for (const item of system.interfaces) api.option(el('interface'), item.ifname, item.ifname);
    if (system.network.interface) el('interface').value = system.network.interface;
    el('network-mode').value = system.network.mode; for (const name of ['address','gateway','dns']) el(name).value = system.network[name] || '';
    el('network-mode').onchange(); el('ssh-enabled').checked = system.ssh.enabled; keys = system.ssh.keys; renderKeys();
    el('local-tools').hidden = !system.local; el('gparted').hidden = !system.local; pending();
  }
  function storageFields() {
    const mode = el('storage-mode').value; el('new-target').hidden = !!el('target').value;
    el('filesystem-fields').hidden = mode !== 'filesystem'; el('smb-fields').hidden = mode !== 'smb'; el('zfs-fields').hidden = !mode.startsWith('zfs-');
    for (const id of ['pool','layout','blank-disks']) el(id).closest('label,div').hidden = mode === 'zfs-import';
    el('import-pool').parentElement.hidden = mode !== 'zfs-import';
  }
  function storageSelection() {
    const selection = {mode: el('storage-mode').value, recording_directory: el('recording-directory').value,
      uuid: el('filesystem').value, pool: el('pool').value, layout: el('layout').value,
      disks: [...el('blank-disks').querySelectorAll('input:checked')].map(i => i.value), pool_id: el('import-pool').value,
      dataset: el('dataset').value, confirmation: el('pool-confirmation').value, smb_acknowledged: el('smb-ack').checked};
    for (const name of ['host','share','username','password','domain']) selection['smb_' + name] = el('smb-' + name).value;
    return selection;
  }
  async function loadStorage() {
    inventory = await api.call('storage-list'); el('devices').replaceChildren();
    function diskRows(nodes, indent = '') { for (const disk of nodes) { const row = document.createElement('tr'); for (const value of [indent + disk.name, fmt(disk.size), [disk.fstype, ...(disk.mountpoints || [])].filter(Boolean).join(' · ')]) row.append(api.text('td',value)); el('devices').append(row); diskRows(disk.children || [], indent + '↳ '); } }
    diskRows(inventory.devices); el('pools').textContent = inventory.zpool_status + '\n' + inventory.zfs_datasets;
    for (const id of ['format-disk','filesystem','import-pool','target']) el(id).replaceChildren();
    api.option(el('target'),'','Add a destination'); for (const target of inventory.targets) api.option(el('target'),target.id,`${target.label} · ${target.path}`);
    el('blank-disks').replaceChildren(); for (const disk of inventory.disks) { api.option(el('format-disk'),disk.id,`${disk.device} · ${fmt(disk.bytes)} · ${disk.serial || disk.model || ''}`); const label = api.text('label',''), box = document.createElement('input'); box.type = 'checkbox'; box.value = disk.id; label.append(box,document.createTextNode(`${disk.device} · ${fmt(disk.bytes)}`)); el('blank-disks').append(label); }
    for (const fs of inventory.filesystems) api.option(el('filesystem'),fs.uuid,`${fs.device} · ${fs.filesystem} · ${fmt(fs.bytes)}`);
    for (const pool of inventory.pools) api.option(el('import-pool'),pool.id,pool.name);
    storageFields(); return {message: 'Storage refreshed.'};
  }
  api.status().then(result => {
    if (!result.available) return; system = result; render(); showSystem(); window.PlainOSUpdates.show(system.updates);
    setInterval(async () => {
      if (document.querySelector('[data-page="settings"]').hidden) return;
      try { const next = await api.status(); window.PlainOSUpdates.show(next.updates); system.network_pending = next.network_pending; pending(); if (next.job?.message && next.job.updated !== system.job?.updated) { notice(next.job.message, next.job.state === 'failed'); system.job = next.job; } }
      catch (_) { /* A network/storage restart can briefly interrupt polling. */ }
    }, 10000);
  }).catch(() => {});
})();
