/* BenchWeave analyse view (I4a): drag-brush region selection.
 *
 * Page-scoped and closed like the wrapper it rides on: bw-plot.js stores
 * the uPlot instance on each plot host element as _bwPlot (its own
 * convention). The brush talks ONLY to the vendored uPlot bytes' real
 * API surface (fold wave 2, B-F1 — the original handler read a
 * selection property these bytes never expose, making it dead code):
 *
 *  - the vendored defaults carry drag.setScale = true, so a finished drag
 *    ZOOMS and fires the setScale hook synchronously INSIDE uPlot's own
 *    mouseup processing (before any later listener could observe a
 *    selection rect — uPlot resets it first);
 *  - the zoomed x extent therefore IS the dragged region: the hook reads
 *    plot.scales.x.min/max directly, no coordinate arithmetic;
 *  - the hook is armed by a mousedown on the plot's canvas container, so
 *    the setScale calls that init and window-resize also fire never
 *    submit.
 *
 * The filled values re-submit the analysis form (htmx posts the partial;
 * without script the form GETs — the no-script path stays whole). No
 * plugin knowledge; no requests beyond the host's own routes. */
(function () {
  "use strict";

  function micro(value) {
    return String(Math.round(value * 1e6) / 1e6);
  }

  function arm(host) {
    var plot = host._bwPlot;
    var form = document.getElementById("analyse-form");
    var canvas = host.querySelector(".bw-plot__canvas");
    if (!plot || !form || !canvas || !plot.hooks || !plot.scales) return;
    var armed = false;
    canvas.addEventListener("mousedown", function () {
      armed = true;
    });
    canvas.addEventListener("mouseup", function () {
      armed = false;
    });
    plot.hooks.setScale = plot.hooks.setScale || [];
    plot.hooks.setScale.push(function () {
      if (!armed) return; /* init and resize fire setScale too */
      var x = plot.scales.x;
      if (!x || !(x.max > x.min)) return; /* a click, not a drag */
      if (form.elements["lo"]) form.elements["lo"].value = micro(x.min);
      if (form.elements["hi"]) form.elements["hi"].value = micro(x.max);
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
