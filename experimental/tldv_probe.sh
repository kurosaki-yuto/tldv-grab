#!/usr/bin/env bash
# tl;dv gaia probe: decide in 3 steps whether the Free-plan route is open.
# Usage: TLDV_JWT=... MEETING_ID=... ./tldv_probe.sh
set -u
: "${TLDV_JWT:?set TLDV_JWT}"; : "${MEETING_ID:?set MEETING_ID}"
RAW=raw.m3u8

echo "== step 1: gaia playlist (status written to stderr, body to $RAW) =="
CODE=$(curl -sL -o "$RAW" -w '%{http_code}' \
  "https://gaia.tldv.io/v1/meetings/${MEETING_ID}/playlist.m3u8" \
  -H "Authorization: Bearer ${TLDV_JWT}" \
  -H 'Accept: application/vnd.apple.mpegurl,*/*')
echo "HTTP $CODE  ($(wc -c < "$RAW" | tr -d ' ') bytes)"
[ "$CODE" = 200 ] || { echo "--- body ---"; head -c 400 "$RAW"; echo; exit 1; }
head -3 "$RAW"
grep -q '^#TLDVCONF:' "$RAW" || { echo "NO #TLDVCONF -- format changed"; exit 1; }

echo "== step 2: decode =="
python3 tldv_playlist.py --url unused -o /dev/null 2>/dev/null  # no-op guard
python3 - "$RAW" decoded.m3u8 <<'PY'
import sys,re
raw=open(sys.argv[1]).read()
m=re.search(r'^#TLDVCONF:([^,]*),(\d+),(.+)$',raw,re.M)
if not m: sys.exit("no #TLDVCONF")
exp,shift,base=m.group(1),int(m.group(2)),m.group(3).strip()
def rot(s,n):
    o=[]
    for c in s:
        d=ord(c)
        if 65<=d<=90: o.append(chr((d-65+n)%26+65))
        elif 97<=d<=122: o.append(chr((d-97+n)%26+97))
        else: o.append(c)
    return ''.join(o)
out=[];seg=0
for l in raw.splitlines():
    if l.startswith('#TLDVCONF:'): continue
    if not l.strip() or l.startswith('#'): out.append(l); continue
    d=rot(l.strip(),shift)
    out.append(d if d.startswith(('http://','https://')) else base+d); seg+=1
open(sys.argv[2],'w').write('\n'.join(out)+'\n')
print(f"expires_field={exp} shift={shift} base={base}")
print(f"segments={seg}  endlist={'#EXT-X-ENDLIST' in raw}  master={'#EXT-X-STREAM-INF' in raw}")
PY

echo "== step 3: does segment 1 actually resolve? (this is the real gate) =="
SEG=$(grep -m1 -v '^#' decoded.m3u8)
curl -s -o /dev/null -w 'segment HTTP %{http_code}  %{size_download} bytes\n' -r 0-2047 "$SEG"
echo "$SEG" | head -c 160; echo ' ...'

echo "== step 4: download =="
echo "yt-dlp --enable-file-urls --force-overwrites -N 16 -o out.mp4 \"file://\$PWD/decoded.m3u8\""
