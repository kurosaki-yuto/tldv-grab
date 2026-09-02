# tldv-grab

tl;dv の自分のミーティング録画を mp4 で手元に落とすための道具と、その調査記録。
**フリープランで動くことを狙った構成。**

## 配信の仕組み（実測）

tl;dv のプレイヤーは hls.js に `data:` URI のプレイリストを渡して MSE で再生する。
セグメントは `media-files.tldv.io` 上の TS（2秒刻み）で、それぞれ AWS S3 の署名付きURL。

重要な点が2つある。

1. `gw.tldv.io/v1/meetings/{id}/watch-page` が返す `video.source` は
   **署名が付いていない素のS3パスで、叩くと 403 AccessDenied**。
   これは所有権と無関係（自分がアップした動画でも他人所有の共有録画でも同じ403）。
   このフィールドはプレイヤーが使っていない。
2. 実際の経路は **`gaia.tldv.io/v1/meetings/{id}/playlist.m3u8`**。
   難読化された m3u8 が返り、1行目に `#TLDVCONF:{expires},{shift},{prefix}` が付く。
   `#` 以外の行にシーザー復号 + prefix 付与で、全セグメントの署名付きURLが復元される。

2 が VOD プレイリストなので、**1リクエストで全セグメントが揃う**。
フック不要・シーク不要・実時間再生不要。

## 使い方

### 1. プレイリストを取る

tl;dv の録画ページを開き、DevTools コンソール（`option+cmd+J`）に `console.js` を貼る。

`tldv_<id>.m3u8` が Downloads に落ちる。同時に出る表で以下を確認する。

| 項目 | 期待値 | 外れたとき |
| --- | --- | --- |
| `signed` | true | false は復号失敗（シフトの符号を疑う） |
| `endlist` | true | false は不完全。落としてはいけない |
| `master` | false | true なら variant URL で引き直す |
| `playlist_seconds` | 実尺と数秒以内 | ずれは欠落 |

### 2. mp4 にする

```bash
tldv-grab dl tldv_<id>.m3u8 out.mp4
```

尺を突き合わせて `OK: 尺一致` が出れば完了。

### その他のサブコマンド

```
tldv-grab decode <raw.m3u8> [out.m3u8]   難読化m3u8を復号（ゲート表示つき）
tldv-grab dl     <decoded.m3u8> [out.mp4] ダウンロード＋尺検証
tldv-grab hls    <playlist.m3u8> [out.mp4] 素のm3u8から結合
tldv-grab list / get <id>                公式API（Pro以上が必要）
```

## 罠

`yt-dlp` に `--abort-on-unavailable-fragment` を付けないと、セグメントが1本欠けても
**「100%」と表示して exit 0 を返し、無言で穴の空いた mp4 を出力する**。
`ffprobe` の duration もそれらしい値になるため気づけない。
`tldv-grab dl` は最初からこのフラグを付け、プレイリストの `sum(EXTINF)` と出力尺を
突き合わせて2秒以上ずれたら失敗にする。

## 公式API（参考）

Pro/Business/Enterprise なら小細工は不要。

```
GET https://pasta.tldv.io/v1alpha1/meetings/{id}/download   -> 302 署名付きURL
```

API可否は**閲覧者ではなく録画の主催者のプラン**で決まる。Free の録画は不可。
共有されていても API のエクスポート権は付かない。

## 検証状況

| 項目 | 状態 |
| --- | --- |
| 配信機構の解析 | 実測済み |
| 署名付きセグメントの捕獲（プレイヤー経由） | 実測済み |
| シーザー復号ロジック | 往復一致テスト済み（カンマ入りprefix含む） |
| m3u8 → mp4 結合 | 合成HLSで検証済み |
| **`gaia` エンドポイントへの実アクセス** | **未検証** |
| 実物のダウンロード | **未検証** |

シフトの符号は tl;dv 出荷バンドルの読み取りに基づく。実データ未確認。
復号結果が文字化けする場合は符号が逆なので `rot(l, shift)` を `rot(l, -shift)` にする。

## ファイル

- `console.js` — ブラウザのコンソールに貼る抽出スクリプト（本線）
- `tldv-grab` — 復号・ダウンロード・検証のCLI
- `bookmarklet.js` — 旧方式（fetch/XHRフック）。gaia ルートが使えるなら不要
- `FREE-PLAN-ROUTE.md` — フリープラン経路の調査レポート
- `OSS-video-extractors.md` — ページ内動画抽出OSSの調査レポート（90リポジトリ検証）
- `experimental/` — エージェント生成の未レビューコード

## 関連OSS

同種の実装。いずれも tl;dv のセッショントークンを要求するので、渡す前に中身を読むこと。

- [Cramraika/tldv_downloader](https://github.com/Cramraika/tldv_downloader) — MIT。単一ファイルPython。コード監査済み（通信先は tldv のみ、外部送信なし）
- [qwadratic/dl-tldv-extension](https://github.com/qwadratic/dl-tldv-extension) — ブラウザ拡張。ただし認証が旧方式の `tldvtoken` クッキー依存で、現行では機能しない可能性が高い
- [ofcRS/yt-dlp-tldv](https://github.com/ofcRS/yt-dlp-tldv) — MIT。yt-dlp プラグイン

## 注意

対象は自分のミーティング録画。tl;dv がアプリ内に配布しているチュートリアル動画等は対象外。
有料のダウンロード機能を迂回する経路である点は事実なので、利用規約との兼ね合いは利用者の判断。
共有された他人主催の録画を扱う場合は、他の参加者の認識と録画の取り扱いルールを確認すること。
