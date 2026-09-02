#!/usr/bin/env bash
# tl;dv gaia route: fetch -> decode -> PROVE completeness -> download.
#
# Fixes three defects in the naive snippet:
#   1. `curl -sSL -o raw.m3u8` with no status check silently writes the
#      401 body "invalid token" INTO raw.m3u8. Always check the code.
#   2. `head -5` can miss #TLDVCONF. grep for it.
#   3. Fetching the playlist proves nothing. The gates are:
#      segment[0] returns 200, and segment_count*target_duration ~= real duration.
#
# Usage: TLDV_JWT=... MEETING_ID=... ./tldv_gaia_verify.sh [out.mp4]
set -uo pipefail
: "${TLDV_JWT:?set TLDV_JWT (browser console: JSON.parse(localStorage.getItem('_cap_jwt')).token)}"
: "${MEETING_ID:?set MEETING_ID (from tldv.io/app/meetings/<id>)}"
OUT="${1:-out.mp4}"
JWT="${TLDV_JWT#Bearer }"

echo "== 1. watch-page (gw) : get the true duration to check completeness against =="
GW=$(mktemp); GWC=$(curl -sS -o "$GW" -w '%{http_code}' \
  -H "Authorization: Bearer $JWT" \
  "https://gw.tldv.io/v1/meetings/${MEETING_ID}/watch-page?noTranscript=true")
echo "   HTTP $GWC"
DUR=$(python3 -c "
import json,sys
try: d=json.load(open('$GW'))
except Exception: print(''); sys.exit()
v=d.get('video') or {}; m=d.get('meeting') or {}
print(v.get('duration') or m.get('duration') or '')" 2>/dev/null)
echo "   reported duration: ${DUR:-unknown} s"

echo "== 2. gaia playlist (this is the route; video.source is dead) =="
RAW=raw.m3u8
CODE=$(curl -sS -L -o "$RAW" -w '%{http_code}' \
  -H "Authorization: Bearer $JWT" \
  -H 'Accept: application/vnd.apple.mpegurl,*/*' \
  "https://gaia.tldv.io/v1/meetings/${MEETING_ID}/playlist.m3u8")
echo "   HTTP $CODE  ($(wc -c < "$RAW" | tr -d ' ') bytes)"
if [ "$CODE" != 200 ]; then
  echo "   body: $(head -c 200 "$RAW")"
  case "$CODE" in
    401) echo "   -> JWT rejected/expired. Re-copy _cap_jwt (it is short-lived).";;
    403) echo "   -> forbidden: no access to this meeting.";;
    404) echo "   -> meeting id not found.";;
    400) echo "   -> meeting id is not a 24-char hex ObjectId.";;
  esac
  exit 1
fi
grep -q '^#TLDVCONF:' "$RAW" || { echo "   NO #TLDVCONF -- format changed"; head -5 "$RAW"; exit 1; }
grep -m1 '^#TLDVCONF:' "$RAW" | cut -c1-100

echo "== 3. decode =="
python3 /Users/kurosakiyuto/tldv-grab/tldv_playlist.py --url "file://$PWD/$RAW" -o decoded.m3u8 >/dev/null || exit 1

echo "== 4. COMPLETENESS GATE (the actual question) =="
python3 - "$RAW" decoded.m3u8 "${DUR:-0}" <<'PY'
import sys,re
raw=open(sys.argv[1]).read(); dec=open(sys.argv[2]).read(); dur=float(sys.argv[3] or 0)
segs=[l for l in dec.splitlines() if l.strip() and not l.startswith('#')]
extinf=[float(m) for m in re.findall(r'#EXTINF:([\d.]+)',dec)]
covered=sum(extinf)
print(f"   segments           : {len(segs)}")
print(f"   sum(#EXTINF)       : {covered:.1f} s")
print(f"   #EXT-X-ENDLIST     : {'#EXT-X-ENDLIST' in dec}   <- must be True (VOD, not live/partial)")
print(f"   master playlist?   : {'#EXT-X-STREAM-INF' in dec} <- must be False (else decode the variant)")
if dur:
    d=abs(covered-dur)
    print(f"   reported duration  : {dur:.1f} s   delta {d:.1f} s")
    print(f"   COVERAGE           : {'COMPLETE' if d<=5 else 'GAP -- ' + str(round(d,1)) + 's missing'}")
else:
    print("   COVERAGE           : cannot cross-check (no duration from watch-page)")
PY

echo "== 5. does segment[0] actually resolve? (signed-URL gate) =="
SEG=$(grep -m1 -v '^#' decoded.m3u8)
curl -s -o /dev/null -w '   segment HTTP %{http_code}  %{size_download} bytes\n' -r 0-2047 "$SEG"

echo "== 6. download (signed URLs live ~48h; do this now) =="
ffmpeg -hide_banner -loglevel warning -stats \
  -protocol_whitelist file,http,https,tcp,tls -allowed_extensions ALL \
  -i decoded.m3u8 -c copy -bsf:a aac_adtstoasc -movflags +faststart -y "$OUT" \
  && echo "   wrote $OUT ($(du -h "$OUT" | cut -f1))"
