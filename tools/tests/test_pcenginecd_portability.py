"""Run the real CD importer/spec with synthetic firmware; not CD gameplay evidence."""
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.tests.test_first_install_startup import JAVA, ROOT, method

GAME = ROOT / 'unified-android/src/com/thorium/preview/game'


class PcEngineCdPortabilityTest(unittest.TestCase):
    def test_actual_joypad_dispatch_and_console_roster(self):
        source = ROOT / 'unified-android/src/com/thorium/lucent/input'
        tests = ROOT / 'unified-android/test/com/thorium/lucent'
        with tempfile.TemporaryDirectory(prefix='emufusion-pcecd-controller-') as temp:
            units = [source / (name + '.java') for name in
                     ('CanonicalControl', 'SystemControlLayouts', 'LibretroJoypadLayout')]
            units += [tests / 'TestSupport.java', tests / 'input/LibretroJoypadLayoutTest.java']
            result = subprocess.run([str(JAVA / 'javac'), '--release', '8', '-encoding', 'UTF-8',
                                     '-d', temp, *map(str, units)], capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            result = subprocess.run([str(JAVA / 'java'), '-cp', temp,
                                     'com.thorium.lucent.input.LibretroJoypadLayoutTest'],
                                    capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_actual_importer_and_system_selection(self):
        harness = r'''
import java.io.*;
import java.nio.file.*;
import java.security.*;
import java.util.*;
class Context {
  static final int MODE_PRIVATE=0;
  final File root;
  Context(File root){this.root=root;}
  File getDir(String name,int mode){File dir=new File(root,name);dir.mkdirs();return dir;}
}
class TestEntry {
  String id,sourceCommit,coreArtifactSha256,runtime,renderer;
  List<String> systems=Collections.emptyList(),acceptedFirmwareHashes=Collections.emptyList();
  int stateCompatibilityVersion;
  boolean firmwareRequired;
  File coreFile;
}
class InternalEngineCatalog {
  static class Entry extends TestEntry {}
  static Entry byId(Context context,String id){return null;}
}
class Phase2QualificationCatalog {
  static class RuntimeInstallation {File directory;String firmwareIdentity;}
  static class Entry extends TestEntry {
    RuntimeInstallation installRuntimeAssets(Context context,String system){return null;}
  }
  static Entry byId(Context context,String id){return null;}
}
class NativeAdapterPrerequisites {
  static List<File> volumes=Collections.emptyList();
  static List<File> permittedVolumeRoots(){return volumes;}
}
public final class PcEngineCdProbe {
  interface Attempt {void run()throws Exception;}
  static int checks;
  static void check(boolean value,String why){checks++;if(!value)throw new AssertionError(why);}
  static void missing(Attempt action)throws Exception {
    try {action.run();throw new AssertionError("accepted missing/incorrect BIOS");}
    catch(PcEngineCdFirmware.SetupException expected){
      check(expected.getMessage().contains("ROMs/pcenginecd/BIOS"),"actionable setup path missing");
    }
  }
  static String hash(byte[] bytes,String name)throws Exception {
    StringBuilder result=new StringBuilder();
    for(byte b:MessageDigest.getInstance(name).digest(bytes))result.append(String.format("%02x",b&255));
    return result.toString();
  }
  static void write(File file,byte[] bytes)throws Exception {
    file.getParentFile().mkdirs();Files.write(file.toPath(),bytes);
  }
  public static void main(String[] args)throws Exception {
    File root=new File(args[0]);Context context=new Context(root);
    LibretroEngineSpec spec=new LibretroEngineSpec("beetle-pce-fast",
      Arrays.asList("pcengine","pcenginecd"),"source","core",false,1,false,
      Collections.emptyList(),new File(root,"core.so"),"software",(c,s)->true,null);
    check(spec.supports("pcenginecd"),"CD not supported");
    LibretroEngineSpec.SystemInstallation cartridge=spec.installRuntime(context,"pcengine");
    check(cartridge.firmwareIdentity.equals("firmware:none"),"cartridge requires CD BIOS");
    missing(()->spec.installRuntime(context,"pcenginecd"));
    File internal=new File(root,"internal"),card=new File(root,"removable");
    NativeAdapterPrerequisites.volumes=Arrays.asList(internal,card);
    byte[] original=new byte[262144];
    for(int i=0;i<original.length;i++)original[i]=(byte)(i*31+7);
    String md5=hash(original,"MD5"),sha=hash(original,"SHA-256");
    File source=new File(card,"ROMs/pcenginecd/BIOS/region/Owner System Card.PCE");
    write(source,original);
    // Real production policy must reject even a correctly sized/name-shaped fake BIOS.
    missing(()->spec.installRuntime(context,"pcenginecd"));
    check(PcEngineCdFirmware.SYSTEM_CARD_3_MD5.equals("38179df8f4ac870017db21ebcbf53114"),
      "upstream firmware contract changed");
    File invalid=new File(internal,"ROMs/pcenginecd/BIOS/syscard3.pce");
    write(invalid,new byte[262144]);
    File oversized=new File(internal,"ROMs/pcenginecd/BIOS/large.bin");
    try(RandomAccessFile f=new RandomAccessFile(oversized,"rw")){f.setLength(1024*1024+1);}
    String identity=PcEngineCdFirmware.installMatching(cartridge.directory,
      NativeAdapterPrerequisites.volumes,md5);
    File installed=new File(cartridge.directory,"syscard3.pce");
    check(identity.equals("firmware:sha256:"+sha),"save-state BIOS identity lost");
    check(Arrays.equals(Files.readAllBytes(installed.toPath()),original),"copy differs");
    check(Arrays.equals(Files.readAllBytes(source.toPath()),original),"user source modified");
    check(Files.readAllBytes(invalid.toPath())[0]==0,"unrelated invalid BIOS modified");
    NativeAdapterPrerequisites.volumes=Collections.emptyList();
    check(identity.equals(PcEngineCdFirmware.installMatching(cartridge.directory,
      Collections.emptyList(),md5)),"installed BIOS not reused without card");
    // Importing CD firmware must not change cartridge save-state identity.
    check(spec.installRuntime(context,"pcengine").firmwareIdentity.equals("firmware:none"),
      "CD install orphaned cartridge states");
    // Fixture acceptance is only through this test's explicit identity, never production.
    missing(()->spec.installRuntime(context,"pcenginecd"));
    check(Arrays.equals(Files.readAllBytes(installed.toPath()),original),"failed import removed BIOS");
    write(installed,new byte[]{1,2,3});
    missing(()->PcEngineCdFirmware.installMatching(cartridge.directory,Collections.emptyList(),md5));
    check(Files.size(installed.toPath())==3,"invalid private image deleted before replacement");
    check(identity.equals(PcEngineCdFirmware.installMatching(cartridge.directory,
      Arrays.asList(internal,card),md5)),"replacement did not recover invalid private image");
    check(cartridge.directory.listFiles().length==1,"partial import left behind");
    System.out.println("PC Engine CD importer/spec PASS: "+checks+" checks; synthetic firmware only");
  }
}
'''
        with tempfile.TemporaryDirectory(prefix='emufusion-pcecd-') as temp:
            directory = Path(temp)
            for filename in ('PcEngineCdFirmware.java', 'LibretroEngineSpec.java'):
                source = (GAME / filename).read_text()
                source = re.sub(r'^package .*;\s*', '', source, flags=re.M)
                source = re.sub(r'^import android\..*;\s*', '', source, flags=re.M)
                (directory / filename).write_text(source)
            (directory / 'PcEngineCdProbe.java').write_text(harness)
            result = subprocess.run([str(JAVA/'javac'), *map(str,directory.glob('*.java'))],
                                    capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            result = subprocess.run([str(JAVA/'java'),'-cp',temp,'PcEngineCdProbe',str(directory/'data')],
                                    capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            print(result.stdout.strip())

    def test_software_session_retains_firmware_identity_and_setup_message(self):
        source = (GAME/'LibretroEngineSession.java').read_text()
        self.assertIn('entry.installRuntime(appContext, launch.systemId)',source)
        self.assertNotIn('entry.installSystem(appContext, launch.systemId)',source)
        self.assertIn('"firmware:none".equals(runtime.firmwareIdentity)',source)
        self.assertIn('entry.acceptedFirmwareHashes) : runtime.firmwareIdentity',source)
        self.assertIn('failure instanceof PcEngineCdFirmware.SetupException',source)
        self.assertIn('? failure.getMessage() : "EmuFusion could not start "',source)

    def test_actual_software_firmware_selection_preserves_legacy_and_installed_identities(self):
        source = (GAME/'LibretroEngineSession.java').read_text()
        selection = re.search(r'String firmware = "firmware:none".*?;',source,re.S).group(0)
        helpers = '\n'.join(method(source,name) for name in (
            'private static String firmwareFingerprint(',
            'private static String sha256(', 'private static String hex('))
        harness = r'''
import java.io.*;
import java.security.*;
import java.util.*;
class Installation {String firmwareIdentity;Installation(String value){firmwareIdentity=value;}}
class Entry {boolean firmwareRequired;List<String> acceptedFirmwareHashes=Collections.emptyList();}
public final class FirmwareIdentityProbe {
  static String select(File system,Installation runtime,Entry entry)throws Exception {
''' + selection + r'''
    return firmware;
  }
  public static void main(String[] args)throws Exception {
    File system=new File(args[0]);system.mkdirs();Entry entry=new Entry();
    String installed="firmware:sha256:0123456789abcdef";
    if(!select(system,new Installation(installed),entry).equals(installed))
      throw new AssertionError("installer identity discarded");
    if(!select(system,new Installation("firmware:none"),entry).equals("firmware:none"))
      throw new AssertionError("legacy no-firmware identity changed");
    File bios=new File(system,"open-qa.bin");
    try(FileOutputStream output=new FileOutputStream(bios)){output.write(new byte[]{3,7,11});}
    entry.firmwareRequired=true;entry.acceptedFirmwareHashes=Arrays.asList(sha256(bios));
    String legacy=firmwareFingerprint(system,true,entry.acceptedFirmwareHashes);
    if(!select(system,new Installation("firmware:none"),entry).equals(legacy))
      throw new AssertionError("legacy accepted firmware state identity changed");
    entry.acceptedFirmwareHashes=Collections.emptyList();
    try {
      select(system,new Installation("firmware:none"),entry);
      throw new AssertionError("required legacy firmware guard bypassed");
    } catch(IllegalStateException expected) {}
    System.out.println("Software firmware identity selection PASS: installed and legacy paths");
  }
''' + helpers + '\n}\n'
        with tempfile.TemporaryDirectory(prefix='emufusion-firmware-identity-') as temp:
            unit=Path(temp)/'FirmwareIdentityProbe.java'
            unit.write_text(harness)
            result=subprocess.run([str(JAVA/'javac'),str(unit)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            result=subprocess.run([str(JAVA/'java'),'-cp',temp,'FirmwareIdentityProbe',str(Path(temp)/'data')],
                                  capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            print(result.stdout.strip())

    def test_real_registry_retains_cartridge_contract_and_no_bundled_firmware(self):
        registry = json.loads((ROOT/'engines/registry.json').read_text())
        row = next(r for r in registry['engines'] if r['id']=='beetle-pce-fast')
        self.assertEqual(row['systems'],['pcengine','pcenginecd'])
        self.assertEqual(row['firmware']['requiredForSystems'],['pcenginecd'])
        self.assertFalse(row['firmware']['required'])
        self.assertEqual(row['firmware']['acceptedHashes'],[])
        self.assertFalse(row['state']['qualified'])
        self.assertFalse(row['shipped'])


if __name__ == '__main__':
    unittest.main()
