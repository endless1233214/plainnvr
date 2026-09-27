/* Shared client for appliance pages; grants stay in memory, never localStorage. */
window.PlainOS = (() => {
  let token = '', expiry = 0;
  async function send(body) {
    const response = await fetch('/api/appliance', body === undefined ? {} : {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
    });
    if (response.status === 401) { location.href = '/login.html'; throw Error('Sign in again.'); }
    const value = await response.json();
    if (!response.ok || value.error) throw Error(value.error || 'Appliance request failed.');
    return value;
  }
  async function unlock() {
    const password = await new Promise((resolve, reject) => {
      const dialog = document.createElement('dialog');
      dialog.className = 'os-unlock';
      dialog.innerHTML = '<form><h2>Unlock appliance controls</h2><p>These controls administer the operating system. Re-enter your PlainNVR password. Access expires after 10 minutes.</p><label>Administrator password<input type="password" autocomplete="current-password" required></label><p class="os-error" role="alert"></p><div class="os-actions"><button type="button">Cancel</button><button type="submit" class="primary-button">Unlock</button></div></form>';
      document.body.append(dialog);
      const close = () => { dialog.remove(); reject(Error('Unlock cancelled.')); };
      dialog.querySelector('button[type=button]').onclick = close;
      dialog.addEventListener('cancel', event => { event.preventDefault(); close(); });
      dialog.querySelector('form').onsubmit = event => {
        event.preventDefault(); const value = dialog.querySelector('input').value;
        dialog.querySelector('input').value = ''; dialog.remove(); resolve(value);
      };
      dialog.showModal(); dialog.querySelector('input').focus();
    });
    const result = await send({operation: 'unlock', password});
    token = result.token; expiry = Date.now() + result.expires_in * 1000;
  }
  async function call(operation, data = {}) {
    if (!token || Date.now() >= expiry) await unlock();
    try { return await send({...data, operation, token}); }
    catch (error) { if (error.message.startsWith('Unlock appliance')) { token = ''; expiry = 0; } throw error; }
  }
  function text(tag, value, className) {
    const element = document.createElement(tag); element.textContent = value;
    if (className) element.className = className;
    return element;
  }
  function option(select, value, label) {
    const element = text('option', label); element.value = value; select.append(element);
  }
  return {call, status: () => send(), unlock, text, option};
})();
