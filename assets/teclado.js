// Atajos de teclado de TRPD_APP:
//   ← / →  segmento anterior / siguiente
//   Esc    cierra el explorador de carpetas
// No actúan mientras se escribe en un campo de texto o número.
(function () {
  function escribiendo(el) {
    if (!el) return false;
    var tag = (el.tagName || "").toLowerCase();
    return tag === "input" || tag === "textarea" || tag === "select" || el.isContentEditable;
  }
  function pulsar(id) {
    var b = document.getElementById(id);
    if (b && !b.disabled && b.offsetParent !== null) b.click();
  }
  document.addEventListener("keydown", function (ev) {
    if (ev.altKey || ev.ctrlKey || ev.metaKey || escribiendo(ev.target)) return;
    if (ev.key === "ArrowLeft") { pulsar("segmento_prev"); ev.preventDefault(); }
    else if (ev.key === "ArrowRight") { pulsar("segmento_next"); ev.preventDefault(); }
    else if (ev.key === "Escape") { pulsar("explorador_cancelar"); }
  });
})();
