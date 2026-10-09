"""Execute real launch-directory and key-cache code without an Android device."""
import json
import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from tools.tests.test_native_adapter_prerequisites import GAME, JAVA, JAVAC, ROOT


class CemuContentPrerequisitesTest(unittest.TestCase):
    def test_native_patch_round_trip_matches_recorded_preimage(self):
        tree = Path(json.loads((ROOT / 'engines/cemu-source-lock.json').read_text())['core']['stagedTree'])
        old = {'KeyCache.cpp': '8de046635b53eb94db050ff83b682d64e47fe70f6c188da287d05edb48847238',
               'KeyCache.h': '90fd353c106a20ae29670c26b0194069df2728233de35f12baeaa9222b76c2c5'}
        patch = ROOT / 'engines/patches/cemu-disc-key-reload.patch'
        with tempfile.TemporaryDirectory(prefix='cemu-key-patch-') as tmp:
            target = Path(tmp) / 'src/Cafe/Filesystem/FST'
            target.mkdir(parents=True)
            for name in old:
                shutil.copy2(tree / 'src/Cafe/Filesystem/FST' / name, target / name)
            subprocess.run(['patch', '--batch', '-R', '-p1', '-i', str(patch)], cwd=tmp,
                           check=True, capture_output=True)
            for name, digest in old.items():
                self.assertEqual(hashlib.sha256((target / name).read_bytes()).hexdigest(), digest, name)
            subprocess.run(['patch', '--batch', '-p1', '-i', str(patch)], cwd=tmp,
                           check=True, capture_output=True)
            for name in old:
                self.assertEqual((target / name).read_bytes(), (tree / 'src/Cafe/Filesystem/FST' / name).read_bytes())

    def test_real_resolver_decrypted_and_encrypted_content(self):
        source = (GAME / 'NativeAdapterSystemDirectory.java').read_text()
        source = re.sub(r'^package .*;\s*', '', source, flags=re.M)
        source = re.sub(r'^import android\..*;\s*', '', source, flags=re.M)
        harness = r'''
import java.io.*;
import java.nio.file.*;
import java.lang.reflect.*;
class Context {
 static final int MODE_PRIVATE=0; final File base;
 Context(File base){this.base=base;}
 File getDir(String name,int mode){File p=new File(base,name);p.mkdirs();return p;}
}
class Environment {static File volume;static File getExternalStorageDirectory(){return volume;}}
class Build {static class VERSION {static final int SDK_INT=36;}}
class Os {static void setenv(String k,String v,boolean overwrite){}}
class Log {static int i(String t,String m){return 0;}static int w(String t,String m){return 0;}}
class NativeAdapterPrerequisites {
 static boolean ready=false;
 static boolean record(Context c,String s,boolean value){ready=value;return true;}
}
public class ContentProbe {
 static void check(boolean b,String m){if(!b)throw new AssertionError(m);}
 static File file(File root,String name,String data)throws Exception {
  File f=new File(root,name);f.getParentFile().mkdirs();Files.write(f.toPath(),data.getBytes("UTF-8"));return f;
 }
 static File resolve(Context c,String engine,String system,File game,String qa)throws Exception {
  // The same baseline call lacked content. This fallback keeps the pre-fix
  // failure behavioral (missing keys), rather than a missing-method compiler error.
  try {
   Method m=NativeAdapterSystemDirectory.class.getDeclaredMethod("resolve",Context.class,
     String.class,String.class,int.class,String.class,File.class);
   try{return (File)m.invoke(null,c,engine,system,1,qa,game);}
   catch(InvocationTargetException e){throw (Exception)e.getCause();}
  } catch(NoSuchMethodException beforeFix) {
   return NativeAdapterSystemDirectory.resolve(c,engine,system,1,qa);
  }
 }
 static void rejects(Context c,String engine,String system,File f)throws Exception {
  try{resolve(c,engine,system,f,"");throw new AssertionError("missing inputs accepted: "+engine);}
  catch(IllegalStateException e){check(e.getMessage().equals("Internal emulator prerequisites are unavailable"),"wrong failure");}
 }
 public static void main(String[] args)throws Exception {
  File base=new File(args[0]);Environment.volume=new File(base,"volume");Environment.volume.mkdirs();
  Context c=new Context(new File(base,"private"));
  for(String ext:new String[]{"wua","WUA","rpx","RPX","elf","wuhb"}){
   File game=file(Environment.volume,"ROMs/wiiu/test."+ext,"native parser validates actual content");
   File root=resolve(c,"cemu","wii-u",game,"");
   check(root.equals(new File(c.base,"engine-system/cemu").getCanonicalFile()),"wrong root");
   check(!new File(root,"keys.txt").exists(),"invented keys");
   check(!NativeAdapterPrerequisites.ready,"decrypted game falsely marks disc keys ready");
  }
  File encrypted=file(Environment.volume,"ROMs/wiiu/test.wux","encrypted");
  for(String ext:new String[]{"wux","WUD","iso","unknown","tmd"})
   rejects(c,"cemu","wiiu",file(Environment.volume,"ROMs/wiiu/test."+ext,"encrypted"));
  File wua=new File(Environment.volume,"ROMs/wiiu/test.wua");
  rejects(c,"eden","switch",wua);rejects(c,"aps3e","ps3",wua);
  String placeholder="541b9889519b27d363cd21604b97c67a # example key (can be deleted)\n";
  file(c.base,"engine-system/cemu/keys.txt",placeholder);
  resolve(c,"cemu","wiiu",wua,"");rejects(c,"cemu","wiiu",encrypted);
  String key="00112233445566778899aabbccddeeff\n";
  File supplied=file(Environment.volume,"ROMs/wiiu/Keys/keys.txt",key);
  File root=resolve(c,"cemu","wiiu",wua,"");
  check(Files.readString(new File(root,"keys.txt").toPath()).equals(key),"optional valid keys not installed");
  check(NativeAdapterPrerequisites.ready,"installed disc keys not recorded");
  resolve(c,"cemu","wiiu",encrypted,"");
  Files.delete(supplied.toPath());
  resolve(c,"cemu","wiiu",encrypted,""); // Preserve the private working copy.
  String qa="qa-0123456789abcdef0123456789abcdef";
  File isolated=resolve(c,"cemu","wiiu",wua,qa);
  check(isolated.getPath().contains("engine-system-qa-"),"QA root lost");
  check(!new File(isolated,"keys.txt").exists(),"QA borrowed unrelated private keys");
  check(NativeAdapterPrerequisites.ready,"QA changed normal readiness");
  System.out.println("CONTENT_REQUIREMENTS_OK");
 }
}
'''
        with tempfile.TemporaryDirectory(prefix='cemu-content-prereq-') as tmp:
            path = Path(tmp)
            (path / 'NativeAdapterSystemDirectory.java').write_text(source)
            (path / 'ContentProbe.java').write_text(harness)
            built = subprocess.run([str(JAVAC), *map(str, path.glob('*.java'))],
                                   capture_output=True, text=True, timeout=60)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            run = subprocess.run([str(JAVA), '-cp', tmp, 'ContentProbe', str(path / 'fixture')],
                                 capture_output=True, text=True, timeout=60)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn('CONTENT_REQUIREMENTS_OK', run.stdout)

    def test_session_passes_resolved_game_to_prerequisite_boundary(self):
        source = (GAME / 'NativeAdapterEngineSession.java').read_text()
        self.assertIsNotNone(re.search(r'NativeAdapterSystemDirectory\.resolve\(appContext,\s*'
            r'entry.id, request.systemId, capabilities.requiredFirmware,\s*'
            r'request.qualificationSession, game\)', source), 'Session must pass actual content')

    def test_actual_native_cache_reload_accepts_later_added_keys(self):
        tree = Path(json.loads((ROOT / 'engines/cemu-source-lock.json').read_text())['core']['stagedTree'])
        source = (tree / 'src/Cafe/Filesystem/FST/KeyCache.cpp').read_text()
        source = re.sub(r'^#include .*$', '', source, flags=re.M)
        harness = r'''
#include <mutex>
#include <string>
#include <string_view>
#include <vector>
#include <cstring>
#include <cstdint>
#include <cassert>
using uint8=uint8_t;using sint32=int32_t;
static bool exists=false;static std::vector<std::string> disk;static int reads=0;
struct FileStream {
 size_t pos=0;
 static FileStream* openFile2(std::string){reads++;return exists?new FileStream:nullptr;}
 static FileStream* createFile2(std::string){exists=true;disk.clear();return new FileStream;}
 void writeString(std::string line){disk.push_back(line);}
 bool readLine(std::string& s){if(pos>=disk.size())return false;s=disk[pos++];return true;}
};
namespace ActiveSettings{std::string GetUserDataPath(std::string s){return s;}}
namespace WindowSystem {
 enum class ErrorCategory{KEYS_TXT_CREATION};
 template<class...T>void ShowErrorDialog(T...){assert(false);}
}
template<class...T>std::string _tr(std::string s,T...){return s;}
namespace StringHelpers {
 void ParseHexString(std::string s,uint8* p,int n){for(int i=0;i<n;i++)p[i]=std::stoul(s.substr(i*2,2),nullptr,16);}
}
''' + source
        # Baseline behavior is exercised rather than failing to compile an absent API.
        if 'void KeyCache_Reload()' not in source:
            harness += '\nvoid KeyCache_Reload(){KeyCache_Prepare();}\n'
        harness += r'''
int main(){
 KeyCache_Prepare();assert(KeyCache_GetAES128(0)==nullptr); // no user keys on first decrypted launch
 disk={"00112233445566778899aabbccddeeff # user supplied later"};exists=true;
 KeyCache_Prepare();assert(KeyCache_GetAES128(0)==nullptr); // ordinary callers remain one-shot
 KeyCache_Reload();assert(KeyCache_GetAES128(0)!=nullptr);
 assert(KeyCache_GetAES128(0)[1]==0x11 && KeyCache_GetAES128(0)[15]==0xff);
 disk={"ffeeddccbbaa99887766554433221100; replacement"};
 KeyCache_Reload();assert(KeyCache_GetAES128(0)[0]==0xff && KeyCache_GetAES128(0)[15]==0);
 assert(KeyCache_GetAES128(1)==nullptr); // replacement is not accumulation
 int before=reads;KeyCache_Prepare();assert(reads==before);
}
'''
        with tempfile.TemporaryDirectory(prefix='cemu-key-cache-') as tmp:
            path = Path(tmp)
            (path / 'test.cpp').write_text(harness)
            built = subprocess.run([shutil.which('clang++'), '-std=c++17',
                '-fsanitize=address,undefined', str(path / 'test.cpp'), '-o', str(path / 'test')],
                capture_output=True, text=True, timeout=60)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            run = subprocess.run([str(path / 'test')], capture_output=True, text=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_reload_only_on_quiescent_relaunch_before_title_parse(self):
        source = (ROOT / 'engines/patches/cemu-lucent-adapter.cpp').read_text()
        self.assertTrue('if (relaunch) KeyCache_Reload();' in source, 'Missing between-title key refresh')
        self.assertLess(source.index('while (CafeTitleList::IsScanning())'), source.index('if (relaunch) KeyCache_Reload();'))
        self.assertLess(source.index('if (relaunch) KeyCache_Reload();'), source.index('TitleInfo launchTitle{launchPath};'))


if __name__ == '__main__':
    unittest.main()
