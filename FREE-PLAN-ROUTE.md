# tl;dv 録画取得 調査レポート

対象: Free プラン、macOS / Chrome。目的は「閲覧できる録画について、長尺でも全セグメントを漏れなく取得すること」。

---

## 結論: フリーで取るならこれ

**`GET https://gaia.tldv.io/v1/meetings/{meetingId}/playlist.m3u8` を Bearer JWT で叩き、返ってきた難読化 m3u8 をシーザー復号する。**

これ1リクエストで、録画全体の VOD メディアプレイリスト（= 全セグメントの署名付き URL）が一括で返る。シーク連打も fetch フックも実時間再生も一切不要。

| 項目 | 判定 |
|---|---|
| 全セグメント漏れなく | 取れる（VOD プレイリストが全セグメントを列挙するため構造的に漏れない） |
| 実時間再生 | 不要。ページを再生すらしなくてよい |
| 壊れやすい点 | JWT の取り出し方（後述）、署名の有効期限、master playlist が返ってきた場合 |

### なぜこれが正解だと言えるか

推測ではなく、tl;dv 自身の出荷バンドルにこの経路がそのまま書いてある。

- `/tmp/tldvjs/src-B6g1f1c2.js` offset 102477
  `getSecuredMeetingPlaylist(e,n){return t.getWithResponse(\`/v1/meetings/${e}/playlist.m3u8\`,n)}`
- そのクライアント `ll` の bind 先を追跡: `Y4=e=>Object.assign(W4,ll(e))` → `H6` 内 `Y4({...G.gaia})` → `/tmp/tldvjs/src-Dw3pBLAH.js` offset 471007 `gaia:{baseURL:"https://gaia.tldv.io"}`
- 復号器も同バンドル内（src-B6g1f1c2.js offset 約 5399141〜）。`z9`（シフト表）/ `sne`（`#TLDVCONF:` パース）/ `cne`（`#` 以外の行に prefix + caesar）/ `ine`（`data:application/vnd.apple.mpegurl;base64,` 化）
- そのまま `URL.createObjectURL` で blob: 化してプレイヤーに渡している。実測事実5（`<video>` が blob:、プレイリストが data: URI）の発生源そのもの。
- 実測事実3（`video.source` が署名なし S3 で 403）は矛盾ではなく前提。`video.source` はプレイヤーが**使っていない**フィールド。webapp のコードに `watch-page` という文字列は233チャンク中1件も無い。

エンドポイントの生存もライブで確認済み（無認証・ダミー ID）:

```
GET gaia.tldv.io/v1/meetings/000000000000000000000000/playlist.m3u8 -> 404 {"message":"Meeting not found"}
同上 + Bearer a.b.c                                                  -> 401 invalid token
gaia.tldv.io/v1/meetings/<id>/存在しないルート                        -> 404 "Cannot GET ..." (Express 既定)
```

つまり専用ハンドラが登録済みで、JWT 検証も動いている。

独立実装も一致している: `qwadratic/dl-tldv-extension`（src/pipeline/{api,playlist,caesar}.ts）、`ofcRS/yt-dlp-tldv`、`Dweeb1578/tldv-downloader`、`anasty17/mirror-leech-telegram-bot`、`Andrew-Sem/skills`。書式はすべて `#TLDVCONF:{expires},{shift},{baseUrl}`。

### 最重要: これまで失敗していた原因

作業ディレクトリの `raw.m3u8` は 13 バイトの `invalid token`。これは**プラン拒否ではなく、JWT の取り出し方の誤り**。

出荷コード `src-Dw3pBLAH.js` offset 438666:

```js
var ij=`_cap_jwt`;
function aj(){let e=localStorage.getItem(ij);
  if(e)try{let t=JSON.parse(e);return typeof t===`string`&&t?t:void 0}catch{return}}
```

`_cap_jwt` は **JSON エンコードされた文字列**であって、`.token` を持つオブジェクトではない。

- 誤: `JSON.parse(localStorage.getItem('_cap_jwt')).token` → `undefined` → `Bearer undefined` → 401 `jwt malformed`
- 誤: `localStorage.getItem('_cap_jwt')` をそのまま貼る（両端にダブルクォートが付く）→ 401 `invalid token`（13バイト。raw.m3u8 と完全一致）
- 正: `JSON.parse(localStorage.getItem('_cap_jwt'))`

`ofcRS/yt-dlp-tldv` の案内文および手元の `tldv_gaia_verify.sh` も `.token` を使っており、この誤りが伝播している。

