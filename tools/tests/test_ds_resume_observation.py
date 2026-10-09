"""Execute the production DS image observer; pixels cannot authorize a reset.

The observer block is extracted unchanged from the Android session. Frame,
logging and reset/storage boundaries are fakes; all sampling/decision code is real.
"""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SESSION = ROOT / 'unified-android/src/com/thorium/preview/game/LibretroEngineSession.java'
JAVA = Path('/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home/bin')


def observer(source):
    match = re.search(r'if\s*\([^{}]*--dualCropDiagCountdown[^{}]*\)\s*\{', source)
    assert match, 'Missing production image observation block'
    start, opening = match.start(), match.end() - 1
    masked = re.sub(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/',
                    lambda m: ' ' * len(m.group()), source, flags=re.S)
    depth = 0
    for end in range(opening, len(source)):
        if masked[end] == '{': depth += 1
        elif masked[end] == '}':
            depth -= 1
            if depth == 0: return source[start:end + 1]
    raise AssertionError('Unclosed observation block')


SHELL = r'''
import java.util.*;
public class DsResumeObservation {
    static final String TAG="test";
    boolean quickResumeLivenessWatch=true;
    int dualCropDiagCountdown,quickResumeFrozenRepeats,quickResumeChangesSeen,resets;
    long quickResumeLastCropSignature=Long.MIN_VALUE;
    final Frame frame=new Frame();
    final int[] frameColors=new int[256*384];
    final Entry entry=new Entry();
    final Vault vault=new Vault();
    final Object identity=new Object();
    static class Frame {int width=256,height=384;}
    static class Entry {String id="melonds-ds";}
    static class Vault {int discards;void discardQuickResume(Object ignored){discards++;}}
    static class Log {
        static final List<String> lines=new ArrayList<>();
        static void i(String tag,String text){lines.add(text);}
        static void w(String tag,String text){lines.add(text);}
        static void e(String tag,String text){lines.add(text);}
    }
    void reset(){resets++;}
    void present(){ OBSERVER }
    static void check(boolean value,String why){if(!value)throw new AssertionError(why);}
    public static void main(String[] args){
        DsResumeObservation s=new DsResumeObservation();
        String scenario=args[0];
        if(scenario.equals("static"))Arrays.fill(s.frameColors,0xff808080);
        if(scenario.equals("cold"))s.quickResumeLivenessWatch=false;
        for(int n=0;n<60*120;n++){
            if(scenario.equals("moving")){
                // A real moving red sprite remains invisible to this blue-only
                // sparse sum, despite different complete images each frame.
                s.frameColors[257+(n%200)]=0xff000000;
                s.frameColors[257+((n+1)%200)]=0xffff0000;
            }
            if(scenario.equals("changing"))Arrays.fill(s.frameColors,0xff000000|(n/120));
            s.present();
        }
        check(s.resets==0,"legitimate "+scenario+" images cold-reset the game");
        check(s.vault.discards==0,"image observations discarded a saved resume reference");
        check(!s.quickResumeLivenessWatch,"observation work outlived its bounded window");
        check(Log.lines.size()<=32,"periodic image logging continued after observation ended");
        check(Log.lines.stream().noneMatch(x->x.contains("liveness confirmed")),
              "sampled image changes falsely declared input/core health");
        if(scenario.equals("cold"))check(Log.lines.isEmpty(),"cold gameplay ran resume diagnostics");
        System.out.println(scenario+" preserved state and gameplay");
    }
}
'''


class DsResumeObservationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='ds-resume-observer-')
        cls.directory = Path(cls.temp.name)
        source = SHELL.replace('OBSERVER', observer(SESSION.read_text()))
        path = cls.directory / 'DsResumeObservation.java'
        path.write_text(source)
        subprocess.run([str(JAVA / 'javac'), '-d', str(cls.directory), str(path)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_image_observations_never_reset_or_discard_progress(self):
        for scenario in ('static', 'black', 'moving', 'changing', 'cold'):
            with self.subTest(scenario=scenario):
                result = subprocess.run([str(JAVA / 'java'), '-cp', str(self.directory),
                                         'DsResumeObservation', scenario], capture_output=True, text=True)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
