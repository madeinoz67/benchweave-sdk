/* BenchWeave analyse view (I4a): drag-brush region selection.
 *
 * Page-scoped and closed like the wrapper it rides on: bw-plot.js stores
 * the uPlot instance on each plot host element as _bwPlot (its own
 * convention), so this script converts the drag extent through uPlot's
 * public posToVal, fills the numeric window inputs, and re-submits the
 * analysis form (htmx posts the partial; without script the form GETs —
 * the no-script path stays whole). No plugin knowledge; no requests
 * beyond the host's own routes. */
(function () {
  "use strict";

  function micro(value) {
    return String(Math.round(value * 1e6) / 1e6);
  }

  function arm(host) {
    var plot = host._bwPlot;
    var form = document.getElementById("analyse-form");
    if (!plot || !form || !plot.over) return;
    plot.over.addEventListener("mouseup", function () {
      var sel = plot.sel;
      if (!sel || sel.x0 == null || sel.x1 == null) return;
      var left = Math.min(sel.x0, sel.x1);
      var right = Math.max(sel.x0, sel.x1);
      if (right - left < 2) return; /* a click, not a brush */
      var lo = plot.posToVal(left, 0);
      var hi = plot.posToVal(right, 0);
      if (!(hi > lo)) return;
      if (form.elements["lo"]) form.elements["lo"].value = micro(lo);
      if (form.elements["hi"]) form.elements["hi"].value = micro(hi);
      try {
        plot.setSelect(null, false);
      } catch (error) {
        /* a uPlot build without setSelect keeps the selection visible;
           the values are already set and the form still re-analyses. */
      }
      if (typeof form.requestSubmit === "function") {
        form.requestSubmit();
      } else {
        form.submit();
      }
    });
  }

  function armAll(root) {
    (root || document).querySelectorAll("[data-bw-plot-host]").forEach(function (host) {
      if (host.dataset.bwBrushArmed === "true") return;
      host.dataset.bwBrushArmed = "true";
      arm(host);
    });
  }

  function boot() {
    armAll(document);
    document.body.addEventListener("htmx:afterSwap", function (event) {
      armAll(event.target);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
