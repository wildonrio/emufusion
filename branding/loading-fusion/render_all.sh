#!/bin/zsh
# Render the loop in parallel lossless segments, then encode ../../loading.mp4.
set -euo pipefail
here=${0:A:h}
work=${TMPDIR:-/tmp}/emufusion-loading-$$
mkdir -p "$work"
trap 'rm -rf "$work"' EXIT
frames=360 workers=${WORKERS:-6}
per=$(( (frames + workers - 1) / workers ))
for i in $(seq 0 $((workers - 1))); do
  start=$(( i * per )); stop=$(( start + per > frames ? frames : start + per ))
  ${PYTHON:-/opt/homebrew/bin/python3} "$here/render.py" "$work/seg$i.mkv" $start $stop &
done
wait
for i in $(seq 0 $((workers - 1))); do echo "file '$work/seg$i.mkv'"; done > "$work/list.txt"
ffmpeg -hide_banner -loglevel error -y -f concat -safe 0 -i "$work/list.txt" \
  -frames:v $frames -an -c:v libx264 -preset slow -crf 17 -tune grain \
  -profile:v high -level:v 4.2 -maxrate 14M -bufsize 28M -g 120 -keyint_min 120 \
  -sc_threshold 0 -pix_fmt yuv420p -movflags +faststart "${1:-$here/../../loading.mp4}"
echo "wrote ${1:-$here/../../loading.mp4}"
