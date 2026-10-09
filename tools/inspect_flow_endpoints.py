"""Export native LFD1 endpoints for visual inspection; not generated-frame proof."""
import argparse
import json
import subprocess
from analyze_dense_flow_merging import read_dump


def main():
    from pathlib import Path
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dump", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    metadata, planes = read_dump(args.dump)
    # No fallback to upscaled half-resolution data.
    previous, current = (planes[n] for n in ("previousFull", "currentFull"))
    args.output.mkdir(parents=True, exist_ok=False)
    for name, (width, height, rgba) in [("previous", previous), ("current", current)]:
        subprocess.run(["/opt/homebrew/bin/ffmpeg", "-v", "error", "-f", "rawvideo",
                        "-pixel_format", "rgba", "-video_size", f"{width}x{height}",
                        "-i", "pipe:0", "-vf", "vflip", "-frames:v", "1",
                        str(args.output / (name + ".png"))], input=rgba, check=True)
    a, b = previous[2], current[2]
    changed = sum(a[i:i+3] != b[i:i+3] for i in range(0, len(a), 4))
    metadata.update(changed_rgb_pixels=changed, generated_frame_included=False)
    (args.output / "metadata.json").write_text(json.dumps(metadata, indent=2)+"\n")
    print(json.dumps(metadata))


if __name__ == "__main__":
    main()
