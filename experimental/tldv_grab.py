#!/usr/bin/env python3
"""
tl;dv full-recording grabber (Free plan, no official API).

Path (verified live 2026-09-02):
  GET https://gaia.tldv.io/v1/meetings/{id}/playlist.m3u8   Authorization: Bearer <jwt>
    -> 302 -> https://puttanesca-v0.tldv.io/v1/playlist.m3u8?t=<temp jwt>
    -> m3u8 whose body starts with  #TLDVCONF:<expires>,<shift>,<base-url>
       and whose segment lines are Caesar-rotated (letters only, +shift).
       e.g. shift=8:  ".lk" -> ".ts" ,  "P-Ser-" -> "X-Amz-"
    -> decoded line = base-url + rot(line, shift)  -> signed media-files.tldv.io/*.ts

Usage:
  python3 tldv_grab.py <meeting-url-or-id> <jwt>
  python3 tldv_grab.py <meeting-url-or-id> <jwt> --probe     # playlist only, no download
"""
import os, re, sys, json, subprocess, tempfile, shutil
from concurrent.futures import ThreadPoolExecutor
import urllib.request, urllib.error

GAIA = "https://gaia.tldv.io/v1/meetings/{}/playlist.m3u8"
GW   = "https://gw.tldv.io/v1/meetings/{}/watch-page?noTranscript=true"
UA   = "Mozilla/5.0"


def rot(text, shift):
    out = []
    for ch in text:
        c = ord(ch)
        if 65 <= c <= 90:
            out.append(chr((c - 65 + shift) % 26 + 65))
        elif 97 <= c <= 122:
            out.append(chr((c - 97 + shift) % 26 + 97))
        else:
            out.append(ch)
    return "".join(out)


def get(url, token=None, accept=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    if token:
        req.add_header("Authorization", "Bearer " + token)
    if accept:
        req.add_header("Accept", accept)
    with urllib.request.urlopen(req, timeout=30) as r:   # follows redirects
        return r.read(), r.status, r.geturl()


def parse_playlist(raw):
    """Return (segment_urls, conf, stats). Raises if not a tl;dv obfuscated playlist."""
    conf = None
    segs = []
    extinf = 0
    endlist = False
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#TLDVCONF:"):
            rest = line[len("#TLDVCONF:"):]
            i = rest.find(",")
            j = rest.find(",", i + 1)
            if i == -1 or j == -1:
                raise ValueError("malformed #TLDVCONF: " + line)
            conf = {"expires": rest[:i], "shift": int(rest[i + 1:j]), "base": rest[j + 1:]}
            continue
        if line.startswith("#EXTINF"):
            extinf += 1
            continue
        if line.startswith("#EXT-X-ENDLIST"):
            endlist = True
            continue
        if line.startswith("#"):
            continue
        if conf is None:
            raise ValueError("segment line before #TLDVCONF")
        d = rot(line, conf["shift"])
        segs.append(d if d.startswith(("http://", "https://")) else conf["base"] + d)
    if conf is None:
        raise ValueError("no #TLDVCONF header - not a tl;dv obfuscated playlist")
    return segs, conf, {"extinf": extinf, "endlist": endlist}


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    mid = sys.argv[1].split("?")[0].rstrip("/").split("/")[-1]
    token = sys.argv[2].strip()
    if token.startswith("Bearer "):
        token = token[7:]
    probe = "--probe" in sys.argv

    name = mid
    try:
        body, _, _ = get(GW.format(mid), token, "application/json")
        meta = json.loads(body)
        name = (meta.get("meeting") or {}).get("name") or mid
        print("meeting: %s" % name)
    except Exception as e:
        print("watch-page metadata failed (%s) - continuing with id as name" % e)

    try:
        raw, status, final = get(GAIA.format(mid), token,
                                 "application/vnd.apple.mpegurl,application/x-mpegURL,*/*")
    except urllib.error.HTTPError as e:
        print("PLAYLIST FAILED: HTTP %s  %s" % (e.code, e.read()[:200]))
        sys.exit(1)
    raw = raw.decode("utf-8", "replace")
    print("playlist: HTTP %s  final-url=%s  bytes=%d" % (status, final, len(raw)))

    segs, conf, st = parse_playlist(raw)
    print("TLDVCONF: expires=%s shift=%s base=%s" % (conf["expires"], conf["shift"], conf["base"]))
    print("segments=%d  #EXTINF=%d  ENDLIST=%s" % (len(segs), st["extinf"], st["endlist"]))
    if not st["endlist"]:
        print("WARNING: no #EXT-X-ENDLIST - playlist may be live/partial, NOT a complete VOD")
    if st["extinf"] != len(segs):
        print("WARNING: #EXTINF count != segment count (%d vs %d)" % (st["extinf"], len(segs)))
    print("first: %s" % segs[0][:160])
    print("last : %s" % segs[-1][:160])
    if probe:
        return

    safe = re.sub(r'[\\/*?:"<>|]', "", name).strip().replace(" ", "_") or mid
    tmp = tempfile.mkdtemp(prefix="tldv_")
    done = [0]

    def fetch(i_url):
        i, url = i_url
        for attempt in range(3):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA})  # no auth: presigned
                with urllib.request.urlopen(req, timeout=60) as r:
                    data = r.read()
                with open(os.path.join(tmp, "s%06d.ts" % i), "wb") as f:
                    f.write(data)
                done[0] += 1
                if done[0] % 25 == 0 or done[0] == len(segs):
                    print("\r  %d/%d" % (done[0], len(segs)), end="", flush=True)
                return None
            except Exception as e:
                if attempt == 2:
                    return (i, str(e))
        return None

    with ThreadPoolExecutor(max_workers=6) as ex:
        errs = [e for e in ex.map(fetch, enumerate(segs)) if e]
    print()
    if errs:
        print("FAILED %d/%d segments. First few: %s" % (len(errs), len(segs), errs[:3]))
        print("403 => playlist expired (expires=%s). Re-run for a fresh one." % conf["expires"])
        sys.exit(1)

    ts = safe + ".ts"
    with open(ts, "wb") as out:
        for i in range(len(segs)):
            p = os.path.join(tmp, "s%06d.ts" % i)
            if not os.path.exists(p):
                print("MISSING segment %d - aborting (incomplete)" % i)
                sys.exit(1)
            with open(p, "rb") as f:
                shutil.copyfileobj(f, out)
    shutil.rmtree(tmp, ignore_errors=True)

    mp4 = safe + ".mp4"
    r = subprocess.run(["ffmpeg", "-y", "-i", ts, "-c", "copy", "-movflags", "+faststart", mp4],
                       capture_output=True)
    if r.returncode != 0:
        print("ffmpeg failed:\n" + r.stderr.decode()[-1500:])
        print("raw concatenated stream kept at: " + os.path.abspath(ts))
        sys.exit(1)
    os.remove(ts)
    print("OK -> %s (%.1f MB)" % (os.path.abspath(mp4), os.path.getsize(mp4) / 1e6))


if __name__ == "__main__":
    main()
