/* Release notes are text, never HTML supplied by a release publisher. */
window.PlainOSUpdates = (() => {
  let panel, report, state;
  const api = window.PlainOS;
  const el = name => panel.querySelector('[data-update="' + name + '"]');
  async function action(name, payload = {}) {
    try { report((await api.call('update-' + name, payload)).message); show((await api.status()).updates); }
    catch (error) { report(error.message, true); }
  }
  function mount(target, notice) {
    panel = target; report = notice;
    panel.innerHTML = '<h3>OS updates</h3><p data-update="summary"></p><p data-update="result" role="status"></p><div data-update="controls"><label>Release channel<select data-update="channel"><option value="stable">Stable</option><option value="preview">Preview</option></select></label><p class="os-note">Preview releases are for testing. Updates are signed and hosted in the PlainNVR GitHub repository.</p><div class="os-actions"><button data-update="check">Check for updates</button><button data-update="download">Download update</button><button data-update="install">Install downloaded update</button></div><p data-update="progress" role="status"></p><progress data-update="meter" max="100" hidden></progress><h4 data-update="available"></h4><pre data-update="notes"></pre><p data-update="layout"></p><p class="os-note">Installing writes the inactive 32 GB system slot. Recordings and appliance settings stay on the shared data volume. Restart when ready; recording pauses during restart. A failed trial returns to the previous system on reboot.</p><div class="os-actions"><button data-update="reboot">Restart to finish update</button><button data-update="rollback">Use previous system</button></div></div>';
    el('channel').onchange = () => action('channel', {channel: el('channel').value});
    el('check').onclick = () => action('check');
    el('download').onclick = () => action('download', {version: state.release?.version});
    el('install').onclick = () => {
      const confirmation = prompt(`Type INSTALL ${state.downloaded} to write the inactive system slot. You can restart after installation finishes.`);
      if (confirmation) action('install', {confirmation});
    };
    el('rollback').onclick = () => {
      const confirmation = prompt('Type ROLLBACK to prepare the previous system. Recordings remain on shared storage. Restart when ready.');
      if (confirmation) action('rollback', {confirmation});
    };
    el('reboot').onclick = async () => {
      const confirmation = prompt('Type REBOOT to restart and try the prepared system. Recording will pause.');
      if (!confirmation) return;
      try { await api.call('power', {action: 'reboot', confirmation}); report('Restarting. Reconnect to this address shortly.'); }
      catch (error) { report(error.message, true); }
    };
  }
  function show(value) {
    if (!panel || !value) return;
    state = value;
    el('controls').hidden = !state.supported;
    el('summary').textContent = state.supported ? `PlainNVR OS ${state.version} · running system ${state.slot} · ${state.repository}` : state.message;
    if (!state.supported) return;
    el('result').textContent = state.last_result?.message || '';
    el('channel').value = state.channel; el('channel').disabled = state.locked;
    const job = state.job || {};
    el('progress').textContent = job.message || 'Check for a signed OS release when you are ready.';
    el('progress').className = job.state === 'failed' ? 'os-error' : 'os-status';
    el('meter').hidden = !Number.isFinite(job.percent); el('meter').value = job.percent || 0;
    el('available').textContent = state.release ? `Available: ${state.release.version}${state.release.prerelease ? ' (Preview)' : ''} · ${(state.release.size / 1e9).toFixed(2)} GB` : '';
    el('notes').textContent = state.release?.notes || '';
    el('check').disabled = state.locked;
    el('download').disabled = state.locked || !state.release || state.downloaded === state.release.version;
    el('install').disabled = state.locked || !state.downloaded;
    el('install').textContent = state.downloaded ? `Install OS ${state.downloaded}` : 'Install downloaded update';
    const other = state.slot === 'A' ? 'B' : 'A';
    el('layout').textContent = ['A', 'B'].map(slot => `System ${slot}: ${state.slots[slot]?.version || 'empty'}${slot === state.slot ? ' (running)' : ''}`).join(' · ');
    el('rollback').disabled = state.locked || !state.slots[other]?.healthy;
    el('reboot').hidden = state.pending?.phase !== 'ready';
  }
  return {mount, show};
})();
