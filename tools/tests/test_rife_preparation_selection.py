"""Behavioral host test of real transport selection; no Android/JNI execution."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
JAVA=Path(os.environ.get('JAVA_HOME', '/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home'), 'bin')
ANDROID=Path('/Users/tyleryoung/Library/Android/sdk/platforms/android-35/android.jar')
CLASSES=ROOT/'unified-android/build/classes'


class PreparationSelectionTest(unittest.TestCase):
    @unittest.skipUnless((JAVA/'javac').exists() and ANDROID.exists() and CLASSES.exists(),
                         'requires local Java17, Android35 and app dependency classes')
    def test_real_selection_and_backpressure(self):
        qualification=ROOT/'unified-android/qualification-src/com/thorium/preview/game'
        native=ROOT/'experiments/rife-ncnn-vulkan-android/android-benchmark/app/src/main/java/com/emufusion/rifebenchmark'
        video=ROOT/'unified-android/src/com/thorium/lucent/video'
        sources=[qualification/'RifePresentationTransport.java',qualification/'RifeQualificationRuntime.java',
                 ROOT/'unified-android/src/com/thorium/preview/game/ExternalFrameGenerationTransport.java',
                 native/'NativeRifeBridge.java',native/'ModelIntegrity.java',
                 video/'FrameGenerationPreparationRequest.java',video/'FrameGenerationPresentationRequest.java',
                 ROOT/'tools/qa/RifePreparationSelectionTest.java']
        with tempfile.TemporaryDirectory(prefix='emufusion-selection-') as output:
            classpath=f'{ANDROID}:{CLASSES}'
            build=subprocess.run([str(JAVA/'javac'),'-cp',classpath,'-d',output,*map(str,sources)],
                                 text=True,capture_output=True,timeout=60)
            self.assertEqual(build.returncode,0,build.stdout+build.stderr)
            run=subprocess.run([str(JAVA/'java'),'-cp',f'{output}:{classpath}','RifePreparationSelectionTest'],
                               text=True,capture_output=True,timeout=20)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            self.assertIn('PASS actual transport',run.stdout)


if __name__=='__main__': unittest.main()
