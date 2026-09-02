// Two independent capture paths:
//  A) messages relayed from the MAIN-world hook (has response bodies)
//  B) chrome.webRequest observation (network level: also sees Worker requests)
const state = { urls: new Set(), playlists: [], net: [] };

const persist = () =>
  chrome.storage.local.set({
    urls: [...state.urls],
    playlists: state.playlists,
    net: state.net,
  });

chrome.runtime.onMessage.addListener((msg) => {
  if (!msg) return;
  if (msg.kind === "url") state.urls.add(msg.payload.url);
  if (msg.kind === "playlist") state.playlists.push(msg.payload);
  if (msg.kind === "dump") {
    const blobless = JSON.stringify(msg.payload, null, 2);
    chrome.downloads.download({
      url: "data:application/json;base64," + btoa(unescape(encodeURIComponent(blobless))),
      filename: "tldv-capture.json",
    });
  }
  persist();
});

chrome.webRequest.onBeforeRequest.addListener(
  (d) => {
    if (!/media-files\.tldv\.io|\.m3u8|\.ts(\?|$)|gaia\.tldv\.io/i.test(d.url)) return;
    state.net.push({ url: d.url, type: d.type, tabId: d.tabId, t: d.timeStamp });
    state.urls.add(d.url);
    persist();
  },
  { urls: ["https://*.tldv.io/*", "https://media-files.tldv.io/*"] }
);
