"""Execute shared instanced shader on desktop core GL; NOT Android acceptance."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
java = Path('/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home/bin')
with tempfile.TemporaryDirectory(prefix='emufusion-instanced-') as temporary:
    build = Path(temporary)
    subprocess.run([str(java/'javac'), '-d', str(build),
                    str(root/'unified-android/src/com/thorium/preview/game/DenseMotionTransportShaders.java'),
                    str(root/'tools/qa/DenseMotionTransportShaderDump.java')], check=True)
    paths = []
    for stage in ('vertex', 'fragment'):
        source = subprocess.run([str(java/'java'), '-cp', str(build),
                                 'com.thorium.preview.game.DenseMotionTransportShaderDump', stage],
                                check=True, capture_output=True, text=True).stdout
        assert source.startswith('#version 300 es\n')
        source = source.replace('#version 300 es', '#version 150', 1).replace('precision highp float;', '')
        path = build/(stage+'.glsl')
        path.write_text(source)
        paths.append(str(path))
    binary = build/'runner'
    subprocess.run(['clang', '-Wno-deprecated-declarations', '-framework', 'OpenGL',
                    str(root/'tools/qa_transport_instanced.c'), '-o', str(binary)], check=True)
    raise SystemExit(subprocess.run([str(binary), *paths]).returncode)
