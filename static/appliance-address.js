/* The attached monitor always shows the current LAN address, including at login. */
(() => {
  let banner;
  async function refresh() {
    try {
      const result = await (await fetch('/api/appliance/address')).json();
      if (!result.available) return;
      if (!banner) {
        banner = document.createElement('aside');
        banner.setAttribute('aria-label', 'Appliance network address');
        banner.style.cssText = 'padding:10px 20px;background:#153c3a;color:#fff;font:14px system-ui;overflow-wrap:anywhere;line-height:1.7';
        const target = document.querySelector('.app-main') || document.body;
        if (target === document.body) banner.style.cssText += ';position:fixed;top:0;left:0;right:0;z-index:20';
        target.prepend(banner);
      }
      banner.replaceChildren(document.createTextNode('PlainNVR OS · Open from another computer: '));
      for (const url of result.urls) {
        const link = document.createElement('a'); link.href = url; link.textContent = url;
        link.style.color = '#9ee9df'; banner.append(link, document.createTextNode('  '));
      }
      if (!result.urls.length) banner.append(document.createTextNode('No network address — check the Ethernet connection.'));
    } catch (_) { /* The server can be restarting after a settings change. */ }
  }
  refresh(); setInterval(refresh, 15000);
})();
