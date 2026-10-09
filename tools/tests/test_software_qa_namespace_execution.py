"""Execute the real launcher's namespace branch without Android or any FG API."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
JAVA = Path('/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home/bin')


class SoftwareQaNamespaceExecutionTest(unittest.TestCase):
    def test_actual_namespace_branch(self):
        host = (ROOT / 'unified-android/src/com/thorium/preview/game/InWindowGameHost.java').read_text()
        branch = host[host.index('String qualificationSession = "";'):]
        branch = branch[:branch.index('FrameGenerationSettings.Mode launchMode')]
        source = '''
import java.util.regex.Pattern;
public class NamespaceTest {
    static final Pattern QUALIFICATION_SESSION=Pattern.compile("qa-[0-9a-f]{32}");
    static String clean(String s) { return s == null ? "" : s.trim(); }
    static class Intent {
        final String value; Intent(String value) { this.value=value; }
        String getStringExtra(String key) { return value; }
    }
    static class Catalog {
        final boolean allowed; Catalog(boolean allowed) { this.allowed=allowed; }
        boolean supports(String system) { return allowed; }
    }
    static String resolve(boolean qualificationOnly, boolean approvedPhaseOne,
            Catalog phaseTwo, boolean approvedPhaseThree, String engine,
            String system, Intent source) {
''' + branch + '''
        return qualificationSession;
    }
    static void eq(String expected, String actual) {
        if (expected==null ? actual!=null : !expected.equals(actual))
            throw new AssertionError("expected="+expected+" actual="+actual);
    }
    public static void main(String[] args) {
        String id="qa-0123456789abcdef0123456789abcdef";
        Intent qa=new Intent(id), empty=new Intent("");
        eq("",resolve(false,true,null,false,"melonds-ds","nds",empty));
        eq(null,resolve(false,true,null,false,"melonds-ds","nds",qa));
        eq(id,resolve(true,true,null,false,"melonds-ds","nds",qa));
        eq(null,resolve(true,false,null,false,"missing","nds",qa));
        eq(null,resolve(true,true,null,false,"melonds-ds","nds",new Intent("../normal")));
        eq(null,resolve(true,true,null,false,"melonds-ds","nds",empty));
        eq(id,resolve(true,false,new Catalog(true),false,"azahar","3ds",qa));
        eq(null,resolve(true,false,new Catalog(false),false,"azahar","3ds",qa));
        eq(id,resolve(true,false,null,true,"aps3e","ps3",qa));
        eq(null,resolve(true,false,null,true,"unknown","other",qa));
        System.out.println("10 namespace cases passed; no frame-generation API needed");
    }
}
'''
        with tempfile.TemporaryDirectory(prefix='emufusion-namespace-') as directory:
            folder = Path(directory)
            java = folder / 'NamespaceTest.java'
            java.write_text(source)
            native = ROOT / 'unified-android/src/com/thorium/lucent/emulators/NativeQualificationStorage.java'
            compile_result = subprocess.run([str(JAVA / 'javac'), '--release', '8',
                '-d', directory, str(java), str(native)], text=True, capture_output=True)
            self.assertEqual(compile_result.returncode, 0, compile_result.stderr)
            result = subprocess.run([str(JAVA / 'java'), '-cp', directory, 'NamespaceTest'],
                                    text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
