// MAIN world, document_start. Runs before the page's first inline <script>.
// No chrome.* here (MAIN world has none) -- everything leaves via window.postMessage.
(() => {
  if (window.__tldvHooked) return;
  window.__tldvHooked = true;

  const store = { urls: [], playlists: [], mse: [] };
  window.__tldv = store;

  const MEDIA = /\.m3u8|\.ts(\?|$)|media-files\.tldv\.io|mpegurl/i;

  const send = (kind, payload) => {
    try {
      window.postMessage({ __tldv: true, kind, payload }, location.origin);
    } catch (_) {}
  };

  const note = (url, via) => {
    const u = String(url);
    store.urls.push({ url: u, via, t: Date.now() });
    if (MEDIA.test(u)) send("url", { url: u, via });
  };

  const keepBody = (url, text) => {
    const u = String(url);
    if (!/\.m3u8|mpegurl|#EXTM3U|TLDVCONF/i.test(u + text.slice(0, 200))) return;
    store.playlists.push({ url: u, text });
    send("playlist", { url: u, text });
  };

  // ---- fetch ----
  const origFetch = window.fetch;
  window.fetch = function (input, init) {
    const url = (input && input.url) || String(input);
    note(url, "fetch");
    const p = origFetch.apply(this, arguments);
    return p.then((res) => {
      if (/\.m3u8|mpegurl|playlist/i.test(url)) {
        res.clone().text().then((t) => keepBody(url, t)).catch(() => {});
      }
      return res;
    });
  };

  // ---- XHR ----
  const xopen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (m, u) {
    this.__tldvUrl = String(u);
    note(u, "xhr");
    return xopen.apply(this, arguments);
  };
  const xsend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.send = function () {
    this.addEventListener("load", () => {
      try {
        if (this.responseType === "" || this.responseType === "text") {
          keepBody(this.__tldvUrl, this.responseText || "");
        }
      } catch (_) {}
    });
    return xsend.apply(this, arguments);
  };

  // ---- MSE (proves what actually reached the decoder) ----
  if (window.MediaSource) {
    const addSB = MediaSource.prototype.addSourceBuffer;
    MediaSource.prototype.addSourceBuffer = function (mime) {
      store.mse.push({ type: "addSourceBuffer", mime: String(mime), t: Date.now() });
      return addSB.apply(this, arguments);
    };
  }
  if (window.SourceBuffer) {
    const ap = SourceBuffer.prototype.appendBuffer;
    SourceBuffer.prototype.appendBuffer = function (data) {
      store.mse.push({ type: "append", bytes: (data && data.byteLength) || 0, t: Date.now() });
      return ap.apply(this, arguments);
    };
  }

  // ---- blob/data playlist handed to the player ----
  const cou = URL.createObjectURL;
  URL.createObjectURL = function (obj) {
    const u = cou.call(URL, obj);
    if (obj instanceof Blob && /mpegurl|text|octet/i.test(obj.type || "")) {
      obj.text().then((t) => keepBody(u, t)).catch(() => {});
    }
    return u;
  };

  window.__tldvDump = () => {
    send("dump", JSON.parse(JSON.stringify(store)));
    return store;
  };
})();
