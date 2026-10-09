#!/usr/bin/env bash
# Regenerate the silent six-second boot loop from the imagegen artwork.
set -euo pipefail
ASSET_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$ASSET_DIR/../.." && pwd)"
FFMPEG="${FFMPEG:-ffmpeg}"
OUTPUT="${1:-$PROJECT_DIR/loading.mp4}"

# Oversample before zoompan so its integer source-pixel rounding is subpixel
# at delivery resolution. The periodic cosine has no jump at the loop seam.
# Fit/pad instead of stretching the slightly non-16:9 generated source.
"$FFMPEG" -hide_banner -y -loop 1 -framerate 60 \
  -i "$ASSET_DIR/scene.png" \
  -vf "scale=3840:2160:force_original_aspect_ratio=decrease:flags=lanczos,pad=3840:2160:(ow-iw)/2:(oh-ih)/2,setsar=1,zoompan=z='1.005+0.0125*(1-cos(2*PI*on/360))':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s=1920x1080:fps=60,format=yuv420p" \
  -frames:v 360 -an -c:v libx264 -preset medium -crf 19 \
  -profile:v high -level:v 4.2 -maxrate 8M -bufsize 16M \
  -g 120 -keyint_min 120 -sc_threshold 0 -movflags +faststart \
  "$OUTPUT"
