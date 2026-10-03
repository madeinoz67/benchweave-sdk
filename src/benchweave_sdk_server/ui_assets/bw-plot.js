/* BenchWeave standalone plot hydrator (I2a §3.3).
 *
 * Hydrates the server-composed figures from their CSP-safe
 * application/json data blocks: time-series/waveform figures draw through
 * the vendored uPlot (colors resolved from the renderer's CSS series
 * tokens); digital-lanes figures keep the server's no-data skeleton until
 * captures exist (I3) — bwHydrateLanes draws synthetic columns now so the
 * path is exercised, and will draw live columns when capture lands.
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
    var plot = new window.uPlot(
      options,
      [channel.x, channel.y],
      function (element) {
        canvas.innerHTML = "";
        canvas.appendChild(element);
      }
    );
    host.dataset.bwHydrated = "true";
    host._bwPlot = plot;
  }

  function hydrateLanes(host) {
    var canvas = host.querySelector(".bw-plot__canvas");
    if (!canvas) return;
    var block = host.querySelector("[data-bw-plot-data]");
    var payload = null;
    if (block) {
      try {
        payload = JSON.parse(block.textContent);
      } catch (error) {
        payload = null;
      }
    }
    var columns = payload && payload.lanes ? payload.lanes : [];
    bwHydrateLanes(canvas, columns);
    host.dataset.bwHydrated = "true";
  }

  function hydrateAll(root) {
    var hosts = (root || document).querySelectorAll("[data-bw-plot-host]");
    hosts.forEach(function (host) {
      if (host.dataset.bwHydrated === "true") return;
      if (host.querySelector("[data-bw-lanes]")) {
        hydrateLanes(host);
      } else {
        hydratePlot(host);
      }
    });
  }

  /* The digital-lanes hydrator (Canvas 2D): draws the edge-preserving
   * columns the §E.4.4 reduction defines — per column, the state segment,
   * with single-transition columns drawing their pre/post edge and
   * multi-transition columns their glitch mark. Exercised on synthetic
   * columns by the browser lane; live lane data arrives with capture (I3). */
  function bwHydrateLanes(canvas, columns) {
    var context = canvas.getContext("2d");
    if (!context) return;
    var width = Math.max(320, canvas.clientWidth || 600);
    var height = 160;
    canvas.width = width;
    canvas.height = height;
    context.clearRect(0, 0, width, height);
    context.strokeStyle = seriesColor("--bw-border", "#888888");
    context.strokeRect(0.5, 0.5, width - 1, height - 1);
    if (!columns.length) return;
    var columnWidth = width / columns.length;
    columns.forEach(function (column, index) {
      var x = index * columnWidth;
      if (column.glitch) {
        context.fillStyle = seriesColor("--bw-critical", "#b44646");
        context.fillRect(x + 1, height / 2 - 6, Math.max(2, columnWidth - 2), 12);
        return;
      }
      var states = column.edge
        ? [column.edge.from, column.edge.to]
        : [column.state, column.state];
      var band = (height - 8) / states.length;
      states.forEach(function (state, bandIndex) {
        context.fillStyle = seriesColor(
          state === "1" ? "--bw-series-1" : "--bw-text-muted",
          state === "1" ? "#4682b4" : "#888888"
        );
        context.fillRect(x + 1, 4 + bandIndex * band, Math.max(2, columnWidth - 2), band - 1);
      });
    });
    canvas.setAttribute("data-bw-lanes-drawn", String(columns.length));
  }

  window.bwHydratePlots = hydrateAll;
  window.bwHydrateLanes = bwHydrateLanes;

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
