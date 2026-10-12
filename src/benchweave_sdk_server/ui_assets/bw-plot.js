/* BenchWeave standalone plot hydrator (I2a §3.3).
 *
 * Hydrates the server-composed figures from their CSP-safe
 * application/json data blocks: time-series/waveform figures draw through
 * the vendored uPlot (colors resolved from the renderer's CSS series
 * tokens); digital-lanes figures are the package's semantic HTML
 * (issue #449 slice 1) — no canvas, no hydrator: the figure renders
 * declaratively and the poll region stops before it.
 * No plugin-supplied options flow through here: the wrapper is closed. */
(function () {
  "use strict";

  function seriesColor(token, fallback) {
    var value = getComputedStyle(document.documentElement).getPropertyValue(token);
    value = value ? value.trim() : "";
    return value || fallback;
  }

  function hydratePlot(host) {
    var canvas = host.querySelector(".bw-plot__canvas");
    var block = host.querySelector("[data-bw-plot-data]");
    if (!canvas || !block || typeof window.uPlot === "undefined") return;
    var payload;
    try {
      payload = JSON.parse(block.textContent);
    } catch (error) {
      return;
    }
    var channel = payload.channels && payload.channels[0];
    if (!channel || channel.x.length === 0) return;

    var axes = (canvas.getAttribute("data-bw-axes") || "").split(";");
    var series = [
      { label: "t (" + (payload.x_unit || "s") + ")" },
      {
        label: channel.id,
        stroke: seriesColor("--bw-series-1", "#4682b4"),
        width: 2,
        points: { show: false },
      },
    ];
    var options = {
      title: canvas.getAttribute("data-bw-plot-title") || "",
      width: Math.max(320, canvas.clientWidth || 600),
      height: 260,
      axes: axes.map(function (unit, index) {
        return index === 0
          ? {}
          : {
              label: unit || "",
              values: function (self, ticks) {
                return ticks.map(function (tick) {
                  return String(tick);
                });
              },
            };
      }),
      series: series,
      legend: { show: false },
      cursor: { drag: { x: true, y: true } },
    };
    canvas.textContent = "";
    var plot = new window.uPlot(options, [channel.x, channel.y], canvas);
    host.dataset.bwHydrated = "true";
    host._bwPlot = plot;
  }

  function hydrateAll(root) {
    var hosts = (root || document).querySelectorAll("[data-bw-plot-host]");
    hosts.forEach(function (host) {
      if (host.dataset.bwHydrated === "true") return;
      hydratePlot(host);
    });
  }

  window.bwHydratePlots = hydrateAll;

  function boot() {
    hydrateAll(document);
    document.body.addEventListener("htmx:afterSwap", function (event) {
      hydrateAll(event.target);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