エラー本文で切り分けられる（実測済み）:

| レスポンス | 意味 |
|---|---|
| 401 `jwt malformed` | `undefined` を送っている（`.token` を付けた） |
| 401 `invalid token` | ダブルクォート付きで送っている、またはトークン失効 |
| 401 `invalid signature` / `jwt expired` | ログインし直して取り直す |
| 404 `Meeting not found` | **無認証時と同じ応答**。ID を疑う前に Authorization が飛んでいるか確認する |
| 403 + プラン文言 | このときだけ「Free で gaia が閉じている」が確定する |

---

### 手順1: ページ内コンソールで完結させる（推奨）

タイミング問題が原理的に存在しない構成。フックを一切使わず、ページのオリジンから自分で API を叩くだけなので、リロードで消えるものが無い。tl;dv の録画ページを開いた状態で DevTools コンソールに貼る。

```js
(async () => {
  // ---- 1. JWT。_cap_jwt は JSON エンコードされた「文字列」。.token は存在しない ----
  const rawJwt = localStorage.getItem('_cap_jwt');
  let jwt;
  try { jwt = JSON.parse(rawJwt); } catch { jwt = rawJwt; }
  if (typeof jwt !== 'string' || !jwt) {
    throw new Error('_cap_jwt を文字列として取得できない。ログインし直してから再実行');
  }

  // ---- 2. meetingId (24桁hex) ----
  const id = (location.href.match(/[0-9a-f]{24}/i) || [])[0];
  if (!id) throw new Error('URL から meetingId を取れない。/app/meetings/<id> を開いて実行する');

  // ---- 3. 難読化プレイリスト取得 ----
  const res = await fetch(`https://gaia.tldv.io/v1/meetings/${id}/playlist.m3u8`, {
    headers: {
      'Authorization': 'Bearer ' + jwt,
      'X-Tldv-Client': 'tldv-webapp/1.0.0',
      'Accept': 'application/vnd.apple.mpegurl,*/*',
    },
  });
  const raw = await res.text();
  console.log('HTTP', res.status, res.statusText, '| bytes', raw.length);
  if (!res.ok) { console.error(raw.slice(0, 300)); return; }

  // ---- 4. 復号 (出荷コード z9 / sne / cne / W9 と同一セマンティクス) ----
  const rot = (s, k) => {
    let o = '';
    for (let i = 0; i < s.length; i++) {
      const c = s.charCodeAt(i);
      if (c >= 65 && c <= 90)       o += String.fromCharCode(((c - 65 + k) % 26 + 26) % 26 + 65);
      else if (c >= 97 && c <= 122) o += String.fromCharCode(((c - 97 + k) % 26 + 26) % 26 + 97);
      else                          o += s[i];
    }
    return o;
  };

  const lines = raw.split('\n');
  let playlist, conf = null;
  if (lines.length >= 2 && lines[1].startsWith('#TLDVCONF:')) {
    // #TLDVCONF:<expiresSec>,<shift 0..25>,<prefix>   prefix に ',' が入りうるので join で復元
    const p = lines[1].slice('#TLDVCONF:'.length).split(',');
    const expires = Number(p[0]), shift = Number(p[1]), prefix = p.slice(2).join(',');
    if (!(shift >= 0 && shift <= 25)) throw new Error('shift が範囲外: ' + shift);
    conf = { expiresSec: expires, shift, prefix };
    const out = [lines[0]];                       // #TLDVCONF 行は捨てる
    for (const l of lines.slice(2)) {
      out.push(l && !l.startsWith('#') ? prefix + rot(l, shift) : l);
    }
    playlist = out.join('\n');
  } else {
    playlist = raw;                               // 難読化なし。出荷コードも同じ分岐をする
    console.warn('#TLDVCONF なし。素の m3u8 として扱う');
  }

  // ---- 5. 完全性ゲート。ここが「漏れなく取れたか」の唯一の機械的証明 ----
  const segs   = playlist.split('\n').filter(l => l.trim() && !l.startsWith('#'));
  const extinf = [...playlist.matchAll(/#EXTINF:([\d.]+)/g)].map(m => parseFloat(m[1]));
  const sum    = extinf.reduce((a, b) => a + b, 0);
  const report = {
    conf,
    segments: segs.length,
    extinf_count: extinf.length,
    playlist_seconds: +sum.toFixed(1),
    endlist: playlist.includes('#EXT-X-ENDLIST'),          // false なら不完全。落とすな
    master:  playlist.includes('#EXT-X-STREAM-INF'),       // true なら variant で引き直す
    signed:  /X-Amz-Signature=/.test(playlist),            // false なら復号が失敗している
    first: segs[0], last: segs[segs.length - 1],
  };
  console.table(report);
  const v = document.querySelector('video');
  if (v && isFinite(v.duration)) {
    console.log('video.duration =', v.duration.toFixed(1),
                '| 差分 =', (sum - v.duration).toFixed(1), '秒 (数秒以内なら完全)');
  }

  // ---- 6. decoded.m3u8 を保存 ----
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([playlist], { type: 'application/vnd.apple.mpegurl' }));
  a.download = `tldv_${id}.m3u8`;
  document.body.appendChild(a); a.click(); a.remove();

  window.__tldv = { raw, playlist, conf, report };
  console.log('window.__tldv に格納した。copy(__tldv.playlist) でクリップボードにも取れる');
})();
```

判定基準（この3つが揃って初めて「全部揃った」と言える）:

- `signed: true`
- `endlist: true`
- `master: false`
- `playlist_seconds` が録画の実尺と数秒以内で一致

`master: true` の場合は、復号済みの variant URL に対してもう一度同じ処理を掛ける。

### 手順2: ダウンロード

`--abort-on-unavailable-fragment` は必須。**付けないと yt-dlp は1本 404 でも「100%」と表示して exit 0 を返し、無言で穴の空いた mp4 を作る**（実測: 20秒素材で 10.03 秒のファイルが「成功」として出力された。ffprobe の duration もそれらしい値になるため気づけない）。ffmpeg も同条件で同じく無言で切り詰める。

```bash
cd ~/Downloads
yt-dlp --enable-file-urls --hls-prefer-native --force-overwrites \
       --abort-on-unavailable-fragment --retries 10 --fragment-retries 20 \
       -N 16 -o out.mp4 "file://$PWD/tldv_<id>.m3u8"

