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
            'private static boolean looksLikePs2Bios(',
            'private static boolean skipAnywhereDirectory(',
            'private static boolean validPs2Bios('))
        methods = 'private static final int ANYWHERE_DEPTH = 8;\n' + methods
        harness = r'''
import java.io.*;
import java.nio.file.*;
import java.util.*;
import java.util.Locale;
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
    // Anywhere on a volume, outside any BIOS folder: a 4 MB Mega Drive .bin
    // is ignored, the real BIOS (ROMDIR beginning with RESET) is used in place.
    File card=new File(root,"card");
    File game=new File(card,"Download/Sonic 3 & Knuckles.bin");
    game.getParentFile().mkdirs();
    try(RandomAccessFile f=new RandomAccessFile(game,"rw")){f.setLength(4*1024*1024);f.write(1);}
    File loose=new File(card,"stuff/keys/ps2/scph39001.bin");
    loose.getParentFile().mkdirs();
    try(RandomAccessFile f=new RandomAccessFile(loose,"rw")){
      f.setLength(4*1024*1024);
      f.seek(0x2700); f.write("RESET\0\0\0\0\0ROMDIR\0\0\0\0".getBytes("ISO-8859-1"));
    }
    NativeAdapterPrerequisites.volumes=Arrays.asList(card);
    File anywhere=new File(root,"anywhere-system");
    installUserPs2Bios(anywhere);
    check(new File(anywhere,"pcsx2/bios/scph39001.bin").isFile(),"BIOS anywhere on the card not found");
    check(!new File(anywhere,"pcsx2/bios/Sonic 3 & Knuckles.bin").exists(),"a 4 MB game is not a BIOS");
    check(loose.isFile(),"the user's file stays where it is");
    NativeAdapterPrerequisites.volumes=Collections.emptyList();
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
