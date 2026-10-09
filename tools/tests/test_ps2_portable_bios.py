"""Execute the PS2 BIOS installer against internal and removable test volumes."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.tests.test_first_install_startup import JAVA, ROOT, method


class Ps2PortableBiosTest(unittest.TestCase):
    def test_removable_bios_is_found_and_private_install_is_reused(self):
        source = (ROOT / 'unified-android/src/com/thorium/preview/game/Phase2QualificationCatalog.java').read_text()
        methods = '\n'.join(method(source, name) for name in (
            'private static void installUserPs2Bios(',
            'private static File findPs2Bios(',
            'private static boolean validPs2Bios('))
        harness = r'''
import java.io.*;
import java.nio.file.*;
import java.util.*;
class Environment {
  static File storage;
  static File getExternalStorageDirectory(){return storage;}
}
class NativeAdapterPrerequisites {
  static List<File> volumes;
  static List<File> permittedVolumeRoots(){return volumes;}
}
class MissingFirmwareException extends IllegalStateException {
  MissingFirmwareException(String message){super(message);}
}
public final class Ps2PortableBiosProbe {
  static void check(boolean v,String m){if(!v)throw new AssertionError(m);}
  static void copyFile(File a,File b)throws Exception{Files.copy(a.toPath(),b.toPath());}
  public static void main(String[] args)throws Exception{
    File root=new File(args[0]);
    File internal=new File(root,"internal");internal.mkdirs();
    File removable=new File(root,"removable");removable.mkdirs();
    Environment.storage=internal;
    NativeAdapterPrerequisites.volumes=Arrays.asList(internal,removable);
    File bios=new File(removable,"ROMs/ps2/BIOS/region/owner-dump.bin");
    bios.getParentFile().mkdirs();
    try(RandomAccessFile f=new RandomAccessFile(bios,"rw")){f.setLength(4*1024*1024);f.write(77);}
    File system=new File(root,"private-system");
    installUserPs2Bios(system);
    File installed=new File(system,"pcsx2/bios/owner-dump.bin");
    check(installed.isFile()&&Files.mismatch(bios.toPath(),installed.toPath())==-1,
      "removable BIOS not copied intact");
    NativeAdapterPrerequisites.volumes=Collections.emptyList();
    installUserPs2Bios(system); // Does not need the card after valid installation.
    check(installed.isFile(),"private BIOS not reused");
    boolean failed=false;
    try{installUserPs2Bios(new File(root,"missing-system"));}
    catch(IllegalStateException expected){failed=true;}
    check(failed,"missing BIOS must not be fabricated or bypassed");
    System.out.println("PS2 removable BIOS PASS");
  }
''' + methods + '\n}\n'
        with tempfile.TemporaryDirectory(prefix='emufusion-ps2-bios-') as temp:
            unit = Path(temp) / 'Ps2PortableBiosProbe.java'
            unit.write_text(harness)
            subprocess.run([str(JAVA/'javac'), str(unit)], check=True, capture_output=True, text=True)
            result = subprocess.run([str(JAVA/'java'), '-cp', temp, 'Ps2PortableBiosProbe', str(Path(temp)/'data')],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)


if __name__ == '__main__':
    unittest.main()
