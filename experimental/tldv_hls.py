#!/usr/bin/env python3
"""tl;dv gaia playlist -> real HLS media playlist.

Mirrors the shipped client decoder exactly (src-B6g1f1c2.js: z9/tne/sne/cne/W9).
  #TLDVCONF:<expiresInSeconds>,<code 0..25>,<prefix>
  every non-'#', non-empty line -> prefix + caesar_forward(line, code)
"""
import argparse, json, re, sys, urllib.request, urllib.error

GAIA = "https://gaia.tldv.io/v1/meetings/{}/playlist.m3u8"
TAG = "#TLDVCONF:"


def table(code):                      # == z9(e)
    t = list(range(128))
    for n in range(128):
        if 65 <= n <= 90:   t[n] = ((n - 65 + code) % 26 + 26) % 26 + 65
        elif 97 <= n <= 122: t[n] = ((n - 97 + code) % 26 + 26) % 26 + 97
    return t


def shift(s, code):                   # == tne(e,t)
    t = table(code)
    return "".join(chr(t[ord(c)]) if ord(c) < 128 else c for c in s)


def parse_conf(line):                 # == sne(e)
    parts = line[len(TAG):].split(",")
    if len(parts) < 3:
        raise ValueError("malformed #TLDVCONF")
    expires_s, code_s, prefix = parts[0], parts[1], ",".join(parts[2:])
    code = int(code_s)
    if not 0 <= code <= 25:
        raise ValueError(f"code out of range: {code}")
    return int(expires_s), code, prefix


def decode(raw):                      # == W9(e) + cne(...)
    lines = raw.split("\n")
    if len(lines) < 2:
        raise ValueError("premature end of playlist")
    if not lines[1].startswith(TAG):
        return raw, {"obfuscated": False}          # already plain -> passthrough
    expires, code, prefix = parse_conf(lines[1])
    out, n = [lines[0]], 0
    for l in lines[2:]:
        if l and not l.startswith("#"):
            out.append(prefix + shift(l, code)); n += 1
        else:
            out.append(l)
    body = "\n".join(out)
    return body, {"obfuscated": True, "expires_in_sec": expires, "code": code,
                  "prefix": prefix, "segments": n,
                  "master": "#EXT-X-STREAM-INF" in body,
                  "endlist": "#EXT-X-ENDLIST" in body,
                  "signed": "X-Amz-Signature" in body}


def fetch(mid, jwt):
    req = urllib.request.Request(GAIA.format(mid), headers={
        "Authorization": "Bearer " + jwt,
        "X-Tldv-Client": "tldv-webapp/1.0.0",
        "Accept": "application/vnd.apple.mpegurl,*/*",
        "User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("meeting_id")
    p.add_argument("--jwt", required=True, help="JSON.parse(localStorage._cap_jwt)  (NOT .token)")
    p.add_argument("-o", "--output", default="decoded.m3u8")
    a = p.parse_args()
    if a.jwt.startswith('"') or a.jwt.count(".") != 2:
        sys.exit("jwt looks wrong: pass the bare 3-part JWT, no quotes")
    try:
        raw = fetch(a.meeting_id, a.jwt)
    except urllib.error.HTTPError as e:
        body = e.read()[:200].decode("utf-8", "replace")
        hint = {401: "token expired/malformed - re-copy it",
                404: "404 'Meeting not found' is ALSO the no-auth response - check the token",
                403: "no access to this meeting"}.get(e.code, "")
        sys.exit(f"gaia HTTP {e.code}: {body}\n{hint}")
    body, meta = decode(raw)
    open(a.output, "w").write(body if body.endswith("\n") else body + "\n")
    print(json.dumps(meta), file=sys.stderr)
    if meta.get("master"):
        print("WARNING: master playlist - rerun ffmpeg on a variant URL", file=sys.stderr)
    if meta.get("obfuscated") and not meta.get("signed"):
        print("WARNING: no X-Amz-Signature after decode - wrong code/prefix", file=sys.stderr)
    print(a.output)


if __name__ == "__main__":
    main()
