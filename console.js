// tl;dv 録画抽出 — 録画ページを開いた状態で DevTools コンソール(option+cmd+J)に貼る
// フリープラン可。フック不要・シーク不要・実時間再生不要。API 1発。
(async () => {
  // 1. JWT。_cap_jwt は JSON エンコードされた「文字列」。.token は存在しない
  const rawJwt = localStorage.getItem('_cap_jwt');
  let jwt;
  try { jwt = JSON.parse(rawJwt); } catch { jwt = rawJwt; }
  if (typeof jwt !== 'string' || !jwt) throw new Error('_cap_jwt を文字列として取得できない。ログインし直して再実行');

  // 2. meetingId (24桁hex)
  const id = (location.href.match(/[0-9a-f]{24}/i) || [])[0];
  if (!id) throw new Error('URLからmeetingIdを取れない。/app/meetings/<id> を開いて実行する');

  // 3. 難読化プレイリスト取得
  const res = await fetch(`https://gaia.tldv.io/v1/meetings/${id}/playlist.m3u8`, {
    headers: { 'Authorization': 'Bearer ' + jwt, 'Accept': 'application/vnd.apple.mpegurl,*/*' },
  });
  const raw = await res.text();
  console.log('HTTP', res.status, '| bytes', raw.length);
  if (!res.ok) { console.error(raw.slice(0, 300)); return; }

  // 4. シーザー復号
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
    const p = lines[1].slice('#TLDVCONF:'.length).split(',');
    const shift = Number(p[1]), prefix = p.slice(2).join(',');   // prefix に , が入りうる
    if (!(shift >= 0 && shift <= 25)) throw new Error('shift 範囲外: ' + shift);
    conf = { expiresSec: Number(p[0]), shift, prefix };
    const out = [lines[0]];
    for (const l of lines.slice(2)) out.push(l && !l.startsWith('#') ? prefix + rot(l, shift) : l);
    playlist = out.join('\n');
  } else { playlist = raw; console.warn('#TLDVCONF なし。素のm3u8として扱う'); }

  // 5. 完全性ゲート — ここが「漏れなく取れたか」の唯一の機械的証明
  const segs   = playlist.split('\n').filter(l => l.trim() && !l.startsWith('#'));
  const extinf = [...playlist.matchAll(/#EXTINF:([\d.]+)/g)].map(m => parseFloat(m[1]));
  const sum    = extinf.reduce((a, b) => a + b, 0);
  const v = document.querySelector('video');
  console.table({
    shift: conf && conf.shift,
    segments: segs.length,
    playlist_seconds: +sum.toFixed(1),
    video_duration: v && isFinite(v.duration) ? +v.duration.toFixed(1) : null,
    signed:  /X-Amz-Signature=/.test(playlist),   // false → 復号失敗
    endlist: playlist.includes('#EXT-X-ENDLIST'), // false → 不完全。落とすな
    master:  playlist.includes('#EXT-X-STREAM-INF'), // true → variantで引き直す
  });

  // 6. decoded.m3u8 を保存
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([playlist], { type: 'application/vnd.apple.mpegurl' }));
  a.download = `tldv_${id}.m3u8`;
  document.body.appendChild(a); a.click(); a.remove();

  window.__tldv = { raw, playlist, conf };
  console.log('保存した。signed/endlist が true、master が false、秒数が一致していればOK');
})();
