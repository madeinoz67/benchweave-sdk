/* BenchWeave public site — panel navigation, install tabs, theme toggle.
   Structure per the public-site mockup (docs/internal/public-site-mockup.html):
   plain JS, no build chain. Adds hash deep links (#standards, #guides, #sdk)
   so panels are reachable from outside the page. */

var THEME_KEY = 'bw-site-theme';

function showPanel(name, btn) {
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.getElementById('panel-' + name).classList.add('active');
  document.querySelectorAll('nav.panels button').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  try { history.replaceState(null, '', '#' + name); } catch (e) { /* no history API */ }
  window.scrollTo({ top: 0, behavior: 'auto' });
}

function showInstall(name, btn) {
  ['pip','uv','brew'].forEach(k => { document.getElementById('install-'+k).style.display = (k===name) ? 'block' : 'none'; });
  document.querySelectorAll('.install-tabs button').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
}

function applyStoredTheme() {
  try {
    const saved = localStorage.getItem(THEME_KEY);
    if (saved === 'light' || saved === 'dark') document.documentElement.setAttribute('data-theme', saved);
  } catch (e) {}
}

function toggleTheme() {
  const isLight = document.documentElement.getAttribute('data-theme') === 'light';
  const next = isLight ? 'dark' : 'light';
  document.documentElement.setAttribute('data-theme', next);
  try { localStorage.setItem(THEME_KEY, next); } catch (e) {}
}

function gotoVersion(select) {
  if (select.value) window.location.href = select.value;
}

applyStoredTheme();

/* Open the panel named by the URL hash (e.g. /#sdk), matching nav buttons. */
(function openPanelFromHash() {
  const PANEL_INDEX = { home: 0, standards: 1, guides: 2, sdk: 3 };
  const name = (location.hash || '').replace('#', '');
  if (name in PANEL_INDEX) {
    const btn = document.querySelectorAll('nav.panels button')[PANEL_INDEX[name]];
    showPanel(name, btn);
  }
})();

if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
  document.querySelectorAll('svg.schematic').forEach(function (svg) {
    if (typeof svg.pauseAnimations === 'function') svg.pauseAnimations();
  });
}