# 検証: プレイリストの sum(EXTINF) と突き合わせる。単独の ffprobe では欠落を検出できない
ffprobe -v error -show_entries format=duration,size -of default=nw=1 out.mp4
ffmpeg  -v error -i out.mp4 -f null -        # 出力が空ならデコードエラーなし
```

ffmpeg で直接やる場合:

```bash
ffmpeg -protocol_whitelist file,http,https,tcp,tls,crypto -allowed_extensions ALL \
       -i tldv_<id>.m3u8 -c copy -bsf:a aac_adtstoasc -movflags +faststart -y out.mp4
```

### 手順3: CLI 版（バッチで回すなら）

`~/tldv-grab/tldv_gaia_dl.py` として保存。

```python
#!/usr/bin/env python3
"""gaia の難読化プレイリストを取得して復号する。出荷バンドルの z9/sne/cne/W9 の移植。"""
import argparse, json, sys, urllib.request, urllib.error

GAIA = "https://gaia.tldv.io/v1/{kind}/{id}/playlist.m3u8"   # kind: meetings|clips|reels
TAG  = "#TLDVCONF:"

def rot(s: str, k: int) -> str:
    o = []
    for ch in s:
        c = ord(ch)
        if   65 <= c <= 90:  o.append(chr(((c - 65 + k) % 26 + 26) % 26 + 65))
        elif 97 <= c <= 122: o.append(chr(((c - 97 + k) % 26 + 26) % 26 + 97))
        else:                o.append(ch)
    return "".join(o)

def decode(raw: str):
    lines = raw.split("\n")
    if len(lines) < 2:
        sys.exit("premature end of playlist")
    if not lines[1].startswith(TAG):
        return raw, {"obfuscated": False}          # 出荷コードも素通しする
    parts = lines[1][len(TAG):].split(",")
    expires, shift = int(parts[0]), int(parts[1])
    prefix = ",".join(parts[2:])                   # prefix に ',' が入りうる
    if not 0 <= shift <= 25:
        sys.exit(f"shift out of range: {shift}")
    out = [lines[0]]
    for l in lines[2:]:
        out.append(prefix + rot(l, shift) if (l and not l.startswith("#")) else l)
    return "\n".join(out) + "\n", {
        "obfuscated": True, "expires_in_sec": expires, "shift": shift, "prefix": prefix
    }

