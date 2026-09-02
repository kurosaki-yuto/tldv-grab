// ISOLATED world, document_start. Bridges MAIN-world hook -> service worker.
window.addEventListener("message", (e) => {
  if (e.source !== window) return;
  const d = e.data;
  if (!d || d.__tldv !== true) return;
  try {
    chrome.runtime.sendMessage({ kind: d.kind, payload: d.payload, href: location.href });
  } catch (_) {}
});
