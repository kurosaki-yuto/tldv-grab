# ブラウザで開いているページの動画を検出・抽出するOSS 調査レポート

対象環境: macOS (Apple Silicon) / Chrome / yt-dlp・gh CLI 導入済み
調査日: 2026-09-02
調査本数: 約90リポジトリ（うち要件適合38本、不適合52本）

---

## 結論: まずこれを入れろ

### 1. 手軽さ重視 — xifangczy/cat-catch

Chrome ウェブストアから1クリックで入り、閲覧中のページの HLS/DASH/MP4/FLV を自動で列挙する。日本語UIが完訳（339キー）されており、star 21.7k・昨日も push・GPL-3.0 と保守も文句なし。blob:/MSE 専用サイトには「キャッシュ捕獲」でページに Proxy を仕込んで対応できる（要リロード）。拡張内に hls.js 由来の AES-128 復号と mux.js を持つのでローカル完結する。

公式ID（偽物が複数出回っているので必ずこれ）:
`https://chromewebstore.google.com/detail/cat-catch/jfedfbgedapdagkghmgibemcoggfppbb`

### 2. 万能性重視 — cat-catch + yt-dlp の併用（拡張は検出器として使う）

拡張で m3u8 URL・Referer・Cookie を拾い、実ダウンロードは既に入っている yt-dlp に渡す。認証付き配信は `yt-dlp --cookies-from-browser chrome "<m3u8>" --referer "<page>"` が最も確実に通る。実機検証では yt-dlp が Chrome のライブプロファイルから 3,364 件の Cookie 読み出しに成功しており、拡張内蔵ダウンローダより認証まわりが強い。検出役として ezwebtools/flowpick も候補だが、後述の理由でダウンロードは絶対に flowpick.net に投げないこと。

### 3. 開発者が組み込む用 — chromedp/chromedp（Go）または mitmproxy/mitmproxy（Python）

自前で「検出→yt-dlp 引き渡し」パイプラインを組むなら、CDP の型付きイベントを購読できる chromedp が最短。MV3 の制約もブラウザ拡張の権限も回避したいなら mitmproxy に addon を20〜30行書くのが最強（ただし CA をシステムに信頼させる代償は大きい）。どちらも動画検出コードは1行も含まれていないので、判定ロジックは自作になる。

---

## Chrome拡張

### 本命クラス