def main():
    p = argparse.ArgumentParser()
    p.add_argument("id")
    p.add_argument("--jwt", required=True, help="JSON.parse(localStorage._cap_jwt) の値。.token ではない")
    p.add_argument("-k", "--kind", choices=("meetings", "clips", "reels"), default="meetings")
    p.add_argument("-o", "--output", default="decoded.m3u8")
    a = p.parse_args()

    jwt = a.jwt.strip().strip('"')                 # 事故防止でクォートを剥がす
    req = urllib.request.Request(
        GAIA.format(kind=a.kind, id=a.id),
        headers={"Authorization": "Bearer " + jwt,
                 "X-Tldv-Client": "tldv-webapp/1.0.0",
                 "Accept": "application/vnd.apple.mpegurl,*/*",
                 "Origin": "https://tldv.io", "Referer": "https://tldv.io/",
                 "User-Agent": "Mozilla/5.0"})
    try:
        raw = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        body = e.read()[:300]
        hint = {401: "JWT が不正/失効。JSON.parse を通した文字列か確認",
                403: "アクセス権なし、またはプランゲート",
                404: "無認証でも同じ 404 が返る。Authorization が飛んでいるか先に疑う"}.get(e.code, "")
        sys.exit(f"HTTP {e.code}: {body!r}  {hint}")

    dec, meta = decode(raw)
    segs   = [l for l in dec.split("\n") if l.strip() and not l.startswith("#")]
    extinf = [float(x) for x in __import__("re").findall(r"#EXTINF:([\d.]+)", dec)]
    meta.update(segments=len(segs), playlist_seconds=round(sum(extinf), 1),
                endlist="#EXT-X-ENDLIST" in dec,
                master="#EXT-X-STREAM-INF" in dec,
                signed="X-Amz-Signature=" in dec)
    print(json.dumps(meta, ensure_ascii=False), file=sys.stderr)
    if not meta.get("signed"):
        print("WARNING: 署名パラメータが無い。復号が失敗している可能性", file=sys.stderr)
    if meta.get("master"):
        print("WARNING: master playlist。variant URL で引き直すこと", file=sys.stderr)
    if not meta.get("endlist"):
        print("WARNING: #EXT-X-ENDLIST が無い。全セグメントが揃っていない", file=sys.stderr)
    open(a.output, "w").write(dec)
    print(a.output)

if __name__ == "__main__":
    main()
