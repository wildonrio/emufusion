"""Execute real route code with fresh-install preferences and missing prerequisites."""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from tools.tests.test_first_install_startup import JAVA, ROOT


class PortableInternalRoutingTest(unittest.TestCase):
    def test_fresh_install_and_explicit_external_routes(self):
        sources = [
            ROOT / 'android-companion/src/com/thorium/preview/EngineRouteStore.java',
            ROOT / 'android-companion/src/com/thorium/preview/GameLaunchRouter.java',
            ROOT / 'unified-android/src/com/thorium/lucent/metadata/EngineSystemIdResolver.java',
            ROOT / 'unified-android/src/com/thorium/lucent/metadata/MetadataGameLaunchCommand.java',
        ]
        harness = r'''
import java.util.*;
class Context {
  static final int MODE_PRIVATE=0;
  final Map<String,SharedPreferences> preferences=new HashMap<>();
  Context getApplicationContext(){return this;}
  SharedPreferences getSharedPreferences(String n,int m){
    return preferences.computeIfAbsent(n,k->new SharedPreferences());
  }
}
class SharedPreferences {
  final Map<String,String> values=new HashMap<>();
  String getString(String k,String fallback){return values.getOrDefault(k,fallback);}
  Editor edit(){return new Editor();}
  class Editor {
    Editor putString(String k,String v){values.put(k,v);return this;}
    Editor remove(String k){values.remove(k);return this;}
    void apply(){}
  }
}
class InternalEngineCatalog {
  static class Entry {String id; Entry(String s){id=s;}}
  static final Map<String,String> engines=new HashMap<>();
  static Entry availableForSystem(Context c,String s){
    String id=engines.get(s);return id==null?null:new Entry(id);
  }
}
class Phase2QualificationCatalog {
  static final Map<String,String> engines=new HashMap<>();
  static String libraryEngineIdForSystem(Context c,String s){return engines.getOrDefault(s,"");}
}
class NativeAdapterCatalog {
  static final Map<String,String> engines=new HashMap<>();
  static String libraryEngineIdForSystem(Context c,String s){return engines.getOrDefault(s,"");}
}
class NativeAdapterPrerequisites {
  // A new installation has no readiness preference, regardless of bundled engines.
  static boolean isReady(Context c,String s){return false;}
}
class InWindowGameHost {static final String ACTION_LAUNCH="com.thorium.preview.LAUNCH_INTERNAL_GAME";}
class CustomEmulatorStore {
  static final String ID="custom";
  static boolean has(Context c,String s){return false;}
  static Object option(Context c,String s){return null;}
}
class EmulatorCatalog {
  static boolean hasExternalOption(String s){return !s.equals("ps3");}
  static Object optionForId(String s,String id){return id.equals("external-test")?new Object():null;}
  static String externalLaunchCommand(Context c,String s,String id){return "EXTERNAL:"+s;}
}
public final class PortableRoutesProbe {
  static void check(boolean ok,String why){if(!ok)throw new AssertionError(why);}
  public static void main(String[] args){
    Context context=new Context();
    String[] systems={"switch","wiiu","ps3","wii","gc","ps2","psp","psx",
      "dreamcast","n3ds","nds","n64","snes","nes","gb","gbc","gba",
      "megadrive","gamegear","pcenginecd"};
    for(String alias:systems){
      String s=EngineSystemIdResolver.canonical(alias);
      // No packaged engine is not permission to open a browser or other app.
      check(EngineRouteStore.resolve(context,alias).equals("internal"),s+" implicit external fallback");
      check(EngineRouteStore.launchCommand(context,alias).isEmpty(),s+" invented unverified engine");
      String engine="core-"+s;
      if(s.equals("switch")||s.equals("wiiu")||s.equals("ps3"))
        NativeAdapterCatalog.engines.put(s,engine);
      else if(s.equals("gamecube")||s.equals("wii")||s.equals("ps2")||s.equals("3ds"))
        Phase2QualificationCatalog.engines.put(s,engine);
      else InternalEngineCatalog.engines.put(s,engine);
      check(GameLaunchRouter.supportsSystem(context,alias),s+" hides bundled engine before readiness scan");
      String command=EngineRouteStore.launchCommand(context,alias);
      check(command.contains("LAUNCH_INTERNAL_GAME"),s+" fresh install is not internal");
      check(command.contains("--es engine_id "+engine),s+" lost packaged engine");
      check(EngineRouteStore.setRoute(context,alias,"internal",""),s+" cannot choose bundled engine");
      if(!s.equals("ps3")){
        check(EngineRouteStore.setRoute(context,alias,"external","external-test"),s+" explicit external rejected");
        check(EngineRouteStore.launchCommand(context,alias).equals("EXTERNAL:"+s),s+" explicit external ignored");
        EngineRouteStore.clearRoute(context,alias);
        check(EngineRouteStore.resolve(context,alias).equals("internal"),s+" reset failed");
      }
      context.getSharedPreferences("engine-routes",0).edit().putString("route."+s,"internal").apply();
      InternalEngineCatalog.engines.clear();Phase2QualificationCatalog.engines.clear();NativeAdapterCatalog.engines.clear();
      check(EngineRouteStore.resolve(context,alias).equals("internal"),s+" silently overrides user's internal choice");
      check(EngineRouteStore.launchCommand(context,alias).isEmpty(),s+" missing engine escaped internally");
    }
    check(!EngineRouteStore.setRoute(context,"ps3","external","external-test"),"PS3 remains internal-only");
    System.out.println("portable internal routing PASS: 20 systems, missing prerequisites, explicit external and unavailable engines");
  }
}
'''
        with tempfile.TemporaryDirectory(prefix='emufusion-portable-routes-') as temp:
            directory = Path(temp)
            for source in sources:
                code = re.sub(r'^package .*;\s*', '', source.read_text(), flags=re.M)
                code = re.sub(r'^import (?:android|com\.thorium)\..*;\s*', '', code, flags=re.M)
                (directory / source.name).write_text(code)
            (directory / 'PortableRoutesProbe.java').write_text(harness)
            compile_result = subprocess.run([str(JAVA/'javac'), *map(str, directory.glob('*.java'))],
                                            capture_output=True, text=True)
            self.assertEqual(compile_result.returncode, 0, compile_result.stderr)
            result = subprocess.run([str(JAVA/'java'), '-cp', temp, 'PortableRoutesProbe'],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('portable internal routing PASS', result.stdout)


if __name__ == '__main__':
    unittest.main()
