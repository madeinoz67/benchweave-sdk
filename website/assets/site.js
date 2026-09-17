/* BenchWeave SDK public site — panel navigation, install tabs, theme toggle.
   Plain JS, no build chain. Hash deep links (#docs, #cli, #gateway) keep the
   panels reachable from outside the page; #install scrolls to the install
   block on the home panel. */

var THEME_KEY = 'bw-site-theme';
var PANEL_INDEX = { home: 0, docs: 1, cli: 2, gateway: 3 };

function showPanel(name, btn) {
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.getElementById('panel-' + name).classList.add('active');
  document.querySelectorAll('nav.panels button').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  try { history.replaceState(null, '', '#' + name); } catch (e) { /* no history API */ }
  window.scrollTo({ top: 0, behavior: 'auto' });
}

function scrollToInstall() {
  if (!document.getElementById('panel-home').classList.contains('active')) {
    showPanel('home', document.querySelectorAll('nav.panels button')[PANEL_INDEX.home]);
  }
  var el = document.getElementById('install');
  if (el) el.scrollIntoView({ block: 'start' });
  try { history.replaceState(null, '', '#install'); } catch (e) {}
}

function showInstall(name, btn) {
  ['pip', 'uv', 'brew', 'git'].forEach(k => {
    var el = document.getElementById('install-' + k);
    if (el) el.style.display = (k === name) ? 'block' : 'none';
  });
  document.querySelectorAll('.install-tabs button').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
}

function applyStoredTheme() {
  try {
    const saved = localStorage.getItem(THEME_KEY);
    if (saved === 'light' || saved === 'dark') document.documentElement.setAttribute('data-theme', saved);
  } catch (e) {}
}

function currentTheme() {
  const set = document.documentElement.getAttribute('data-theme');
  if (set === 'light' || set === 'dark') return set;
  return (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) ? 'dark' : 'light';
}

function toggleTheme() {
  const next = currentTheme() === 'light' ? 'dark' : 'light';
  document.documentElement.setAttribute('data-theme', next);
  try { localStorage.setItem(THEME_KEY, next); } catch (e) {}
}

function gotoVersion(select) {
  if (select.value) window.location.href = select.value;
}

applyStoredTheme();

/* Header star CTA: live count from the GitHub API, best-effort. The ask
   stands without the number when the fetch fails or the count is zero. */
(function starCount() {
  const el = document.getElementById('star-count');
  if (!el) return;
  fetch('https://api.github.com/repos/madeinoz67/benchweave-sdk', { headers: { Accept: 'application/vnd.github+json' } })
    .then(r => (r.ok ? r.json() : null))
    .then(d => {
      const n = d && typeof d.stargazers_count === 'number' ? d.stargazers_count : 0;
      if (n > 0) {
        el.textContent = n >= 1000 ? (n / 1000).toFixed(1).replace(/\.0$/, '') + 'k' : String(n);
        el.hidden = false;
      }
    })
    .catch(() => { /* offline or rate-limited: keep the ask, drop the number */ });
})();

/* Open the panel named by the URL hash (e.g. /#cli), matching nav buttons. */
(function openFromHash() {
  const name = (location.hash || '').replace('#', '');
  if (name in PANEL_INDEX) {
    showPanel(name, document.querySelectorAll('nav.panels button')[PANEL_INDEX[name]]);
  } else if (name === 'install') {
    scrollToInstall();
  }
})();

/* Reduced motion: the hero figure degrades to its finished state (solid
   device, verified badge) rather than freezing at t=0 on the wireframe. */
if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
  document.querySelectorAll('svg.schematic').forEach(function (svg) {
    if (typeof svg.setCurrentTime === 'function') svg.setCurrentTime(5.2);
    if (typeof svg.pauseAnimations === 'function') svg.pauseAnimations();
  });
}
