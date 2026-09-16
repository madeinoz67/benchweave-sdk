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
