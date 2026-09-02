#!/usr/bin/env python3
"""tl;dv: fetch the wrapper playlist, ROT-decode it, emit a real HLS media playlist.

Verified against 5 independent OSS implementations (see NOTES at bottom).
Usage:
  python3 tldv_playlist.py <MEETING_ID> --jwt "$TLDV_JWT" -o decoded.m3u8
  python3 tldv_playlist.py --url "https://puttanesca-v0.tldv.io/v1/playlist.m3u8?t=..." -o decoded.m3u8
"""
import argparse, re, sys, time, urllib.request, urllib.error

TLDVCONF_RE = re.compile(r"^#TLDVCONF:([^,]+),([^,]+),(.+)$")
GAIA = "https://gaia.tldv.io/v1/meetings/{}/playlist.m3u8"


def rot(text, shift):
    out = []
    for ch in text:
        c = ord(ch)
        if 65 <= c <= 90:
            out.append(chr((c - 65 + shift) % 26 + 65))
        elif 97 <= c <= 122:
            out.append(chr((c - 97 + shift) % 26 + 97))
        else:
            out.append(ch)          # digits and ? & = - . / % _ untouched
    return "".join(out)


def fetch(url, jwt=None, timeout=30):
    h = {"User-Agent": "Mozilla/5.0",
         "Accept": "application/vnd.apple.mpegurl,application/x-mpegURL,*/*"}
    if jwt:
        h["Authorization"] = "Bearer " + jwt
    req = urllib.request.Request(url, headers=h)   # urlopen follows gaia -> puttanesca redirect
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace"), r.geturl()


def decode_playlist(raw):
    base_url, shift, expires, out, nseg = "", 0, "", [], 0
    for line in raw.splitlines():
        m = TLDVCONF_RE.match(line)
        if m:
            expires, shift_s, base_url = m.groups()
            shift = int(shift_s)
            continue                                  # drop the TLDVCONF line
        if not line.strip() or line.startswith("#"):
            out.append(line)                          # HLS tags pass through
            continue
        d = rot(line.strip(), shift)
        out.append(d if d.startswith(("http://", "https://")) else base_url + d)
        nseg += 1
    if not base_url:
        raise SystemExit("no #TLDVCONF line - not a tl;dv obfuscated playlist")
    return "\n".join(out) + "\n", {"expires": expires, "shift": shift,
                                   "base_url": base_url, "segments": nseg}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("meeting_id", nargs="?")
    p.add_argument("--url", help="wrapper playlist URL copied from the Network tab")
    p.add_argument("--jwt", help="localStorage._cap_jwt token (needed for the gaia route)")
    p.add_argument("-o", "--output", default="decoded.m3u8")
    a = p.parse_args()

    if a.url:
        src, jwt = a.url, None
    elif a.meeting_id:
        src, jwt = GAIA.format(a.meeting_id), a.jwt
    else:
        raise SystemExit("give a MEETING_ID or --url")

    try:
        raw, final = fetch(src, jwt)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"playlist fetch failed: HTTP {e.code} {e.reason}\n{e.read()[:300]!r}")
    print(f"fetched: {final}", file=sys.stderr)

    decoded, meta = decode_playlist(raw)

    # gap-prevention checks
    if "#EXT-X-STREAM-INF" in decoded:
        print("WARNING: master playlist - re-run this script on the variant URL below", file=sys.stderr)
    if not decoded.rstrip().endswith("#EXT-X-ENDLIST") and "#EXT-X-ENDLIST" not in decoded:
        print("WARNING: no #EXT-X-ENDLIST - playlist may be partial/live", file=sys.stderr)
    try:
        left = int(meta["expires"]) - int(time.time())
        meta["expires_in_sec"] = left
        if left < 600:
            print(f"WARNING: signed URLs expire in {left}s - refetch before downloading", file=sys.stderr)
    except ValueError:
        pass

    with open(a.output, "w") as f:
        f.write(decoded)
    print(meta, file=sys.stderr)
    print(a.output)


if __name__ == "__main__":
    main()