```

```bash
python3 ~/tldv-grab/tldv_gaia_dl.py <meetingId> --jwt "$TLDV_JWT" -o decoded.m3u8
```

`expires_in_sec` は**残り秒数**であって epoch ではない（出荷コード `expiresInMs: U9(t,1)*1e3`）。手元の `tldv_playlist.py` は epoch 前提で `int(expires) - time.time()` を計算しており、常に巨大な負値を出す。要修正。

---

## 代替案

### 代替1: MV3 拡張で `window.Hls` を document_start にフックし、復号済みプレイリストを横取りする

gaia が 401/403 で塞がれた場合の第一候補。tl;dv 自身が復号した後の m3u8 を掠め取るので、暗号仕様の変更に強い。

| 項目 | 判定 |
|---|---|
| 全セグメント漏れなく | 取れる（掠め取るのは同じ VOD プレイリスト全体） |
| 実時間再生 | 不要。プレイヤーが初期化されるだけでよい |
| 壊れやすい点 | tl;dv 側のバンドル構造変更（`window.Hls` 代入の消失）、埋め込み/クリップ画面では blob: で渡される |

**なぜ拡張なのか（タイミング問題の確実な解決）**

- ブックマークレットは document_start に置けない。リロードでフックが消える（実測事実8）。
- userscript も駄目。Tampermonkey 公式 Content Script API ドキュメントが、Chrome の既定モードについて明示的に `no real document-start support` と書いている。`UserScripts API Dynamic` に切り替え、かつ chrome://extensions で「ユーザースクリプトを許可」を ON にして初めて成立する（Chrome 138 以降は新規インストールで既定オフ）。条件が多く不安定。
- 静的 `content_scripts` の `run_at: "document_start"` には Chrome 公式の明文保証がある: *"Scripts are injected after any files from css, but before any other DOM is constructed or any other script is run."* しかも developer mode 以外の追加トグルが要らない。

**なぜ setter トラップなのか**

`window.Hls` は tl;dv のアプリコードが `tN=e(Nv()); window.Hls=tN.default` で明示的に代入している（hls.js 自身は UMD の CJS 分岐に入るのでグローバルを触らない）。document_start 時点ではまだ存在しないので、`Object.defineProperty` で setter を仕掛けて代入の瞬間を捕まえる。

また、本体プレイヤーの Hls インスタンスは `C0=(e,t)=>{...let n=new tN.default; n.loadSource(e), n.attachMedia(t)...}` の **useEffect クロージャローカル**で、React fiber からは原理的に到達できない（実測事実7の真因）。だが `window.Hls` と `new tN.default` は同一コンストラクタなので、prototype を先回りで差し替えれば確実に捕まる。

`~/tldv-grab/capture-ext/manifest.json`:

```json
{
  "manifest_version": 3,
  "name": "tldv playlist capture",
  "version": "1.0",
  "permissions": ["storage", "unlimitedStorage"],
  "host_permissions": ["https://*.tldv.io/*"],
  "content_scripts": [{
    "matches": ["https://*.tldv.io/*"],
    "js": ["hook.js"],
    "run_at": "document_start",
    "world": "MAIN",
    "all_frames": true
  }]
}
```

`~/tldv-grab/capture-ext/hook.js`:

```js
// MAIN world / document_start。ページの他の script より前に必ず走る。
// リロードしても拡張が毎回注入するので、フックが消える問題は起きない。
(() => {
  const S = (window.__tldvCap = { playlists: [], log: [] });

  const grab = async (u, via) => {
    if (!u || typeof u !== 'string') return;
    try {
      let text = null;
      if (u.startsWith('data:')) {
        text = atob(u.slice(u.indexOf(',') + 1));           // 主画面はこちら
      } else if (u.startsWith('blob:')) {
        text = await (await fetch(u)).text();               // embed / クリップ / トリム
      } else if (/\.m3u8/.test(u)) {
        text = await (await fetch(u)).text();
      }
      if (!text || !text.includes('#EXTM3U')) return;
      if (S.playlists.some(p => p.text === text)) return;    // リロードでの二重登録を防ぐ
      const segs = text.split('\n').filter(l => l.trim() && !l.startsWith('#'));
      const rec = {
        via, url: u.slice(0, 80), text,
        segments: segs.length,
        endlist: text.includes('#EXT-X-ENDLIST'),
        master: text.includes('#EXT-X-STREAM-INF'),
        signed: /X-Amz-Signature=/.test(text),
        obfuscated: text.split('\n')[1]?.startsWith('#TLDVCONF:') || false,
      };
      S.playlists.push(rec);
      console.log('[tldvCap]', via, rec.segments, 'segments',
                  'endlist=' + rec.endlist, 'signed=' + rec.signed);
    } catch (e) { S.log.push(String(e)); }
  };

  const wrapProto = (K) => {
    if (!K || !K.prototype || K.__tldvWrapped) return K;
    const orig = K.prototype.loadSource;
    if (typeof orig === 'function' && !orig.__tldv) {
      const w = function (url) { grab(url, 'loadSource'); return orig.apply(this, arguments); };
      w.__tldv = 1;
      K.prototype.loadSource = w;
    }
    K.__tldvWrapped = 1;
    S.log.push('Hls prototype wrapped v=' + K.version);
    return K;
  };

  // window.Hls への代入を待ち構える。document_start ならこれで必ず先回りできる
  let real = window.Hls;
  if (real) wrapProto(real);
  Object.defineProperty(window, 'Hls', {
    configurable: true,
    get() { return real; },
    set(K) { real = wrapProto(K); },
  });

  // 保険: 難読化プレイリストの生取得も押さえる（gaia を直接見られる）
  const RF = window.fetch;
  window.fetch = function (i, init) {
    const u = String((i && i.url) || i || '');
    const p = RF.apply(this, arguments);
    if (/gaia\.tldv\.io|\.m3u8/.test(u)) {
      p.then(r => r.clone().text()).then(t => {
        if (t && t.includes('#EXTM3U') && !S.playlists.some(x => x.text === t)) {
          grab('data:text/plain;base64,' + btoa(unescape(encodeURIComponent(t))), 'fetch:' + u.slice(0, 60));
        }
      }).catch(() => {});
    }
    return p;
  };
})();
```

使い方:

1. chrome://extensions → デベロッパーモード → 「パッケージ化されていない拡張機能を読み込む」→ `~/tldv-grab/capture-ext`
2. tl;dv の録画ページを開く（リロードしてよい。何度でも効く）
3. コンソールで確認して取り出す:

```js
__tldvCap.playlists.map(p => [p.via, p.segments, p.endlist, p.signed, p.obfuscated])
copy(__tldvCap.playlists.find(p => p.segments > 1 && !p.master).text)
```

`obfuscated: true` のものは結論セクションの復号器に通す。`false` なら既に復号済みなのでそのまま `pbpaste > decoded.m3u8` して yt-dlp へ。

### 代替2: 倍速 + バッファ追走で MSE の appendBuffer を横取りしてバイト列を取る

プレイリスト系が全部塞がれた場合の最後の手段。**再生されるメディアバイト列そのもの**を取る。

| 項目 | 判定 |
|---|---|
| 全セグメント漏れなく | 条件付き。tfdt による重複排除とギャップ検査を必ず併用すること |
| 実時間再生 | 必要（16倍速 + バッファ端追走で 30分素材が実測 115秒） |
| 壊れやすい点 | 巻き戻しシークで dts 逆行、ABR 混在、MSE クォータ、抽出時の 403MB 天井 |

30分/294MB の合成 HLS で完走を実測済み（1800.03秒、映像54000フレーム、デコードエラー0）。ただし押さえるべき落とし穴が多い。

- **一時停止のまま全部バッファする設定（`maxMaxBufferLength: 36000`）は必ず失敗する。** hls.js のロード目標は「currentTime からの前方 maxBufLen 秒」なので再生位置が動かないと先に進まず、しかも SourceBuffer のクォータに当たると `reduceMaxBufferLength` が働いて 36000 が現バッファ長まで自動縮小され、そこで恒久停止する。45分素材で 950秒（35%）で停止するのを実測。エラーは fatal にならないので無言でハングする。
- 正解は「前方60秒だけバッファし、`backBufferLength: 10` で捨てながら 16倍速で押し流す」。
- **巻き戻しシークが1回でも入ると append 順の素朴な連結は壊れる。** 実測で映像フレームが 3000 → 5200 に膨れ、`non monotonically increasing dts` が 2200行。moof の tfdt を鍵にした重複排除と decode time 昇順ソートが必須。
- 抽出は `String.fromCharCode` の一括 btoa をやめ、8MB ごとのバッチ・ストリーミングにする。V8 の最大文字列長 536,870,888 文字 = バイナリ 403MB で、**超えると例外を投げずに空文字を返す**。1時間の録画は普通に超える。
- 吸い出す前に必ずドライバを停止する。停止しないと末尾フラグメントが重複して dts 警告が出る（実測: 27060 フレーム / 期待 27000）。

構成は代替1と同じ MV3 拡張（MAIN world / document_start）に `MediaSource.prototype.addSourceBuffer` と `SourceBuffer.prototype.appendBuffer` の Proxy を足し、Playwright の `launchPersistentContext`（ログイン済み Chrome プロファイル、`channel: 'chrome'` は H.264/AAC のため必須）から駆動する。完了判定は `video.ended && pending === 0`。

コード一式は `/private/tmp/claude-501/-Users-kurosakiyuto/f69d37ed-6b97-4f96-8710-5f345be52f62/scratchpad/mse-test/` に検証済みのもの（`capture6.js` / `run6.js` / `dedupe.js` / `gapcheck.js`）がある。gaia と代替1が両方死んだときにだけ触ればよい。

---

## 使えなかった案

いずれも実コードまたは実測で否定されたもの。

**1. `watch-page` の `video.source` を直接叩く**
署名クエリが一切付かない素の S3 パス。所有権に関係なく 403 AccessDenied。そもそも webapp のバンドルに `watch-page` という文字列が1件も無く、プレイヤーはこのフィールドを使っていない。`Andrew-Sem/skills` の SKILL.md にも失敗パターンとして明記されている。

**2. `Cramraika/tldv_downloader`（検索上位に出る 20 star のリポジトリ）**
`video.source` を N_m3u8DL-RE / ffmpeg に直渡しする実装で、上記 403 で必ず死ぬ。gaia 対応の PR #12 は 2026-05-25 に未マージのままクローズされており、main は今も壊れたまま。本体を触った最終コミットは 2025-11-15 で、以降の push は依存バンプのみ。

**3. `gw.tldv.io/v1/meetings/{id}/download?format=hls`**
ルートは 401 を返すので実在するが、返却スキーマが `gv=z({url:P()})` = `{url: string}` 一本（policies-Crq_ZMA-.js offset 286811）。全セグメント URL が入る余地が無い。233チャンク全 grep で呼び出し側 0 件の死にコード。現行 UI は gaia の `POST /v1/meetings/{id}/async-download`（クレジットウォレットを invalidate する = 課金ゲート）に置き換わっている。OSS 実績もゼロ。

**4. `hls.js` に「全部バッファさせる」config（`maxMaxBufferLength: 36000`, `maxBufferSize: 6e8`）**
上述の通り MSE クォータで無言停止する。`backBufferLength: 30` は currentTime 起点で後方を捨てる設定なので、currentTime=0 のまま止めている構成では削除対象がゼロで一切機能しない。「quota 対策」として書かれた唯一の設定が原理的に無効。

**5. React fiber から `this.hls` を回収する**
tl;dv の視聴ページは react-player ではない。`C0=(e,t)=>{...let n=new tN.default;...}`（src-Dw3pBLAH.js）の useEffect クロージャローカルで、ref にも state にも props にも入らない。fiber を何階層辿っても到達不能。react-player が使われるのは埋め込みページ・クリップ作成モーダル・トリムモーダル・reels のみ。

**6. `MediaSource` から `Hls` への逆引き（`Error.prepareStackTrace` + `CallSite.getThis()`）**
hls.js の配信物は ES モジュール = 常に strict mode で、`getThis()` は `undefined` を返す。sloppy CJS でしか成立しない。別経路から殴っても「逆引きは不可能」という結論は生き残った。

**7. `Hls.prototype` を後から差し替えれば既存インスタンスにも効く**
実測で偽。稼働中プレイヤーに後から arm しても捕獲 0 件（シーク後・実再生後も 0 件）。生きているインスタンスに `loadSource` / `attachMedia` / `startLoad` は二度と呼ばれないため。捕獲できたのは常に新規 construct のみ。だから代替1では document_start で先回りする構成にしてある。

**8. `chrome.webRequest` での二重取り**
(a) レスポンスボディを読めない（MV3 に `onResponseBody` は無い）ので「バイト列そのもの」は原理的に取得不能。(b) 対応スキームに `data:` が含まれず、完全性を与える唯一の物体である data: URI プレイリストが構造的に見えない。(c) メモリキャッシュから返る要求はイベントに出ない。(d) MV3 SW のサスペンド後にリスナが呼ばれない既知バグがある。

**9. MV3 postMessage リレー拡張の bg.js（初版）**
`state` をメモリに持つだけで起動時の `chrome.storage.local.get` による復元が無く、`persist()` がキーごと上書きする。MV3 SW は 30秒アイドルで停止するため、復帰後の最初の1件で過去の捕獲が全消しになる（実測: 4件中1件しか残らない）。加えて `unlimitedStorage` 未申請で 10MB 上限（実測で強制される）。リレー機構自体は正しいので、rehydrate を足せば救える。

**10. clips / reels の secured playlist 経路**
`gaia /v1/clips/{id}/playlist.m3u8` と `/v1/reels/{id}/playlist.m3u8` は実在する（404 `Playlist not found`）。だが clip はトランスクリプトから切り出した抜粋、reel はその連結で、録画全体を覆う保証が構造的に無い。さらにバンドルの i18n に `Free users can create up to a max. of 4 clips.` があり、Free は clip 4本上限。自作して全体を覆う迂回も成立しない。clip ダウンロード自体も UI 上 Pro ゲート。

**11. userscript の `@run-at document-start`**
Tampermonkey 公式の Content Script API ドキュメントが、既定モードと `UserScripts API` モードの両方について `no real document-start support` と明記している。`UserScripts API Dynamic` + chrome://extensions の「ユーザースクリプトを許可」ON でのみ成立。Violentmonkey も Chrome では MV3 で `chrome.userScripts.register` をナビゲーションごとに動的登録しており、実装者自身がレースを認識している（`lastRegTime` / `lastRegDuration`）。静的 `content_scripts` を使うべき。

**12. `_cap_jwt` ではなく `tldvtoken` クッキーが正しい、という説**
出荷バンドル4本を全 grep して `tldvtoken` は 0 件、`_cap_jwt` は 2 件。`qwadratic/dl-tldv-extension` の `auth.ts` が `COOKIE_NAME = "tldvtoken"` を読んでいるのは事実だが、それは現行 tl;dv には存在しない古い認証方式。あの拡張の認証は今のままでは高確率で機能しない。

---

## 未検証の箇所

正直に列挙する。ここは推測であって実測ではない。

1. **最重要: Free プランの有効な `_cap_jwt` で gaia が HTTP 200 を返すことを、誰も実測していない。** 確認できたのは「ルートが実在し、認証ミドルウェアが動作し、認証失敗時の応答が手元の失敗記録（`raw.m3u8` の 13バイト `invalid token`）と完全一致する」ところまで。200 のレスポンス本文は一度も見ていない。
   論拠としては強い: Free のブラウザで再生できており、その署名付きセグメントと data: URI プレイリストを供給する経路は `dA` → `mr` → `getSecuredMeetingPlaylist` の1本しかない（`videoSource` の代入箇所は src-Dw3pBLAH.js に 21 箇所、フォールバックなし）。だがこれは論理的推論。**結論セクションのコンソールスクリプトを1回叩けば 30秒で確定する。**
   手元の `tldv_grab.py` の docstring にある `verified live 2026-09-02` という記述は、同ディレクトリの `raw.m3u8` が認証失敗の記録である以上、根拠が無い。信用しないこと。

2. **gaia が media playlist を返すか master playlist を返すかが未確定。** CDN 側に `_master.m3u8` が存在する記述があるため、master の可能性が残る。qwadratic / anasty17 / Dweeb1578 の実装はフラットな media playlist 前提で、master だと variant URL をセグメントとみなして壊れたファイルを吐く（検知不能）。上記スクリプトには `#EXT-X-STREAM-INF` 検出を入れてある。

