#!/usr/bin/env python3
"""tl;dv gaia route -> complete signed HLS media playlist -> mp4.

Mirrors tl;dv's OWN shipped decoder, read from the live bundle
https://tldv.io/app/assets/src-B6g1f1c2.js  (symbols z9/ene/tne/sne/cne/W9/ine):

  GET https://gaia.tldv.io/v1/meetings/{id}/playlist.m3u8
      Authorization: Bearer <JSON.parse(localStorage._cap_jwt)>
      X-Tldv-Client: tldv-webapp/<ver>

  line[0]                        -> passthrough (#EXTM3U)
  line[1] == "#TLDVCONF:a,b,c"   -> a=expiresInSeconds  b=code(0..25)  c=prefix
                                    (if line[1] is not #TLDVCONF: body is NOT obfuscated)
  every later non-empty non-'#'  -> prefix + caesar_FORWARD(line, code)
  everything else                -> passthrough

Usage:
  python3 tldv_gaia_dl.py <MEETING_ID> --jwt "$TLDV_JWT" -o out.mp4
  python3 tldv_gaia_dl.py --file raw.m3u8 -o out.mp4        # offline decode
  python3 tldv_gaia_dl.py <MEETING_ID> --jwt "$TLDV_JWT" --dump-only
"""
import argparse, json, os, subprocess, sys, urllib.request, urllib.error

GAIA = "https://gaia.tldv.io/v1/meetings/{}/playlist.m3u8"
TAG = "#TLDVCONF:"


def _table(code):
    t = list(range(128))
    for n in range(128):
        if 65 <= n <= 90:
            t[n] = ((n - 65 + code) % 26 + 26) % 26 + 65
        elif 97 <= n <= 122:
            t[n] = ((n - 97 + code) % 26 + 26) % 26 + 97
    return t


def caesar(s, code):
    t = _table(code)
    return "".join(chr(t[ord(c)]) if ord(c) < 128 else c for c in s)


def decode(raw):
    """Exact port of W9()+cne(). Returns (playlist_text, meta)."""
    lines = raw.split("\n")
    if len(lines) < 2:
        raise SystemExit("premature end of playlist")
    if not lines[1].startswith(TAG):
        return raw, {"obfuscated": False}
    parts = lines[1][len(TAG):].split(",")
    if len(parts) < 3:
        raise SystemExit("invalid TLDV tag")
    expires_s, code = int(parts[0]), int(parts[1])
    prefix = ",".join(parts[2:])
    if not 0 <= code <= 25:
        raise SystemExit("code out of range: %d" % code)
    out, nseg = [lines[0]], 0
    for l in lines[2:]:
        if l and not l.startswith("#"):
            out.append(prefix + caesar(l, code)); nseg += 1
        else:
            out.append(l)
    body = "\n".join(out)
    return body, {"obfuscated": True, "expires_in_sec": expires_s, "code": code,
                  "prefix": prefix, "segments": nseg,
                  "master": "#EXT-X-STREAM-INF" in body,
                  "endlist": "#EXT-X-ENDLIST" in body,
                  "signed": "X-Amz-Signature" in body}


def fetch(url, jwt=None):
    h = {"User-Agent": "Mozilla/5.0",
         "X-Tldv-Client": "tldv-webapp/1.0.0",
         "Accept": "application/vnd.apple.mpegurl,*/*"}
    if jwt:
        h["Authorization"] = "Bearer " + jwt
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=60) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        body = e.read()[:300].decode("utf-8", "replace")
        hint = {401: "token rejected. Re-copy: JSON.parse(localStorage._cap_jwt)  (a plain string, NOT .token)",
                404: "404 'Meeting not found' is ALSO the no-token response. Check the JWT.",
                403: "no access to this meeting"}.get(e.code, "")
        raise SystemExit("HTTP %d: %s\n%s" % (e.code, body, hint))


def audit(meta, text):
    """Prove completeness before downloading anything."""
    prob = []
    if meta.get("obfuscated"):
        if not meta["signed"]:
            prob.append("no X-Amz-Signature after decode -> wrong code/prefix")
        if not meta["endlist"]:
            prob.append("no #EXT-X-ENDLIST -> playlist is partial or live")
        if meta["master"]:
            prob.append("MASTER playlist -> re-run on the variant URL printed above")
        left = meta["expires_in_sec"]
        if left < 900:
            prob.append("signed URLs valid only %ds -> refetch immediately" % left)
    dur = sum(float(l[8:].rstrip(",")) for l in text.split("\n")
              if l.startswith("#EXTINF:") and l[8:].rstrip(",").replace(".", "", 1).isdigit())
    meta["total_seconds"] = round(dur, 1)
    return prob


def main():
    p = argparse.ArgumentParser()
    p.add_argument("meeting_id", nargs="?")
    p.add_argument("--jwt")
    p.add_argument("--file", help="decode a already-saved raw playlist instead of fetching")
    p.add_argument("--dump-only", action="store_true")
    p.add_argument("-o", "--output", default="out.mp4")
    a = p.parse_args()

    if a.file:
        raw = open(a.file, encoding="utf-8", errors="replace").read()
    elif a.meeting_id:
        if not a.jwt or a.jwt.count(".") != 2 or a.jwt.startswith('"'):
            raise SystemExit("--jwt must be the bare 3-part JWT (no quotes). "
                             "Get it with: JSON.parse(localStorage._cap_jwt)")
        raw = fetch(GAIA.format(a.meeting_id), a.jwt)
    else:
        raise SystemExit("give a MEETING_ID (with --jwt) or --file")

    text, meta = decode(raw)
    problems = audit(meta, text)
    m3u8 = os.path.splitext(a.output)[0] + ".m3u8"
    open(m3u8, "w").write(text if text.endswith("\n") else text + "\n")
    print(json.dumps(meta, indent=2), file=sys.stderr)
    for pr in problems:
        print("PROBLEM: " + pr, file=sys.stderr)
    print(m3u8)
    if a.dump_only:
        return
    if problems:
        raise SystemExit("refusing to download until the problems above are resolved")
    subprocess.run(["ffmpeg", "-y", "-allowed_extensions", "ALL",
                    "-protocol_whitelist", "file,http,https,tcp,tls,crypto",
                    "-i", m3u8, "-c", "copy", "-bsf:a", "aac_adtstoasc",
                    a.output], check=True)
    print(a.output)


if __name__ == "__main__":
    main()
