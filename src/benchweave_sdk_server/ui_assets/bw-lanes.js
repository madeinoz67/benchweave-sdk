/* The viewport refusal channel (issue #449 fold F2): htmx's default
 * response handling swaps NOTHING on an error status, so a stale
 * server-minted window URL would silently no-op — the operator sees a dead
 * button. The document-level listener renders the refusal into the viewport
 * region the click came from; a viewport swap carries fresh controls, and a
 * poll (outside the lanes region) can never wipe the notice mid-flight. */
document.addEventListener("htmx:responseError", function (evt) {
  "use strict";
  var elt = evt.detail && evt.detail.elt;
  if (!elt || !elt.closest) {
    return;
  }
  var viewport = elt.closest(".bw-lanes-viewport");
  if (!viewport) {
    return;
  }
  var status = evt.detail.xhr ? evt.detail.xhr.status : 0;
  var notice = viewport.querySelector(".bw-lanes-viewport-error");
  if (!notice) {
    notice = document.createElement("p");
    notice.className = "bw-lanes-viewport-error";
    notice.setAttribute("role", "status");
    viewport.appendChild(notice);
  }
  notice.textContent =
    "Viewport refused (HTTP " + status + "): the capture window moved — " +
    "press Full to reset the view.";
});