3. **`#TLDVCONF` の第1フィールドの実値と署名の実 TTL。** 出荷コードの命名（`expiresInMs = 第1フィールド * 1000`）から「残り秒数」と読めるが、この値は出荷コード内で一度も消費されておらず、用法から相対/絶対を決定できない。実物を1本取れば即決着する（3600 や 172800 なら相対秒、17xxxxxxxx なら epoch）。TTL は OSS の README ベースで約48時間とされるが未計測。長尺を落とし切れるかはこれ次第。

4. **復号後のセグメント URL がブラウザ外の curl / yt-dlp から通るか。** SigV4 のクエリ署名は通常 Referer を縛らず、参照した実装はすべて素の Python / ffmpeg から取りに行っているので通る見込みが高い。ただし `Andrew-Sem/skills` の SKILL.md が region/IP 制約の可能性に触れている。ブラウザと同一回線から実行するのが安全。

5. **代替1の MV3 拡張を実際の tldv.io 上で走らせていない。** バンドル読解（`window.Hls=tN.default` の実在、`C0` の `new tN.default` が同一コンストラクタであること、`data:` と `blob:` の分岐）に基づく設計で、注入タイミングは Chrome 公式の明文保証に依拠しているが、実機での発火は確認していない。

6. **`gw.tldv.io/v1/meetings/{id}/download?format=hls` に有効な JWT を付けた場合の実レスポンス。** 200 で `{url}` が返るのか 402/403 なのかは未確認。ただし返却スキーマが URL 1本である以上、200 でも目的は達成できない。

