/* BenchWeave analyse view (I4a + I4b.1): drag-brush region selection and
 * marker click-to-place.
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
 * Click-to-place (I4b.1 AR-8) uses the same closed surface: the click's
 * t comes from uPlot's own posToVal(left, "x") pixel->value API, and a
 * drag (mousedown more than 3px from the click) never places — the brush
 * owns drags. The selected row is the marker row whose inputs last had
 * focus; with no selection the first row with an empty t takes the
 * value. The numeric marker fields alone are the complete no-script
 * path (the record's underpowered clause).
 *
 * The filled values re-submit the analysis form (htmx posts the partial;
 * without script the form GETs — the no-script path stays whole). No
 * plugin knowledge; no requests beyond the host's own routes. */
(function () {
  "use strict";

  var selectedRow = null;

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

  function armMarkerPlacement(host) {
    var plot = host._bwPlot;
    var canvas = host.querySelector(".bw-plot__canvas");
    if (!plot || !canvas || typeof plot.posToVal !== "function") return;
    var downX = null;
    canvas.addEventListener("mousedown", function (event) {
      downX = event.offsetX;
    });
    canvas.addEventListener("click", function (event) {
      if (downX === null || Math.abs(event.offsetX - downX) > 3) {
        return; /* a drag, not a click — the brush owns it */
      }
      var target = event.target;
      if (!target) return;
      /* B-F2: event.offsetX is TARGET-relative — a click on the .u-axis
       * gutter poisons the over-div convention posToVal expects, and the
       * result was in-range garbage silently saved and exported. Place
       * only from clicks inside the over-div (or the unhydrated
       * container). */
      if (canvas.querySelector(".u-over")) {
        if (typeof target.closest !== "function") return;
        if (!target.closest(".u-over") || target.closest(".u-axis")) return;
      } else if (target !== canvas) {
        return;
      }
      var t = plot.posToVal(event.offsetX, "x");
      if (!isFinite(t)) return;
      var input = selectedMarkerInput() || firstEmptyMarkerInput();
      if (!input) return;
      input.value = micro(t);
      syncExportMarkers();
    });
  }

  /* B-F3: the visible editor and the export form must never be
   * independent copies — the export's hidden marker fields are rebuilt
   * from the live rows at every placement/edit and again at submit, so
   * click-to-place can never be silently dropped from the report. */
  function syncExportMarkers() {
    var fieldset = document.getElementById("marker-fieldset");
    var exportForm = document.getElementById("export-form");
    if (!fieldset || !exportForm) return;
    var stale = exportForm.querySelectorAll(
      "input[name='marker_label'],input[name='marker_t']," +
        "input[name='marker_note'],input[name='marker_capture']"
    );
    Array.prototype.forEach.call(stale, function (node) {
      if (node.parentNode) node.parentNode.removeChild(node);
    });
    Array.prototype.forEach.call(
      fieldset.querySelectorAll(".bw-marker-row"),
      function (row) {
        var label = row.querySelector("input[name='marker_label']");
        var t = row.querySelector(".bw-marker-t");
        var note = row.querySelector("input[name='marker_note']");
        appendHidden(exportForm, "marker_label", label ? label.value : "");
        appendHidden(exportForm, "marker_t", t ? t.value : "");
        appendHidden(exportForm, "marker_note", note ? note.value : "");
      }
    );
    appendHidden(
      exportForm,
      "marker_capture",
      fieldset.getAttribute("data-bw-marker-capture") || ""
    );
  }

  function appendHidden(form, name, value) {
    var input = document.createElement("input");
    input.type = "hidden";
    input.name = name;
    input.value = value;
    form.appendChild(input);
  }

  /* The selected marker row is the one whose inputs last had focus; with
   * no live selection, the first row with an empty t takes the click. */
  function selectedMarkerInput() {
    if (selectedRow && selectedRow.isConnected) {
      return selectedRow.querySelector(".bw-marker-t");
    }
    selectedRow = null;
    return null;
  }

  function firstEmptyMarkerInput() {
    var form = document.getElementById("analyse-form");
    if (!form) return null;
    var rows = form.querySelectorAll(".bw-marker-row");
    for (var index = 0; index < rows.length; index += 1) {
      var input = rows[index].querySelector(".bw-marker-t");
      if (input && !input.value) return input;
    }
    return null;
  }

  document.addEventListener(
    "focusin",
    function (event) {
      var target = event.target;
      if (target && target.closest) {
        var row = target.closest(".bw-marker-row");
        if (row) selectedRow = row;
      }
    },
    true
  );

  function armAll(root) {
    (root || document).querySelectorAll("[data-bw-plot-host]").forEach(function (host) {
      if (host.dataset.bwBrushArmed === "true") return;
      host.dataset.bwBrushArmed = "true";
      arm(host);
      armMarkerPlacement(host);
    });
  }

  function boot() {
    armAll(document);
    document.body.addEventListener("htmx:afterSwap", function (event) {
      armAll(event.target);
    });
    /* The export form lives in the swapped partial: delegate on
     * document so a rebuilt form still mirrors before submitting. */
    document.addEventListener(
      "submit",
      function (event) {
        if (event.target && event.target.id === "export-form") {
          syncExportMarkers();
        }
      },
      true
    );
    document.addEventListener(
      "input",
      function (event) {
        var target = event.target;
        if (target && target.closest && target.closest("#marker-fieldset")) {
          syncExportMarkers();
        }
      },
      true
    );
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
