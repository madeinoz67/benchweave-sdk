// The host's advisory hydrator (I2c): one EventSource over /events, the
// two reload advisory regions. First-party on purpose — the vendored
// htmx-1 SSE extension is incompatible with htmx 2 (api.selectAndSwap
// was removed), so the advisory rides a native EventSource instead; the
// advisory TEXT comes from the event's own data (web.py is its single
// source), this script only maps event names to regions.
(function () {
  "use strict";
  function ready(fn) {
    if (document.readyState !== "loading") {
      fn();
    } else {
      document.addEventListener("DOMContentLoaded", fn);
    }
  }
  ready(function () {
    var source;
    try {
      source = new EventSource("/events");
    } catch (err) {
      return;
    }
    var REGIONS = {
      plugin_reloaded: "reload-advisory",
      reload_confirmation_required: "reload-confirm-advisory",
    };
    Object.keys(REGIONS).forEach(function (kind) {
      source.addEventListener(kind, function (event) {
        var region = document.getElementById(REGIONS[kind]);
        if (region) {
          region.textContent = event.data || "";
        }
      });
    });
  });
})();