| リポジトリ | star | 最終push | ライセンス | 何をするか | 捕捉機構 | macOS導入 |
|---|---|---|---|---|---|---|
| [xifangczy/cat-catch](https://github.com/xifangczy/cat-catch) | 21,670 | 2026-09-01 | GPL-3.0 | 閲覧中ページのメディアを全形式で列挙・拡張内で結合保存 | webRequest.onSendHeaders/onResponseStarted + 拡張子/Content-Type テーブル照合。加えて MediaSource.addSourceBuffer / SourceBuffer.appendBuffer を MAIN world で Proxy 化して MSE を捕獲。m3u8 は hls.js 由来の AESDecryptor で AES-128 復号、mux.js で MP4 化。declarativeNetRequest で Referer 書換 | Chrome ウェブストアから1クリック（ID: jfedfbgedapdagkghmgibemcoggfppbb）。ソース導入も可、ビルド不要 |
| [chandler-stimson/live-stream-downloader](https://github.com/chandler-stimson/live-stream-downloader) | 360 | 2026-08-29 | MPL-2.0 | ページを見ているだけでバッジに検出件数が出る型。拡張内で mux まで完結 | 4系統: (1) webRequest.onHeadersReceived を3本、(2) Blob コンストラクタを Proxy 化して application/vnd.apple.mpegurl の生成を捕捉、(3) jwPlayer/videojs オブジェクト走査 + performance.getEntriesByType、(4) declarativeNetRequest でタブ単位の Referer/Origin 差し替え | `git clone` → chrome://extensions で **v3/ ディレクトリ**を「パッケージ化されていない拡張機能を読み込む」。ビルド不要 |
| [mediago-dev/mediago](https://github.com/mediago-dev/mediago) | 9,206 | 2026-08-29 | MIT | 拡張が検出→デスクトップ本体(yt-dlp + N_m3u8DL-RE)へ Cookie 込みで渡す | webRequest.onSendHeaders に `extraHeaders` 付きで登録し、Cookie ヘッダを含む requestHeaders ごと本体に転送。判定は共有の SNIFF_FILTERS（m3u8 + 直リンク拡張子 + サイト別 host パターン） | dmg (`mediago-community-setup-darwin-arm64-3.5.0.dmg`) を導入 → 設定から拡張ディレクトリを開いて unpacked 読み込み。Docker 版は arm64 対応 |
| [puemos/hls-downloader](https://github.com/puemos/hls-downloader) | 2,688 | 2026-09-01 | MIT | HLS専用。画質・音声・字幕を選んで ffmpeg.wasm で mux | webRequest.onCompleted に `urls:["*.m3u8"]`, `types:["xmlhttprequest"]`, Content-Type 検証つきで登録。以後 m3u8-parser でレンディション列挙 → fetch でセグメント取得 → Web Crypto で AES-128 復号 → OPFS 経由 ffmpeg.wasm (32MB) で MP4/MKV | `gh release download v5.5.0 -R puemos/hls-downloader -p 'extension-mv3-chrome.zip'` → 展開して unpacked 読み込み（Chrome 111+） |
| [ezwebtools/flowpick](https://github.com/ezwebtools/flowpick) | 164 | 2026-08-27 | MIT | 検出力は最高クラス。ただしダウンロード本体はOSSではない | webRequest(onBeforeRequest/onHeadersReceived/onSendHeaders) + Content-Type + URL パターン + MAIN world での XHR/fetch フックおよび MediaSource Proxy の4層。Cookie/Authorization 等を requestId 単位で退避。DRM も正規表現で検出 | ストアから1クリック（ID: mfinfkkabangbkanlfhhbokgfekjklea）。**HLS/DASH/mp4 の DL は Cookie 込みで flowpick.net に投げる実装なので、検出器としてだけ使い URL は yt-dlp に渡すこと** |
| [asdfghj1237890/WebVideo2NAS](https://github.com/asdfghj1237890/WebVideo2NAS) | 1,162 | 2026-08-25 | MIT | NAS常設でブラウザを閉じても落とし続ける構成 | inject.js/deepsearch.js を MAIN world・document_start・all_frames で注入し fetch/XHR をフック（.jpg偽装HLSやマニフェストレス DASH も検出）。content.js が `<video>` を監視。cookies 権限でドメイン Cookie を付与し declarativeNetRequest で Referer 整形して FastAPI へ POST | Docker で `docker compose up -d`（GHCR は arm64 マルチアーチ）→ 拡張 zip を unpacked 読み込み。Mac1台完結ならオーバースペック |
| [helloyanis/media-downloader-unleashed](https://github.com/helloyanis/media-downloader-unleashed) | 146 | 2026-08-10 | MIT | webRequest 一本槍で全通信を張り込み、AES-128 復号と結合まで拡張内で完結 | onBeforeRequest〜onCompleted を `<all_urls>` に張り、MIME 判定と約90種の拡張子判定の2系統（個別ON/OFF可、両方OFFで全リクエスト列挙）。Firefox 専用の filterResponseData でレスポンス本体を IndexedDB にキャッシュする経路もあり | **Chrome では v4系が動かない**。Chrome 常用なら v3.6.8 の xpi を zip 化して unpacked 読み込み（機能欠落あり）。本命は Firefox + AMO |
| [jvillegasd/media-bridge](https://github.com/jvillegasd/media-bridge) | 9 | 2026-03-07 | MIT | 検出→ffmpeg.wasm で mux まで。実装は真面目だがレビュー実績が薄い | service worker の webRequest.onCompleted（`*.m3u8`/`*.mpd`・xmlhttprequest 限定）+ content script の MutationObserver による `<video>` 走査。blob: は「video 要素をキーに捕捉済み実URLを引く」紐付け方式。FairPlay/PlayReady は検出して明示拒否 | Release の zip を展開して unpacked 読み込み。**star 9 の個人開発に `<all_urls>` を渡す構成なので専用プロファイル推奨** |

### 補助・限定用途

| リポジトリ | star | 最終push | ライセンス | 何をするか | 捕捉機構 | macOS導入 |
|---|---|---|---|---|---|---|
| [DevLARLEY/WidevineProxy2](https://github.com/DevLARLEY/WidevineProxy2) | 1,072 | 2026-08-05 | GPL-3.0 | DRM専用。マニフェスト+ヘッダ+復号鍵を集めて N_m3u8DL-RE コマンドを生成 | MAIN world で EME(requestMediaKeySystemAccess/generateRequest/update) を Proxy 化。加えて XHR/fetch をフックしてレスポンス本文から HLS/DASH/MSS を判定、webRequest.onBeforeSendHeaders で Cookie 等を紐付け | Release zip を unpacked 読み込み。**別途 .wvd (Widevine デバイス) を自力調達しないと content script が登録すらされない**。法的リスクは最大級（後述） |
| [EltonChou/TwitterMediaHarvest](https://github.com/EltonChou/TwitterMediaHarvest) | 1,152 | 2026-08-31 | MPL-2.0 | X(Twitter)専用。タイムラインの動画付き投稿にDLボタンを自動注入 | MutationObserver で `<article>` を監視し `articleHasMedia()` 判定。MAIN world で fetch をフックして x-client-transaction-id を採取、cookieStore の ct0 と併せて X 内部 GraphQL を叩き最高ビットレート MP4 を解決 | ストアから1クリック（ID: hpcgabhdlnapolkkjpejieegfpehfdok）。READMEの「第三者サービス不使用」は誇張（Cognito/Sentry へ通信あり） |
| [c-yyy/bili-mux](https://github.com/c-yyy/bili-mux) | 52 | 2026-09-01 | **なし（全権利留保）** | bilibili専用。offscreen + ffmpeg.wasm で DASH を MP4 化 | ネットワーク傍受なし。URLから BV/av を抽出し `credentials:'include'` で B站 playurl API を叩く（WBI署名は自前MD5実装）。declarativeNetRequest で Referer 注入 | `git clone --depth 1` → unpacked 読み込み（Chrome 116+）。ffmpeg 同梱で brew 不要。ライセンス不在なので流用不可 |
| [nobiyou/wx_channel](https://github.com/nobiyou/wx_channel) | 2,577 | 2026-09-01 | MIT | 微信視頻号専用。MITM + ページへのJS注入 | SunnyNet プロキシで復号したHTMLに `<head>` 直後からJSを注入。ただし注入対象は channels.weixin.qq.com の4パスと mp.weixin.qq.com のみ | **macOS実質非対応**。作者が「Macを持っていない」と明言、EnableProxyInMacOS はデッドコード、DLボタンの本命である WeChatAppEx.exe 注入は Windows 限定 |

### メンテ停止 / 非推奨

| リポジトリ | star | 最終push | ライセンス | 状態 |
|---|---|---|---|---|
| [54ac/stream-detector](https://github.com/54ac/stream-detector) | 721 | 2023-07-13 | MPL-2.0 | **メンテ停止・アーカイブ済み**。機構は優秀（webRequest + extraHeaders で Cookie を読み、yt-dlp/ffmpeg/streamlink のコマンドを `--add-header "Cookie:..."` 付きで生成）だが、作者が「Chrome版は動作保証しない」と明言。MV3 の service worker がアイドル停止後にリスナーを再登録しない構造的バグを抱える。使うなら Firefox 版 |
| [bangersys/stream-detector](https://github.com/bangersys/stream-detector) | 0 | 2026-03-15 | MPL-2.0 | 上記の Chrome MV3 対応フォーク。bun でビルドすれば動く（実機確認済み）が、star 0・作者2日間の突貫・未公開の別製品(primedl)の付属部品に改造されており、既定で存在しない ws://127.0.0.1:7421 に無限再接続する |
| [zamgi/m3u8](https://github.com/zamgi/m3u8) | 139 | 2026-08-30 | MIT | 生きているが macOS 非対応。DL実体が C#/Avalonia のネイティブホストで、README/CI とも Windows/Linux のみ。しかも `Environment.OSVersion.Platform` 判定のため macOS を Linux と誤認する |
| [Leenshady/m3u8Sniffer2](https://github.com/Leenshady/m3u8Sniffer2) | 12 | 2025-07-23 | GPL-3.0 | **メンテ停止**。検出は background.js の実質40行で教材向き。ただし `details.tabId` でなく `tabs.query({active:true})` に紐付けるバグがあり、別タブの結果が混入する |
| [cssnr/hls-video-downloader](https://github.com/cssnr/hls-video-downloader) | 18 | 2026-02-24 | GPL-3.0 | 生きているが Cookie を一切引き継がない（SW の fetch も ffmpeg も credentials/ヘッダ無し）。Apple Silicon は brew 経路のみで、公式の caveats のコマンドが引用符バグで動かない |
| [Momo707577045/media-source-extract](https://github.com/Momo707577045/media-source-extract) | 1,961 | 2025-04-22 | **なし** | **メンテ停止**（16ヶ月）。MSE抜き取りの原典として読む価値は高い（addSourceBuffer/appendBuffer/endOfStream フック）が、全サイトで1秒ごとに iframe の sandbox 属性を剥がし続ける挙動があり常用不可 |

---

## Firefox拡張

Chrome から乗り換える気があるなら選択肢が広がる領域。特に MV2 の非永続バックグラウンドページが使える点で、MV3 の service worker 停止問題を踏まない。

| リポジトリ | star | 最終push | ライセンス | 何をするか | 捕捉機構 | macOS導入 |
|---|---|---|---|---|---|---|
| [helloyanis/media-downloader-unleashed](https://github.com/helloyanis/media-downloader-unleashed) | 146 | 2026-08-10 | MIT | Firefox 版が本命。DRMなし配信サイト用の第一候補 | 前述（webRequest 全張り + filterResponseData） | `brew install --cask firefox` → AMO から追加（v4.0.10 / 日次13,262ユーザー）。YouTube は公式に非対応（yt-dlp に任せる） |
| [54ac/stream-detector](https://github.com/54ac/stream-detector) | 721 | 2023-07-13 | MPL-2.0 | **アーカイブ済みだが Firefox 版は完成度が高い**。Cookie/UA/Referer 込みで yt-dlp コマンドを生成 | 前述 | AMO の hls-stream-detector（v2.11.7 / 約14,500ユーザー） |
| [truelockmc/m3u8-detect-addon](https://github.com/truelockmc/m3u8-detect-addon) | 8 | 2025-12-16 | GPL-3.0 | 検出専用の最小実装。URLコピー止まり | webRequest.onBeforeRequest に `url.includes(".m3u8")` の部分一致だけ。全タブ共通の Set に貯める（タブ単位ではない） | AMO から追加。**Chrome 不可**（`browser.*` 名前空間・polyfill なし） |
| [mstfsgdc/Streamra](https://github.com/mstfsgdc/Streamra) | 0 | 2026-08-24 | **なし** | 見送り推奨 | onHeadersReceived で Content-Type/拡張子判定するが、**EXCLUDE_PATTERNS で .m3u8/.mpd/.ts/.m4s を明示除外している**。READMEの「HLS対応」は虚偽 | AMO にはあるが入れる価値なし。UIはトルコ語 |

参考: [downthemall/downthemall](https://github.com/downthemall/downthemall)（star 1,109 / MIT+GPL）は現在 Chrome にインストール不可（MV2、ストア掲載も消滅）。DOM走査で `<video>`/`<source>` は拾うが、`ALLOWED_SCHEMES` が http/https/ftp のみで blob: を無条件に捨てるため、MSE 再生の動画は1件も出ない。作者自身が TODO.md に「video sniffing は WebExtension では実質不可能」と書いている。

---

## セルフホストWeb

拡張ではなくサーバを立てる構成。「ブラウザを閉じても落とし続けたい」「NASに溜めたい」向け。

| リポジトリ | star | 最終push | ライセンス | 何をするか | 捕捉機構 | macOS導入 |
|---|---|---|---|---|---|---|
| [arabcoders/ytptube](https://github.com/arabcoders/ytptube) | 1,014 | 2026-08-31 | MIT | サーバ側 Chromium がページを開き直してストリームを捕まえる二段構え | `app/yt_dlp_plugins/extractor/generic_browser.py`（850行）が `playwright.chromium.connect_over_cdp()` で外部Chromiumに接続し、`page.on('request'/'response')` で media/xhr/manifest を収集。並行して `document.querySelectorAll('video'/'audio')` を evaluate。捕捉時の実リクエストヘッダを replay して yt-dlp の抽出器に渡す | macOS arm64 ネイティブビルドあり（`ytptube-macOS-arm64-*.zip`、要 `xattr -cr`）。推奨は同梱 compose（Chromium + POTプロバイダ同梱）。`.env` に `YTP_BROWSER_URL=http://chrome:9222` を設定し、プリセット `generic_browser` を選ぶ |
| [tubearchivist/tubearchivist](https://github.com/tubearchivist/tubearchivist) | 8,414 | 2026-08-28 | GPL-3.0 | YouTube専用の自宅アーカイブ基盤。公式拡張がページにDLボタンを注入 | 拡張が MutationObserver でセレクタ（`a#video-title[href]` 等）を走査し href から videoId を抽出してボタン注入。`chrome.cookies` から .youtube.com の Cookie を Netscape 形式に組んでサーバへ送る（メン限・年齢制限対応） | Docker compose の Elasticsearch イメージを `docker.elastic.co/elasticsearch/elasticsearch:8.19.0` に差し替える（既定の bbilly1/tubearchivist-es は amd64 専用）。ES+Redis+Django で4GBメモリ常駐 |

---

## CLI・エンジン

検出はしないが、拾った URL を確実に落とす後段。ここが強いから「拡張は検出だけ」という分業が成立する。

| リポジトリ | star | 最終push | ライセンス | 何をするか | 捕捉機構 | macOS導入 |
|---|---|---|---|---|---|---|
| [yt-dlp/yt-dlp](https://github.com/yt-dlp/yt-dlp) | 188,476 | 2026-08-30 | Unlicense | 事実上の標準。**唯一「渡された URL のページHTMLを解析して埋め込み動画を発見する」機能を持つ CLI** | `extractor/generic.py` が jwplayer設定・flashvars・og:video・iframe・JSON-LD を総なめし、`_parse_html5_media_entries` が `<video>/<source>` を直接パース。Cookie は `--cookies-from-browser chrome`（実機で Chrome から3,364件の読み出しに成功、macOS Keychain 経由で v10 復号） | 導入済み（v2026.07.04）。**最新は 2026.08.19 なので `brew upgrade yt-dlp` 推奨**。extractor は頻繁に壊れるので週次更新が前提 |
| [nilaoda/N_m3u8DL-RE](https://github.com/nilaoda/N_m3u8DL-RE) | 8,685 | 2026-07-03 | MIT | MPD/M3U8/ISM の後段エンジン。トラック選択・並列取得・CENC復号・mux | 検出は一切しない。URL とヘッダを手で渡す | `N_m3u8DL-RE_v0.6.0-beta_osx-arm64_*.tar.gz` を展開 → `xattr -dr com.apple.quarantine` → PATH へ。mux に `brew install ffmpeg` |
| [streamlink/streamlink](https://github.com/streamlink/streamlink) | 11,728 | 2026-09-02 | BSD-2-Clause | ライブ配信のHLS抽出精度が高い。136プラグイン | サイト別プラグインがページHTMLや内部APIを叩く。内蔵 Chromium はあるが**使い捨てプロファイル + `--disable-extensions` で起動する隔離環境**で、閲覧セッションは引き継がない（用途は Twitch/Kick の integrity token 取得） | `brew install streamlink`（arm64 bottle あり）。Cookie は `--http-cookies-file` で手渡し |
| [emarsden/dash-mpd-cli](https://github.com/emarsden/dash-mpd-cli) | 557 | 2026-08-30 | MIT | DASH専用。yt-dlp が苦手な複雑な mpd に強い | 検出なし（MPD-URL は必須引数）。ただし `--cookies-from-browser` で Chromium/Firefox/**Safari** から Cookie を読める数少ない CLI | `brew install dash-mpd-cli`（公式formula、arm64 bottle あり。ffmpeg/mkvtoolnix/bento4 も自動導入） |
| [clitic/vsd](https://github.com/clitic/vsd) | 541 | 2026-06-17 | MIT/Apache-2.0 | `vsd capture` で Chrome を起動して curl コマンドを印字、`vsd save` で落とす2段構え | chromiumoxide で Chrome を新規起動し `Network.requestWillBeSent` を購読。判定は URL 末尾の拡張子（既定 .m3u8/.mpd/字幕）+ resourceType（既定 fetch/xhr） | `brew install vsd`（homebrew-core、arm64 bottle + ffmpeg 同梱）。**ユーザーの Chrome セッションは継承しない**（新規プロファイル） |
| [Last-Order/Minyami](https://github.com/Last-Order/Minyami) | 649 | 2026-09-01 | GPL-3.0 | 日本の会員制配信（ABEMA/ニコ生/DMM/onsen.ag等）に特化。公式Chrome拡張つき | 拡張が MAIN world で `window.fetch` と `XMLHttpRequest.prototype.open` を差し替え、`.m3u8` レスポンス本文から `#EXT-X-KEY` の AES鍵まで抜く。Cookie 込みの CLI コマンド文字列を生成してクリップボードへ | `npm i -g minyami` + ストアから拡張（ID: cgejkofhdaffiifhcohjdbbheldkiaed）。SAMPLE-AES 用に `brew install bento4`。**対応は約34ドメインのハードコード許可リストのみ** |
| [ciwga/VantaEther](https://github.com/ciwga/VantaEther) | 1 | 2026-05-03 | MIT | userscript が目、ローカル Flask サーバが手 | userscript が fetch/XHR をラップし、URL 拡張子・URLパターン・**Content-Type ヘッダ**の三層で判定して 127.0.0.1:5005 へ POST | `brew install ffmpeg` + `pip install VantaEther` → `vantaether`（macOS arm64 / Python 3.14 で起動確認済み）。**Cookie を一切送らない**ので認証必須サイトは不可 |

---

## 開発者向け（CDP・プロキシ）

自前で組む場合の土台。いずれも動画検出コードはゼロなので、判定は自作になる。

| リポジトリ | star | 最終push | ライセンス | 何をするか | 捕捉機構 | macOS導入 |
|---|---|---|---|---|---|---|
| [chromedp/chromedp](https://github.com/chromedp/chromedp) | 13,269 | 2026-07-14 | MIT | Go製 CDP クライアント。20〜30行でスニファが書ける | `ListenTarget(ctx, fn)` で `network.EventResponseReceived` / `requestWillBeSent` を型付きで購読。cdproto に network/ と fetch/ の型定義あり | `brew install go`（go.mod が go 1.26 要求）→ `go get github.com/chromedp/chromedp@v0.15.1`。**Chrome 136 以降は既定プロファイルへの CDP 接続を拒否**するので、別 `--user-data-dir` が必須＝ログイン状態は引き継がれない |
| [mitmproxy/mitmproxy](https://github.com/mitmproxy/mitmproxy) | 44,888 | 2026-09-01 | MIT | MV3 も blob: も無関係に全通信を捕捉できる最強の土台 | 素の状態では動画検出コードは0行（code search で m3u8 のヒット0件、addon 38本すべて汎用機能）。`def response(self, flow)` で `flow.request.pretty_url` と Content-Type を見る addon を自作する | **`brew install --cask mitmproxy`**（formula ではなく cask。v12.2.3）。`mitmdump -s addon.py` → Chrome を専用プロファイルで `--proxy-server` 起動 → mitm.it で CA をキーチェーンに追加。**終わったら証明書を必ず削除すること** |
| [lqqyt2423/go-mitmproxy](https://github.com/lqqyt2423/go-mitmproxy) | 1,560 | 2026-09-01 | MIT | Go 製 MITM エンジン。res-downloader 等の土台 | Addon インターフェース（Requestheaders/Response/StreamResponseModifier 等）を提供するだけ。判定は自作 | Darwin_arm64 バイナリあり（`xattr -dr com.apple.quarantine` 必要）。Homebrew formula なし |
| [royswift2007/m3u8-video-sniffer](https://github.com/royswift2007/m3u8-video-sniffer) | 51 | 2026-07-31 | MIT | Playwright で**実 Chrome を永続プロファイル起動**して4経路で捕捉。設計の筋は良い | `launch_persistent_context(channel="chrome")` + `page.on("request"/"response")` + `add_init_script` 注入 + `framenavigated` の4系統。ローカル HTTP API (127.0.0.1:9527) と `m3u8dl://` で外部連携 | Windows 前提だが**実機で GUI 起動・5エンジンロード・HLS捕捉まで通ることを確認済み**。ただし `validate_engine_exe()` が拡張子 `.exe` を必須にするため、`cp $(which yt-dlp) bin/yt-dlp.exe` と実体コピーが必要（シンボリックリンク不可）。自動更新ボタンを押すと Windows PE で上書きされて壊れる |
| [ffmpegwasm/ffmpeg.wasm](https://github.com/ffmpegwasm/ffmpeg.wasm) | 17,771 | 2026-02-01 | MIT（core は GPL） | ブラウザ内で結合・変換する後段パーツ | 検出機能なし | `npm i @ffmpeg/ffmpeg`。**入力2GB上限**、core-mt は SharedArrayBuffer 必須（MV3 拡張では成立が困難）、**core が GPL なので拡張に同梱すると汚染する**。main の実装は約1年停滞 |

参考: [orestonce/m3u8d](https://github.com/orestonce/m3u8d)（star 1,006 / MIT）は関数名に `sniffM3u8()` があり進捗表示も「嗅探m3u8」と出るが、実体は「渡されたURLを自分でGETして正規表現でm3u8を探す」だけ。ブラウザは一切見ていないので誤読注意。

---

## userscript

Tampermonkey/Violentmonkey で動く。拡張ストアの審査を通らない機構を実装できる反面、全サイトに fetch/XHR フックを撒く権限を未監査コードに渡すことになる。

| リポジトリ | star | 最終push | ライセンス | 何をするか | 捕捉機構 | macOS導入 |
|---|---|---|---|---|---|---|
| [lzwme/m3u8-dl](https://github.com/lzwme/m3u8-dl) | 139 | 2026-07-20 | MIT | userscript が検出、ローカルサーバ(:6600)が落とす二段構成 | 4系統: XHR フック（setRequestHeader も退避）、fetch ラップ、`PerformanceObserver({entryTypes:['resource']})`、DOM走査。iframe 内では postMessage で親フレームに集約 | `brew install ffmpeg && npm i -g @lzwme/m3u8-dl && m3u8dl server`。Apple Silicon ネイティブ dmg (M3U8-DL-mac_arm64) もあり（未署名、要 `xattr -dr`）。**HttpOnly Cookie は原理的に読めない**ので認証壁の内側は弱い |
| [xxxily/h5player](https://github.com/xxxily/h5player) | 3,757 | 2026-08-22 | GPL-3.0 | 動画プレイヤー拡張の副機能としてMSE録り込み | `mediaSource.js` が `URL.createObjectURL` / `MediaSource.prototype.addSourceBuffer` / `SourceBuffer.appendBuffer` / `endOfStream` を Proxy 化してバッファを全保持。要素捕捉は `hackAttachShadow`（Shadow DOM の close 禁止）+ HTMLMediaElement グローバルフックで iframe/Shadow DOM 内まで届く | Tampermonkey で `https://h5player.anzz.top/h5player.user.js`。**既定でDL無効**（設定で experimental features を有効化 → 自動リロード → 再生し直し）。音声/映像が別ファイルで落ちるので ffmpeg で mux が必要 |
| [carmelobattiato/Universal-Video-Downloader](https://github.com/carmelobattiato/Universal-Video-Downloader) | 0 | 2026-08-17 | MIT | 機構は理想的だが実績ゼロ | fetch は self-healing な `guard()`（Object.defineProperty のセッターで再ラップ）、XHR は prototype 差し替え、HTMLMediaElement/HTMLSourceElement の src セッターを defineProperty で横取り、PerformanceObserver、セグメントURLからのマニフェスト逆算の5系統。GM_xmlhttpRequest で CORS/ホットリンク回避、Referer 再現、AES-128 復号、IndexedDB キャッシュで Resume、ffmpeg.wasm で remux | Tampermonkey に `universal-video-downloader.js` を貼る（READMEのリンクは404、実ファイル名が違う）。**star 0・2コミット・既定で全iframeのsandboxを剥がす**（`CFG.stripSandbox` を false にすること） |
| [Momo707577045/m3u8-downloader](https://github.com/Momo707577045/m3u8-downloader) | 7,066 | 2025-04-22 | **なし** | **メンテ停止**（16ヶ月）。検出後、作者ホストの別オリジンページにURLを渡す | `window.XMLHttpRequest` を丸ごと差し替えて `.m3u8` を検出。3秒ごとに `getElementsByTagName('video')` を走査 | Tampermonkey。**fetch は非フックなので現代のプレイヤーは取りこぼす**。別オリジンに投げるので Cookie/Referer が引き継がれず、会員限定は落とせない |
| [Senzube4n/m3u8-hls-downloader](https://github.com/Senzube4n/m3u8-hls-downloader) | 2 | 2026-03-07 | MIT | 音声(MP3)抽出が主目的、映像は副産物 | `unsafeWindow.XMLHttpRequest.prototype.open` と `unsafeWindow.fetch` をラップ + DOM走査。GM_xmlhttpRequest で Cookie を載せて CORS を跨ぐ | Tampermonkey で GitHub Pages から。**fMP4(`#EXT-X-MAP`)・BYTERANGE・別レンディション音声が全て未対応**なので TS ベースの HLS 限定。1日で書いて半年放置 |
| [marco-jardim/tm-hls-dash-downloader](https://github.com/marco-jardim/tm-hls-dash-downloader) | 1 | 2025-11-01 | MIT | HLS/DASH 検出は本物だが穴が大きい | XHR/fetch フック + `performance.getEntriesByType('resource')` の事後スキャン。iframe は postMessage 転送。DASH の SegmentTemplate/$Number$/$Time$ まで実装済み | Tampermonkey（**chrome://extensions で「ユーザースクリプトを許可」ON 必須**）。**AES-128 非対応で無警告のまま壊れたファイルが出る**。音声と映像を結合しないので無音になる |
| [EfM8caQE9F1v4pFt5x7WrjDI1N2kFqYdydVj/open-media-grabber](https://github.com/EfM8caQE9F1v4pFt5x7WrjDI1N2kFqYdydVj/open-media-grabber) | 2 | 2026-08-01 | GPL-3.0 | 設計思想は最有力だが未検証 | Tier1 は PerformanceObserver の passive 観測、Tier2 は fetch/XHR をラップしてレスポンス**本文**まで読む。MP4マージは moov の trak 接合で再エンコードなし。DRM は検出して明示拒否 | Violentmonkey で dist の user.js。**@match が SNS 11ドメインのみ**で、目玉の汎用アダプタは自分で @match を足さないと起動しない。作者が「ログイン状態の実プラットフォームで一つも検証していない」と明記 |

---

## デスクトップGUI

| リポジトリ | star | 最終push | ライセンス | 何をするか | 捕捉機構 | macOS導入 |
|---|---|---|---|---|---|---|
| [amir1376/ab-download-manager](https://github.com/amir1376/ab-download-manager) | 17,620 | 2026-09-02 | Apache-2.0 | 汎用DLマネージャだが**HLS検出とページ内ポップアップを実装済み** | 拡張が webRequest でレスポンスを傍受し Content-Type が `application/x-mpegurl` 等なら hls-parser で m3u8 を実パース、Variant から resolution/framerate を抽出して画質選択肢を作る。タブ単位で状態管理し、content script がページ内に選択ポップアップを描画。Cookie/requestHeaders 込みで本体に渡す。Kotlin 側に HLSDownloader/HLSPartDownloader 一式あり | `brew tap amir1376/tap && brew install --cask ab-download-manager` → ストアから拡張（ID: bbobopahenonfdgjgaleledndnnfhooj）。**YouTube はブラックリストでハードコード除外**。暗号化HLSの復号処理が見当たらず、ffmpeg 非依存のため出力が .ts のまま |
| [putyy/res-downloader](https://github.com/putyy/res-downloader) | 19,654 | 2026-09-01 | Apache-2.0 | システムプロキシ型MITM。Chromeで開くだけで一覧に出る | `networksetup -setwebproxy` でシステムプロキシを奪い、`security add-trusted-cert` でCAを System.keychain に信頼登録。Content-Type で video/m3u8/live を分類 | Universal Binary の dmg あり（arm64 ネイティブ確認済み、要 `xattr -d`）。**採用非推奨。後述の重大な脆弱性あり** |
| [putyy/resd-mini](https://github.com/putyy/resd-mini) | 131 | 2025-12-31 | Apache-2.0 | 上記の軽量版 | goproxy で MITM、Content-Type 分類 | arm64 dmg あり（未署名）。**HLS はダウンロード未実装**（.m3u8 テキストが保存されるだけ）。同じくシステム全体 MITM |
| [alexch33/super-video-downloader](https://github.com/alexch33/super-video-downloader) | 902 | 2026-08-19 | GPL-3.0 | 内蔵ブラウザ型。機構は本命級 | Android WebView の `shouldInterceptRequest` で全リソースを傍受し、Cookie込みの OkHttp Request に変換して Content-Type 判定。自前 HLS/DASH パーサ + yt-dlp 内蔵 | **Androidアプリ専用**。macOS ネイティブでは動かない |

### res-downloader についての警告

star 19,654 と最多で機能も本物だが、`core/app.go` の58〜109行目に**ルートCAの証明書と対応するRSA秘密鍵が平文でハードコードされており、全ユーザーが同一のCAを System.keychain に信頼登録する**。実際に抽出して検証したところ、証明書は `CN=gowas.cn`, `Basic Constraints CA:TRUE`, 有効期限 2124-01-25（100年）、公開鍵フィンガープリントは証明書側・秘密鍵側とも MD5 `aa8806a7684b2df73be076c66366bdc3` で完全一致した。つまりこの鍵を持つ者（＝GitHubを見た誰でも）が任意ドメインの正当な証明書を偽造でき、それをこのMacは全ブラウザ・全アプリで信頼する。カフェのWi-Fiや悪意あるルータと組み合わされば銀行を含む全HTTPSが中間者攻撃可能になる。理論上のリスクではなく実働する脆弱性。常用マシンには入れないこと。どうしても使うなら使い捨てVM限定で、終了後に `sudo security delete-certificate -c gowas.cn /Library/Keychains/System.keychain` まで実行する。

---

## 要件を満たさなかったもの

調査の網羅性のため、検討したが「閲覧中のページから動画を検出する」機構を持たないと確認できたものを理由付きで列挙する。

### URL貼り付け型のCLI（検出機構なし）

| リポジトリ | star | 理由 |
|---|---|---|
| [streamlink/streamlink](https://github.com/streamlink/streamlink) | 11,728 | 内蔵Chromiumは使い捨てプロファイル + `--disable-extensions` の隔離環境で、Twitch/Kick の integrity token 取得専用。閲覧中のページは見ない。CDPClient を使うプラグインは twitch.py と kick.py の2つだけ |
| [mikf/gallery-dl](https://github.com/mikf/gallery-dl) | 19,383 | generic extractor は静的HTMLの正規表現マッチのみで、対応拡張子に m3u8/mpd を含まない。HLS/DASH は yt-dlp への丸投げ。開発の主戦場は既に Codeberg に移動済み |
| [iawia002/lux](https://github.com/iawia002/lux) | 31,661 | `universal.go` はページ解析を一切せず、渡されたURLを1本のストリームとして直DLするだけ。manifest.json 0件。最新タグ v0.24.1 は2024-05で2年以上前 |
| [soimort/you-get](https://github.com/soimort/you-get) | 56,874 | **メンテ停止**（2025-04）。Chrome の Cookie 読み込みが `# TODO: Chromium Cookies` のまま未実装。Firefox の cookies.sqlite のみ対応 |
| [ytdl-org/youtube-dl](https://github.com/ytdl-org/youtube-dl) | 141,082 | `--cookies-from-browser` が存在せず（コード検索0件）、cookies.txt 手動書き出しのみ。master は9ヶ月停止、リリースは4年9ヶ月前、brew formula も削除済み |
| [ytdl-patched/ytdl-patched](https://github.com/ytdl-patched/ytdl-patched) | 623 | 直近12ヶ月のコミット207件が全てボットの自動再生成。上流マージは2023-06で停止し、実測で YouTube が「No video formats found」。yt-dlp の完全下位互換 |
| [yutto-dev/yutto](https://github.com/yutto-dev/yutto) | 2,011 | bilibili専用のURL指定型CLI。ブラウザ拡張の成果物なし（manifest.json 0件） |
| [Puyodead1/udemy-downloader](https://github.com/Puyodead1/udemy-downloader) | 2,040 | Udemy専用。コースURL指定型で内部APIを叩く。DRM講義は復号鍵をユーザーが自力調達する前提で、作者が「鍵の入手方法を聞いたらブロック」と明記 |
| [instaloader/instaloader](https://github.com/instaloader/instaloader) | 13,281 | Instagram専用。ターゲットは username/#hashtag 等の識別子7種のみでURLすら受け付けない。Cookie 流用機能はあるが検出はしない |
| [EcomGraduates/loom-downloader](https://github.com/EcomGraduates/loom-downloader) | 157 | Loom専用。共有URLを axios で GET して埋め込みJSONをパースするだけ。拡張なし |
| [tuhinpal/hls-downloader](https://github.com/tuhinpal/hls-downloader) | 183 | **メンテ停止**（16ヶ月）。m3u8を手貼りするブラウザ内結合ツール。作者自身が limitations に「Cookieはブラウザが無視するので不可能」「CORS回避には拡張機能を使え」と明記 |

### URLを転送するだけの拡張（ページを見ていない）

| リポジトリ | star | 理由 |
|---|---|---|
| [nexmoe/VidBee](https://github.com/nexmoe/VidBee) | 10,496 | 拡張の権限が `activeTab`/`storage` のみで content script エントリが存在しない。`tab.url` をローカル本体に投げるだけ。しかも version 0.0.1 のままストア未公開、公開CIは成功実行ゼロ |
| [neosubhamoy/neodlp](https://github.com/neosubhamoy/neodlp) | 561 | 拡張の権限は tabs/storage/contextMenus/nativeMessaging のみ。content script も webRequest もなく、URL文字列1本を Native Messaging で渡すだけ。blob: は右クリックしても `blob:https://...` が返って yt-dlp が扱えない |
| [GopeedLab/gopeed](https://github.com/GopeedLab/gopeed) | 26,063 | `downloadFilter()` の冒頭で `info.url.startsWith("blob:")` を明示的に return false。webRequest は `main_frame`/`sub_frame` 限定でm3u8のリクエストを観測すらしない。本体プロトコルは http/bt/ed2k のみ |
| [alexta69/metube](https://github.com/alexta69/metube) | 14,576 | Chrome拡張は `chrome.tabs.query` で現在タブのURLをPOSTするだけ。右クリックメニューは `targetUrlPatterns` が YouTube 限定 |
| [karakeep-app/karakeep](https://github.com/karakeep-app/karakeep) | 28,730 | 動画検出処理がソース上に存在しない。`crawlerWorker.ts` は設定がONなら全ブックマークに対して投機的に yt-dlp を撃つだけ |
| [ArchiveBox/ArchiveBox](https://github.com/ArchiveBox/ArchiveBox) | 28,224 | 拡張はタブURLをREST APIに送るだけ。サーバ側で yt-dlp を回す。認証は persona で事前エクスポートした cookies.txt 方式 |
| [Tzahi12345/YoutubeDL-Material](https://github.com/Tzahi12345/YoutubeDL-Material) | 3,200 | 同梱拡張は 2.6KB のURLリレー。しかも `current_url.includes('youtube.com')` の条件付きで、YouTube以外では入力欄の自動補完すらしない。Manifest V2 で現行Chromeに載らない |
| [marcopiovanello/yt-dlp-web-ui](https://github.com/marcopiovanello/yt-dlp-web-ui) | 2,566 | リポジトリ内に manifest.json が1つも存在しない（code search で確認）。第三者製拡張もリンクのhrefを転送するだけ |
| [aandrew-me/ytDownloader](https://github.com/aandrew-me/ytDownloader) | 10,261 | 拡張のコードベース自体を持たない。入力経路はテキストボックスへの手入力とクリップボード読み取りボタンのみ |
| [jely2002/youtube-dl-gui](https://github.com/jely2002/youtube-dl-gui) | 9,116 | Issue #314「Browser Extension to Find Videos」を 2025-12 に not_planned でクローズ済み。メンテナが拡張を明確に却下 |
| [NickvisionApps/Parabolic](https://github.com/NickvisionApps/Parabolic) | 6,981 | 拡張は実在するが権限が activeTab/contextMenus/storage のみで `parabolic://` にURLを投げるだけ。しかも macOS の Info.plist に CFBundleURLTypes がなく、その唯一の連携すら成立しない疑い |
| [mhogomchungu/media-downloader](https://github.com/mhogomchungu/media-downloader) | 4,952 | READMEの「Extensions」はブラウザ拡張ではなく CLI バックエンド(yt-dlp/aria2c 等)の差し替え定義 |
| [Rudloff/alltube](https://github.com/Rudloff/alltube) | 2,968 | **アーカイブ済み**。URL入力フォーム1個。yt-dlp が `^2023.03` で固定、PHP 7.4(EOL)、公式Dockerイメージは2021年amd64ビルド |
| [manbearwiz/youtube-dl-server](https://github.com/manbearwiz/youtube-dl-server) | 934 | ブックマークレットが `window.location.href` をPOSTするだけ。Starlette を debug=True で起動し、無認証の `PUT /youtube-dl/update` が `pip install --upgrade` を実行する |
| [nbr23/youtube-dl-server](https://github.com/nbr23/youtube-dl-server) | 315 | 同上。ブックマークレットは location.href のみ。front/ はサーバ管理UIのVue SPA |
| [sooros5132/yt-dlp-web](https://github.com/sooros5132/yt-dlp-web) | 163 | **メンテ停止**（15ヶ月）。ソースツリー170ファイル全体に content script/manifest.json なし。ライセンス未設定 |
| [rroller/media-roller](https://github.com/rroller/media-roller) | 129 | ブックマークレットが location.href を渡すだけ。加えて `-` で始まるクエリパラメータをそのまま yt-dlp の引数に渡す実装があり、外部公開すると任意コマンド実行に直結 |
| [snarfed/huffduff-video](https://github.com/snarfed/huffduff-video) | 95 | **アーカイブ済み・公式インスタンス停止済み**。最終コミットが「decommisioning」 |
| [exotic123567/yt-dlp-bridge](https://github.com/exotic123567/yt-dlp-bridge) | 14 | webRequest も content_scripts も宣言なし。`--cookies-from-browser` も未実装。Windows専用(.bat/.reg)、LICENSE不在、Issue 7件全て未対応 |

### 定期購読・アーカイバ（そもそも単発URLを受け付けない）

| リポジトリ | star | 理由 |
|---|---|---|
| [meeb/tubesync](https://github.com/meeb/tubesync) | 2,789 | ソース種別が CHANNEL/CHANNEL_ID/PLAYLIST の3つのみで、`path_must_not_match` に `/watch`, `/shorts`, `/live` が明示列挙されており**単発動画URLをコードレベルで拒否** |
| [kieraneglin/pinchflat](https://github.com/kieraneglin/pinchflat) | 5,293 | router.ex の `:api` パイプラインを通るルートが `/healthcheck` 1本のみ。外部から投入する導線が存在しない |
| [dongaba/TVerRec](https://github.com/dongaba/TVerRec) | 237 | TVer API のキーワードクロール型。同梱Chrome拡張は platform_uid/platform_token を抜く認証情報キャプチャで、動画URLには触れていない |

### 汎用URL解決サービス

| リポジトリ | star | 理由 |
|---|---|---|
| [imputnet/cobalt](https://github.com/imputnet/cobalt) | 42,564 | `getHostIfValid()` が対応21サービスのホワイトリストと照合し、外れると `link.invalid` を返す。拡張なし。web/ は CC BY-NC-SA(商用不可) |

### 部品・ライブラリ

| リポジトリ | star | 理由 |
|---|---|---|
| [ffmpegwasm/ffmpeg.wasm](https://github.com/ffmpegwasm/ffmpeg.wasm) | 17,771 | 取得済みバイト列を変換するだけ。検出も抽出もしない。main の実装は約1年停滞 |
| [jimmywarting/StreamSaver.js](https://github.com/jimmywarting/StreamSaver.js) | 4,366 | 「保存先の口」だけのライブラリ。実装コードは約3年停止し、著者自身が File System Access API への移行を推奨 |
| [borisbabic/browser_cookie3](https://github.com/borisbabic/browser_cookie3) | 1,072 | **メンテ停止**（20ヶ月）。Cookie DB を復号するだけ。yt-dlp の `--cookies-from-browser` で同等機能が内蔵済み。Chrome v20 (App-Bound Encryption) 未対応の issue が放置 |
| [webrecorder/browsertrix-crawler](https://github.com/webrecorder/browsertrix-crawler) | 1,127 | 汎用Webアーカイバ。出力は WARC/WACZ で再生可能な動画ファイルではない。動画検出のUI・判定ロジックがソースに存在しない |
| [akiirui/mpv-handler](https://github.com/akiirui/mpv-handler) | 412 | `mpv-handler://` を受けて mpv を起動するだけ。ダウンロード機能なし、macOS 公式バイナリなし |
| [smashedr/hls-downloader-go](https://github.com/smashedr/hls-downloader-go) | 2 | 267行のネイティブメッセージングホスト。検出機能ゼロで、Cookie/Referer を受け取るフィールドが構造体レベルで存在しない |

### プラットフォーム不一致・重大な欠陥

| リポジトリ | star | 理由 |
|---|---|---|
| [subhra74/xdm](https://github.com/subhra74/xdm) | 7,899 | 機構は本物（webRequest + ネイティブメッセージング + 内蔵FFmpegでHLS/DASH解析）だが、**XDM 8.x に macOS ビルドもソースも存在しない**。MV3拡張が要求するネイティブホストが macOS 向けに存在せず連携が物理的に断線。実質メンテ停止（2024-01、issue 850件） |
| [filecxx/FileCentipede](https://github.com/filecxx/FileCentipede) | 10,895 | 拡張の機構は本物だが update.json の mac 欄が空で**macOSビルドが一度も出ていない**。加えて OSS ではない（ライセンス表記ゼロ、依存ライブラリ非公開、有償化予告あり）。本体の最終リリースは2023-02 |
| [setvisible/ArrowDL](https://github.com/setvisible/ArrowDL) | 845 | 拡張が収集するのは `<a>` の href と `<img>` の src のみ。`getElementsByTagName("video")` が存在せず webRequest 権限もない。macOS の Native Messaging インストーラは「TODO」の走り書きのみ |
| [JunkFood02/Seal](https://github.com/JunkFood02/Seal) | 28,666 | Androidアプリ。共有シートで受け取ったURLを yt-dlp に渡すだけ |
| [Alos21750/UAV-Downloader](https://github.com/Alos21750/UAV-Downloader) | 342 | 「UAV Browser」はブラウザではない（selenium/playwright/CEF いずれも依存になし）。4サイト専用スクレイパ |
| [yoyokits/VideoBrowser](https://github.com/yoyokits/VideoBrowser) | 25 | CefSharp 内蔵だが動画検出の実体は `FullUrl.Contains("youtube.com/watch?v=")` の1行。Windows専用(.NET Framework 4.8 + WPF)、機能開発は2022年3月で停止 |

### 中身が空・OSSではない

| リポジトリ | star | 理由 |
|---|---|---|
| [aclap-dev/video-downloadhelper](https://github.com/aclap-dev/video-downloadhelper) | 1,081 | リポジトリ内の blob が README・スクリーンショット・Discussion テンプレ2件の4つだけ。実体は商用製品のサポート掲示板。AMO 上のライセンスは Custom(独自プロプライエタリ) |
| [aclap-dev/vdhcoapp](https://github.com/aclap-dev/vdhcoapp) | 30 | **アーカイブ済み**。単体では動画検出をせず、VDH v10 以降は不要と公式に宣言済み |
| [qiye45/wechatVideoDownload](https://github.com/qiye45/wechatVideoDownload) | 5,707 | ソースコードが1行も存在しない（README + リリースzipの配布窓口のみ）。ライセンス不在。Windows専用 |

### 対象サイト特化（汎用性なし）

| リポジトリ | star | 理由 |
|---|---|---|
| [the1812/Bilibili-Evolved](https://github.com/the1812/Bilibili-Evolved) | 30,360 | bilibili専用。機構は本物（Cookie込みで playurl API を叩き ffmpeg.wasm で mux）だが他サイトでは動かない。manifest.json は存在せず userscript 単体 |
| [88lin/video_vip](https://github.com/88lin/video_vip) | 4,784 | ページ内のストリームを解析せず、タイトル文字列で第三者の海賊版CMSを検索して別ソースを再生するだけ。ダウンロード機能ゼロ。むしろページの動画を stopMedia() で停止させている |
| [limbopro/Adblock4limbo](https://github.com/limbopro/Adblock4limbo) | 4,493 | 本体は広告ブロッカー。動画検出は副機能で、ネットワーク傍受を一切実装せず DOM を1回舐めるだけ。汎用ファインダーは実行時に作者ドメインからリモートロードされる |
| [hoothin/UserScripts](https://github.com/hoothin/UserScripts) | 4,277 | 動画関連4本を全て確認したが検出機構なし。「ページ内の動画リンクを見つける」と謳う Easy offline も `a[href$=".mp4"]` の拡張子マッチのみで、しかも主要動画サイトを @exclude で除外 |
| [YePpHa/YouTubeCenter](https://github.com/YePpHa/YouTubeCenter) | 2,905 | **メンテ停止・2018年で更新停止**。依存していた `ytplayer.config` のストリームマップが2017年のPolymer移行で消滅。Chrome拡張版はMV2 |
| [ltaoo/wx_channels_download](https://github.com/ltaoo/wx_channels_download) | 9,002 | JS注入アセットを持つアダプタが wxchannels/wxmp/zhihu の3つだけ。汎用のメディアスニッフィングがプロキシ層に存在しない。ルートCAをSystemキーチェーンに入れる代償が用途に釣り合わない |
| [magicoflolis/Magic-PH](https://github.com/magicoflolis/Magic-PH) | 167 | **メンテ停止**（18ヶ月）。成人向け18ドメイン決め打ち。README自身が対象サイトのポリシー違反を明言 |
| [IwaraEnhance/IwaraDownloadTool](https://github.com/IwaraEnhance/IwaraDownloadTool) | 420 | iwara.tv 専用（@include が `*://*iwara*/*`）。m3u8/DASH/blob の解析コードはゼロ |
| [Panopto-Video-DL/Panopto-Video-DL-browser](https://github.com/Panopto-Video-DL/Panopto-Video-DL-browser) | 116 | Panopto専用。DOM走査もネットワーク傍受もせず、内部API `DeliveryInfo.aspx` を決め打ちで叩くだけ。ライセンス未設定 |
| [bytedream/stream-bypass](https://github.com/bytedream/stream-bypass) | 230 | 19ホストのドメイン固定ハードコード。ダウンロード機能なし(downloads 権限すら持たない)。Chrome版は機能削減版 |
| [JustKappaMan/VK-Video-Downloader](https://github.com/JustKappaMan/VK-Video-Downloader) | 305 | VK専用。HLS/DASH/blob は扱わず、`window.mvcur.player.vars` のプログレッシブMP4直リンクに完全依存 |
| [kanadeblisst00/WechatVideoSniffer](https://github.com/kanadeblisst00/WechatVideoSniffer) | 332 | **メンテ停止**（25ヶ月）。検出が `finder.video.qq.com/251/20302` のハードコード1パターンのみ。aardio + .NET FiddlerCore の Windows 専用。復号キーを httpbin.org に送る細工コードを注入する |
| [woodruffw/ff2mpv](https://github.com/woodruffw/ff2mpv) | 639 | 検出はブラウザ標準の右クリックメニュー任せ(`info.srcUrl`)で自前解析はゼロ。blob:/MSE と要認証ページには実質使えない |

### 個人の習作・未完成品

| リポジトリ | star | 理由 |
|---|---|---|
| [izamashidog/StreamDownloader](https://github.com/izamashidog/StreamDownloader) | 0 | 実際にビルド検証したが dist/ に manifest.json もHTMLも出ず拡張として読み込めない。SWも起動せず、目玉のContent-Type検出とffmpeg.wasm muxは原理的に動かない。README に「全コードをAIが生成」と明記 |
| [joseedis157-afk/Media-Sniffer-Advanced](https://github.com/joseedis157-afk/Media-Sniffer-Advanced) | 0 | ダウンロード機能が1行も存在しない。検出URL一覧は console.log にしか出ず、UIから取れるのは「先頭1件を小窓で再生」だけ。blob:/MSE は正規表現方式ゆえ原理的に不可 |
| [FrankMutuma/AnyVideoDownloader](https://github.com/FrankMutuma/AnyVideoDownloader) | 0 | HLS/DASH の文字列すら存在しない。ファイル名サニタイザが日本語を全消去（「徳島旅行 2026」→ `_2026`）。リポジトリ本体の正規表現が二重バックスラッシュで壊れており検出が動かない |
| [carmelobattiato/Universal-Video-Sniffer](https://github.com/carmelobattiato/Universal-Video-Sniffer) | 2 | READMEが謳う MutationObserver・MSE傍受・JSON解析がコードに一切存在しない。DASH は検出するがパーサがなく、押すとマニフェストXMLが .mp4 として保存される |
| [gabekole/m3u8Downloader](https://github.com/gabekole/m3u8Downloader) | 0 | **メンテ停止**（14ヶ月）。Chrome 136+ で `--user-data-dir` 必須になり「ログイン済みセッションをそのまま使う」という売りが成立しない。検出は `endsWith('.m3u8')` の完全一致のみ |
| [chuyeow/reel](https://github.com/chuyeow/reel) | 0 | 検出4系統は本物だが Cookie 転送が未実装（yt-dlp 呼び出しに `--cookies-from-browser` なし）。コミット30本超が全て2026-04-04の1日に集中し以後5ヶ月放置、README・LICENSE ともになし |
| [okuseyoshio/video-lens](https://github.com/okuseyoshio/video-lens) | 0 | 機構は素直だがライセンス皆無、5.5ヶ月更新なし、DASH非対応、HLSが ffmpeg なしの .ts 単純連結、認証付きHLSは Cookie が乗らず落ちる公算大 |
| [faridhafizh/video-downloader-ext](https://github.com/faridhafizh/video-downloader-ext) | 9 | リポジトリ作成から14分で完成した単発コミット。DASHは検出だけしてマニフェストXMLが落ちる、fMP4非対応、ポップアップを閉じるとDLが死ぬ |
| [Nhj-sz/media-catcher-extension](https://github.com/Nhj-sz/media-catcher-extension) | 1 | HLS/DASH は検出してもDLボタンを意図的に無効化（yt-dlpに丸投げ）。真の抽出はB站専用ハードコード。全11コミットが2日間に集中し以後2ヶ月無音 |
| [AllShadowAnan/browser-media-sniffer](https://github.com/AllShadowAnan/browser-media-sniffer) | 1 | 検出3層は実装されているがストリームのDLは未実装（URLコピー止まり）。コミット3件が全て同日、READMEに `your-username` のプレースホルダが残存 |
| [xuewexin/m3u8-sniffer](https://github.com/xuewexin/m3u8-sniffer) | 1 | 嗅探は動くが host.py の実行ファイルパスが `.exe` 決め打ちで macOS では必ず止まる。Cookie も渡さない（Referer/UA のみ） |
| [likunqi/xiaoe-downloader](https://github.com/likunqi/xiaoe-downloader) | 8 | 小鹅通の5ドメイン限定。Cookie を渡さず期限付きURL頼み。コミット1本、Issue #1「下载不了」が未回答 |
| [wujiangbj/VideoDownloader](https://github.com/wujiangbj/VideoDownloader) | 1 | Playwright の page.route による捕捉は本物だが、毎回まっさらなコンテキストを作るため Chrome のログイン状態を継承しない。Windows前提のハードコード多数、ライセンス不在 |
| [drhema/anyvideodownload](https://github.com/drhema/anyvideodownload) | 1 | 機構は真っ当だが star 1・テストゼロ・ライセンス未設定・リポジトリ作成から19分で全push・以後4ヶ月放置。ユーザーのChromeセッションを引き継がない |
| [StasonJatham/m3u8_dl](https://github.com/StasonJatham/m3u8_dl) | 2 | 検出条件が `'index.m3u8' in url` / `'/api/v1/watch/'` / 固有XPath の特定サイト決め打ち。毎回新規コンテキストでセッション非継承 |
| [ArtByteFilip/hls-stream-capture](https://github.com/ArtByteFilip/hls-stream-capture) | 0 | 既存Chromeではなく使い捨てプロファイルを `--disable-extensions` で起動。ffmpeg に Referer しか渡さない。デフォルトURLがチェコの海賊版サイトにハードコード |
| [lucianoestevest477-bit/playwright-network-sniffer](https://github.com/lucianoestevest477-bit/playwright-network-sniffer) | 1 | 遷移先URLがブラジルの違法スポーツ配信サイトにハードコードされた使い捨てスクリプト。ダウンロード機能なし |
| [Jane-xiaoer/xiaoer-videolab](https://github.com/Jane-xiaoer/xiaoer-videolab) | 594 | webRequest 権限すら持たない。「検出」の実体はサーバ側で `yt-dlp --dump-json` を実行しているだけ。真のページ内抽出は抖音・小紅書の2サイト限定。開発実績は4日間のみ |
| [Neet-Nestor/Telegram-Media-Downloader](https://github.com/Neet-Nestor/Telegram-Media-Downloader) | 5,418 | Telegram Web 専用（@match が3ドメイン）。機構は本物（DOM検出 + Range 分割 fetch）だが汎用性なし |
| [redoste/StreamCleaner](https://github.com/redoste/StreamCleaner) | 6 | **アーカイブ済み**。作者自ら「DON'T USE THIS ANYMORE. PREFER youtube-dl」と明記。対応4サイトのうち3つが既に閉鎖 |
| [a-sync/get-video-source](https://github.com/a-sync/get-video-source) | 8 | **メンテ停止**（7年4ヶ月）。実機検証したところ MSE ページでは blob: URL しか返らず yt-dlp に渡せない。progressive MP4 限定 |

---

## 技術的な現実

ここが実務で一番刺さる部分。ツールの優劣より、以下の制約が結果を決める。

### Manifest V3 の webRequest 制約

MV3 では `webRequestBlocking` が使えず、リクエストの改変は `declarativeNetRequest` に移行した。ただし**観測（非ブロッキングの `webRequest`）は今も使える**ので、m3u8/mpd の検出自体は問題なく動く。実際に cat-catch も live-stream-downloader も flowpick も onHeadersReceived/onSendHeaders で普通に捕捉している。Referer/Origin の書き換えが必要な場合（ホットリンク保護）は `declarativeNetRequest.updateSessionRules` でタブ単位のルールを張る、という実装が定石になっている。

一方で MV3 固有の実害は **service worker が約30秒アイドルで停止すること**。停止後にリスナーが再登録されない書き方だと検出が黙って止まる。54ac/stream-detector の Chrome 版がまさにこれで、top-level の async IIFE 内で複数 await した後に `addListeners()` を呼ぶ構造のため、SW 復帰時にリスナーが張られない。cat-catch は alarms/HeartBeat で対策しているが取りこぼしはゼロではない。長時間開いたタブで検出が効かなくなったら、まずタブをリロードすること。

### DRM (Widevine/FairPlay/PlayReady) は取れない

調査した全ツールで例外なく取れない。Netflix・Amazon Prime・Disney+・U-NEXT・DAZN・TVer(有料)などの EME 暗号化配信は原理的に対象外。取れるのは平文の HLS/DASH/MP4/FLV と、マニフェストに鍵URLが載る AES-128 HLS まで。

例外的に WidevineProxy2 が EME をフックして CDM を差し替える実装を持つが、動かすには自前の Widevine デバイスファイル(.wvd)が必要で、それは配布されていない。加えて L3 相当なので主要サービスは Android CDM を拒否するか SD 画質に制限する。何より**日本では著作権法30条1項2号により、技術的保護手段の回避を伴う複製は私的使用目的でも例外の対象外**になる。不正競争防止法の技術的制限手段回避装置の提供規制にも触れうる。実用ツールとして数えないこと。

なお「Supports encrypted HLS」という表記は AES-128 の話であって DRM とは別物。混同しないこと。

### blob:/MSE の扱い

現代の動画サイトの大半は MSE (Media Source Extensions) を使う。プレイヤーが JS でセグメントを取得して `SourceBuffer.appendBuffer()` に流し込むため、`<video>` の `currentSrc` は `blob:https://...` になる。この blob: URL はページのオリジンに閉じたメモリ上のハンドルで、yt-dlp にも curl にも渡せない。実機で `a-sync/get-video-source` を検証したところ、progressive な `<video src>` では直リンクが返るが、MSE ページでは blob: しか返らないことを確認済み。

対処は2通り。

**(1) 下層のネットワークリクエストを拾う（王道）**
blob: の裏では必ず m3u8/mpd とセグメントが HTTP で流れているので、webRequest でそちらを捕まえる。cat-catch・live-stream-downloader・flowpick・WebVideo2NAS はいずれもこの方式。これが最も現実的。

**(2) MediaSource を Proxy 化してバッファを直接横取り（最終手段）**
`MediaSource.prototype.addSourceBuffer` と `SourceBuffer.appendBuffer` を差し替えて、流れてきた ArrayBuffer を全部貯める。Momo707577045/media-source-extract が原典で、cat-catch・flowpick・h5player・xxxily 系が同じ手法を実装している。ただし以下の代償がある。

- **プレイヤーが MediaSource を生成する前に Proxy を仕込む必要がある** → ページのリロードが必須（cat-catch は `bypassCache` で自動リロードする）
- **再生を最後まで実際に流し切らないと全部揃わない** → 1時間の動画は最低でも数分〜1時間かかる
- **全セグメントを JS 配列でメモリ保持する** → 長尺はタブごと落ちる
- **音声と映像が別ファイルで出る** → `ffmpeg -i video.mp4 -i audio.mp4 -c copy out.mp4` で自分で mux する
- ABR で途中に画質が変わると解像度が混在して壊れることがある

要するに MSE 捕獲は「他が全部ダメだったときの手段」。まず (1) を試すべき。

### 認証付きページには --cookies-from-browser が要る

拡張が「検出できたのに落とせない」の最大の原因はここ。

**拡張内蔵ダウンローダの落とし穴**: 拡張のオリジンから `fetch()` する場合、credentials が既定の `same-origin` になるためクロスオリジンの CDN に Cookie が載らない。puemos/hls-downloader、cssnr/hls-video-downloader、okuseyoshio/video-lens はいずれもこの状態で、コード上 `credentials` の指定がない。署名付きURL型の配信は通るが、Cookie 必須の配信は 403 になる。

**userscript の落とし穴**: `document.cookie` は HttpOnly Cookie を読めない。主要サービスのセッション Cookie はほぼ HttpOnly なので、lzwme/m3u8-dl の captureHeaders のような「document.cookie を渡す」実装では認証壁を越えられない。

**最も確実な経路**: 拡張で URL と Referer だけ拾い、実ダウンロードは yt-dlp に投げる。

```
yt-dlp --cookies-from-browser chrome \
       --referer "https://example.com/watch/123" \
       "https://cdn.example.com/hls/master.m3u8"
```

実機検証で Chrome のライブプロファイルから 3,364 件の Cookie 読み出しに成功している（macOS Keychain 経由で v10 暗号化を復号）。初回は Keychain のアクセス許可ダイアログが出る。なお Safari の Cookie は TCC 制限で `Operation not permitted` になるので、ターミナルにフルディスクアクセスを付与する必要がある（Chrome は不要）。

**ヘッダを丸ごと引き継げる拡張**: 54ac/stream-detector（アーカイブ済みだが Firefox 版は現役）は `extraHeaders` 付きで Cookie ヘッダを読み、`--add-header "Cookie:..."` 込みの yt-dlp コマンドを生成する。この用途では今も最強クラス。

### CDP アタッチはもう「ログイン状態のまま」ではない

Chrome 136 以降、既定プロファイル（既定の user-data-dir）に対するリモートデバッグ接続は拒否される。`--remote-debugging-port=9222` を使うには `--user-data-dir` で別プロファイルを指定せざるを得ず、その時点で普段のログイン Cookie は引き継がれない。gabekole/m3u8Downloader の「既存 Chrome にアタッチして閲覧セッションをそのまま使う」という売りは、この仕様変更で成立しなくなっている。chromedp や vsd で自作する場合も同じ壁に当たる。

例外は royswift2007/m3u8-video-sniffer が使う `launch_persistent_context(channel="chrome")` 方式で、これは専用の user_data_dir を使い回す（=そこで一度ログインすれば状態は残る）。ただし既存の Chrome が同じプロファイルを掴んでいるとロック衝突で一時プロファイルにフォールバックし、ログイン状態が消える。

### 検出フィルタの取りこぼし

多くのツールが「URL 末尾の拡張子」で判定している。これだと `/manifest?type=hls` や `/playlist?token=...` のような**拡張子を持たない配信 URL を丸ごと取りこぼす**。zamgi/m3u8（`.m3u8` 完全一致）、Leenshady/m3u8Sniffer2（末尾一致）、vsd（拡張子マッチ）などが該当。

対策として Content-Type ヘッダ（`application/vnd.apple.mpegurl`, `application/x-mpegurl`, `application/dash+xml`）を併用しているのが cat-catch・flowpick・live-stream-downloader・VantaEther。さらに flowpick と WidevineProxy2 はレスポンス**本文**を読んで `#EXTM3U` / `<MPD` を判定するので取りこぼしが最も少ない。検出漏れが多いと感じたら、Content-Type 判定まで持っているツールに乗り換えること。

もう一点、`types: ["xmlhttprequest"]` に限定しているツール（puemos/hls-downloader、media-bridge）は `media` タイプで飛ぶリクエストを見ない。逆に素の `<video src="*.mp4">` のプログレッシブ再生はブラウザのネイティブメディアローダが読むため fetch/XHR フック型の userscript では捕まらない。この2つは検出網の穴として認識しておくこと。

### 権限の重さ

要件の性質上、どのツールも `<all_urls>` + `webRequest`（+ 多くは `cookies`）を要求する。これは「訪問した全サイトの通信とCookieを読める」権限で、銀行も業務SaaSも例外ではない。star 数の少ない個人開発の未監査拡張にこれを渡すのは割に合わない場面が多い。実用するなら、cat-catch のような監査母数の大きいものを選ぶか、動画取得専用の Chrome プロファイルを分けること。

MITM プロキシ型（res-downloader、resd-mini、go-mitmproxy、mitmproxy）はさらに一段強い。ルート CA をシステムキーチェーンに信頼登録するため、ブラウザだけでなく Mac 上の全アプリの HTTPS が復号可能な状態になる。作業後は必ず証明書を削除し、システムプロキシ設定を戻すこと。

### 法的注意

日本の著作権法では、違法配信と知りながら行う動画のダウンロードは私的使用目的でも例外の対象外（30条1項3号・4号）で、有償著作物については刑事罰の対象になる。また技術的保護手段（DRM）の回避を伴う複製は同30条1項2号により私的複製から外れ、回避装置の提供は不正競争防止法にも触れうる。加えて技術的に取得できることと各サービスの利用規約上許されることは別問題で、多くの配信サービスは規約でダウンロードを明示的に禁じている。自分に権利があるコンテンツ、権利者の許諾があるもの、パブリックドメインに限って使うのが実務上の線。