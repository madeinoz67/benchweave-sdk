# Vendored upstream sources

## uplot.min.js, uplot.css

- Upstream: uPlot, https://github.com/leeoniya/uPlot (MIT; see `uplot-LICENCE`).
- Version pinned at vendoring: 1.6.32 (the byte-identical single-file IIFE
  build from the upstream `dist/`, measured 49.9 KiB by the plot-renderer
  ruling — issue #310). The FILENAME deliberately carries no version:
  the tree stays version-literal free and the inventory rows carry the
  digest; this note is the provenance record.
- Retrieved from the upstream release artifacts (jsDelivr CDN mirror of
  the npm package `uplot@1.6.32`, `dist/uPlot.iife.min.js` and
  `dist/uPlot.min.css`).
- Vendored HOST-SIDE by the #310 ruling ("host-side decimation regardless
  of renderer"; the renderer-neutral contract carries no JS). When the
  shared ui-html package ships JS assets at a release > 0.1.0, the pin-bump
  motion (drift row D-B5) decides whether these bytes move there.
