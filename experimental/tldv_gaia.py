#!/usr/bin/env python3
"""
tl;dv gaia playlist grabber.
出典: Cramraika/tldv_downloader PR #12 (nicolamazz, 未マージ) + Andrew-Sem/skills SKILL.md
検証状況: Caesar デコーダは手計算で検証済み。gaia が Free プラン JWT を受けるかは未検証。
使い方:
  python3 tldv_gaia.py probe   <meeting_id> <jwt>   # gaia のステータスだけ見る(安全)
  python3 tldv_gaia.py dump    <meeting_id> <jwt>   # 復号済み m3u8 を標準出力
  python3 tldv_gaia.py fetch   <meeting_id> <jwt> <out.mp4>
"""
import sys, subprocess, tempfile, urllib.request, urllib.error
from pathlib import Path

GAIA = "https://gaia.tldv.io"

def _shift(text, n):
    out = []
    for ch in text:
        if 'a' <= ch <= 'z':
            out.append(chr((ord(ch) - ord('a') + n) % 26 + ord('a')))
        elif 'A' <= ch <= 'Z':
            out.append(chr((ord(ch) - ord('A') + n) % 26 + ord('A')))
        else:
            out.append(ch)
    return ''.join(out)

def _get(url, jwt):
    if not jwt.lower().startswith('bearer '):
        jwt = 'Bearer ' + jwt
    req = urllib.request.Request(url, headers={
        'Authorization': jwt,
        'Accept': 'application/vnd.apple.mpegurl,*/*',
        'User-Agent': 'Mozilla/5.0',
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, r.geturl(), r.read().decode('utf-8', 'replace')

def raw_playlist(mid, jwt):
    return _get(f"{GAIA}/v1/meetings/{mid}/playlist.m3u8", jwt)

def decode(raw):
    prefix, n, out = "", 0, ["#EXTM3U"]
    seen_conf = False
    for line in raw.splitlines():
        if line.startswith("#TLDVCONF:"):
            parts = line[len("#TLDVCONF:"):].split(",", 2)
            if len(parts) >= 3:
                try: n = int(parts[1])
                except ValueError: n = 0
                prefix = parts[2]; seen_conf = True
            continue
        if line.startswith("#EXTM3U"):
            continue
        if line.startswith("#") or not line.strip():
            out.append(line)
        else:
            out.append(prefix + _shift(line, n))
    if not seen_conf:
        raise SystemExit("ERR: #TLDVCONF ヘッダなし。形式が変わったか、これは master playlist の可能性")
    return "\n".join(out) + "\n", n, prefix

def main():
    if len(sys.argv) < 4: raise SystemExit(__doc__)
    mode, mid, jwt = sys.argv[1], sys.argv[2], sys.argv[3]
    try:
        status, final, raw = raw_playlist(mid, jwt)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"gaia HTTP {e.code}: {e.read()[:400]!r}")
    if mode == "probe":
        print(f"status={status}\nfinal_url={final}\nbytes={len(raw)}")
        print("--- head ---"); print("\n".join(raw.splitlines()[:8])); return
    pl, n, prefix = decode(raw)
    segs = [l for l in pl.splitlines() if l and not l.startswith('#')]
    print(f"# shift={n} prefix={prefix} segments={len(segs)}", file=sys.stderr)
    if mode == "dump":
        print(pl); return
    out = Path(sys.argv[4])
    with tempfile.NamedTemporaryFile('w', suffix='.m3u8', delete=False, encoding='utf-8') as t:
        t.write(pl); tmp = t.name
    try:
        subprocess.run(['ffmpeg','-protocol_whitelist','file,http,https,tcp,tls',
                        '-allowed_extensions','ALL','-i',tmp,'-c','copy',
                        '-bsf:a','aac_adtstoasc','-y',str(out)], check=True)
    finally:
        Path(tmp).unlink(missing_ok=True)

if __name__ == "__main__":
    main()