7. **`gaia` の無認証アクセス。** 存在しない ID に対して無認証で 404 が返る（401 ではない）ため、認証ミドルウェアを素通りしている。実在 ID なら無認証で通る可能性があるが、実 ID を持っていないため未確認。自分の共有リンクで試すこと。

8. **代替2の MSE 経路は 400MB 超の実データで通していない。** ローカル合成 57MB / 294MB までしか流していない。403MB の抽出天井そのものは実測済みで、バッチ・ストリーミング化すれば原理上は無関係になるはずだが、実データでの確認はしていない。

---

## 手元ファイルで直すべき点

- `~/tldv-grab/tldv_gaia_verify.sh` の JWT 取り出しが `JSON.parse(...).token`。`.token` を削る。
- `~/tldv-grab/tldv_playlist.py` の `int(meta["expires"]) - int(time.time())` は expires を epoch 扱いしており、常に巨大な負値を出して警告が誤作動する。相対秒として扱う。
- `~/tldv-grab/tldv_grab.py` の docstring `verified live 2026-09-02` は根拠が無い。実際に 200 を取ってから書き直す。
- `~/tldv-grab/README.md` の「Cramraika/tldv_downloader はバッチなら妥当」は誤り。推奨から外す。ルート1/ルート2の見出しも入れ替わっている。
- `~/tldv-grab/raw.m3u8`（13バイトの `invalid token`）は削除してよい。