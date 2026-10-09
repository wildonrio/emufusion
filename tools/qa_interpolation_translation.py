"""Run production shader against a known-motion midpoint on the host GPU.

Only GLSL dialect is changed (ES precision -> desktop GLSL120). No interpolation
logic is reimplemented. Nonzero means the synthetic/endpoint image is wrong.
This is not Android GPU timing or actual-game image acceptance.
"""
import ast
from pathlib import Path
import re
import subprocess
import tempfile
import argparse
import os

parser = argparse.ArgumentParser()
parser.add_argument("--transport-prototype", action="store_true",
                    help="Experimental GPU forward transport; NOT the deployed production pipeline")
parser.add_argument("--disable-hud-diagnostic", action="store_true",
                    help="Diagnostic only: isolate HUD hold contribution; never acceptance")
args = parser.parse_args()

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java").read_text()
block = source.split("private static final String MOTION_INTERPOLATE_SHADER =", 1)[1]
block = block.split("private static final String MOTION_PREDICTION_PROOF_SHADER", 1)[0]
# Remove comments first: comments themselves contain quoted historical examples.
block = re.sub(r"//[^\n]*", "", block)
shader = "".join(ast.literal_eval(s) for s in re.findall(r'"(?:[^"\\]|\\.)*"', block))
assert shader.count("void main()") == 1 and shader.rstrip().endswith("}")
shader = "#version 120\n" + shader.replace("precision highp float;", "")
if args.transport_prototype:
    shared = ROOT / "unified-android/src/com/thorium/preview/game/DenseMotionSynthesisShader.java"
    shared_source = shared.read_text()
    controls = {}
    for name in ("LAYER_CORRECTION", "HOLE_CORRECTION"):
        literal = re.search(r"static final String " + name + r' = ("(?:[^"\\]|\\.)*");', shared_source).group(1)
        controls[name] = ast.literal_eval(literal)
    layer_correction = controls["LAYER_CORRECTION"]
    hole_correction = controls["HOLE_CORRECTION"]
    java = Path("/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home/bin")
    with tempfile.TemporaryDirectory(prefix="emufusion-synthesis-java-") as build:
        base = Path(build) / "base.glsl"
        base.write_text(shader)
        subprocess.run([str(java / "javac"), "-d", build, str(shared),
                        str(ROOT / "tools/qa/DenseMotionSynthesisShaderDump.java")], check=True)
        shader = subprocess.run([str(java / "java"), "-cp", build,
                                 "com.thorium.preview.game.DenseMotionSynthesisShaderDump", str(base)],
                                check=True, capture_output=True, text=True).stdout
    print("EXPERIMENTAL SHARED JAVA SYNTHESIS/TRANSPORT: not Android acceptance.", flush=True)
if args.disable_hud_diagnostic:
    assert args.transport_prototype, "HUD diagnostic requires transport prototype"
    token = "predictionAdmission*(1.0-staticHud)"
    assert shader.count(token) == 1
    shader = shader.replace(token, "predictionAdmission")
    print("DIAGNOSTIC ONLY: HUD protection disabled; not a candidate fix.", flush=True)
with tempfile.TemporaryDirectory(prefix="emufusion-interpolation-") as directory:
    directory = Path(directory)
    transport_source = (ROOT / "unified-android/src/com/thorium/preview/game/DenseMotionTransportShaders.java").read_text()
    for name in ("VERTEX", "CLASSIFY", "FRAGMENT"):
        part = transport_source.split("static final String " + name + " =", 1)[1]
        part = part.split("static final String", 1)[0]
        part = re.sub(r"//[^\n]*", "", part)
        glsl = "".join(ast.literal_eval(s) for s in re.findall(r'"(?:[^"\\]|\\.)*"', part))
        glsl = "#version 120\n" + glsl.replace("precision highp float;", "")
        path = directory / (name.lower() + ".glsl")
        path.write_text(glsl)
        os.environ["EMUFUSION_TRANSPORT_" + name] = str(path)
    fragment = directory / "interpolation.glsl"
    fragment.write_text(shader)
    binary = directory / "runner"
    subprocess.run(["clang", "-Wno-deprecated-declarations", "-framework", "OpenGL",
                    str(ROOT / "tools/qa_interpolation_translation.c"), "-o", str(binary)], check=True)
    cases = [[direction, str(contrast), domain]
             for domain in ("global", "local") for contrast in (255, 8)
             for direction in ("forward", "reverse")]
    cases += [[direction, "255", "scrolling"] for direction in ("forward", "reverse")]
    cases += [[direction, "255", "fast-background"] for direction in ("forward", "reverse")]
    cases += [[direction, "255", "opposed-background"] for direction in ("forward", "reverse")]
    results = [subprocess.run([str(binary), str(fragment), *case,
                              *(["transport"] if args.transport_prototype else [])]).returncode
               for case in cases]
    # Remove only the correction to demonstrate that the image assertions
    # actually detect the production bug (GL/compile errors are not a pass).
    correction = " staticHud*=1.0-confirmedCrossing;\n"
    assert shader.count(correction) == 1
    fragment.write_text(shader.replace(correction, ""))
    # Isolate the HUD defect from the independently tested input-quantization
    # failure; this control deliberately exercises the old, untransported path.
    control = subprocess.run([str(binary), str(fragment)], capture_output=True, text=True,
                             env={k: v for k, v in os.environ.items() if k != "EMUFUSION_QA_RGBA8_INPUT"})
    if not args.disable_hud_diagnostic and (control.returncode != 1 or "actual_white=16 mismatched_pixels=128" not in control.stdout):
        raise RuntimeError("Uncorrected shader did not reproduce the missing midpoint: " + control.stdout + control.stderr)
    if not args.disable_hud_diagnostic:
        print("Negative control: uncorrected shader erases all 128 midpoint object pixels (expected failure).")
    if args.transport_prototype:
        fragment.write_text(shader.replace(layer_correction, ""))
        control = subprocess.run([str(binary), str(fragment), "forward", "255", "scrolling", "transport"],
                                 capture_output=True, text=True)
        if not args.disable_hud_diagnostic and (control.returncode != 1 or "mismatched_pixels=24" not in control.stdout):
            raise RuntimeError("Removing layer sampling did not reproduce fractional halos: " + control.stdout + control.stderr)
        if not args.disable_hud_diagnostic:
            print("Negative control: removing layer sampling restores fractional halos (expected failure).")
        fragment.write_text(shader.replace(hole_correction, ""))
        control = subprocess.run([str(binary), str(fragment), "forward", "255", "local", "transport"],
                                 capture_output=True, text=True)
        if control.returncode != 1 or "missing=0 extra=128" not in control.stdout:
            raise RuntimeError("Removing hole correction did not reproduce ghosting: " + control.stdout + control.stderr)
        print("Negative control: removing disocclusion correction restores 128 ghost pixels (expected failure).")
    raise SystemExit(max(results))
