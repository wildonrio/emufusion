"""Execute the actual metadata writer against removable-ROM transitions."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.tests.test_first_install_startup import JAVA, ROOT, method

IMPORTER = ROOT / 'android-companion/src/com/thorium/preview/ImportManager.java'


class GeneratedLibraryReconcileTest(unittest.TestCase):
    def test_writer_reports_only_real_changes_and_keeps_registry_and_user_metadata(self):
        source = IMPORTER.read_text()
        methods = '\n'.join(method(source, signature) for signature in (
            'private boolean writeMetadata(',
            'private static boolean writeGeneratedMetadataIfChanged(',
            'private static boolean cleanupGeneratedMetadata(',
            'private static String readText(',
            'private static void writeTextAtomic(',
            'private static void writeCompatibilityMirror(',
            'private static int metadataQuality('))
        harness = r'''
import java.io.*;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
public class MetadataProbe {
  static String TAG="test";
  static File PEGASUS,REGISTRY,AUTO_METADATA,LUCENT_AUTO_METADATA,LEGACY_AUTO_METADATA;
  static class Log { static void i(String tag,String message) {} }
  static class JSONObject {
    Map<String,Object> values=new HashMap<>();
    JSONObject put(String k,Object v) { values.put(k,v); return this; }
    String optString(String k) { Object v=values.get(k); return v==null?"":v.toString(); }
    long optLong(String k,long d) { Object v=values.get(k); return v instanceof Number?((Number)v).longValue():d; }
    int optInt(String k,int d) { return (int)optLong(k,d); }
    int optInt(String k) { return optInt(k,0); }
    double optDouble(String k,double d) { Object v=values.get(k); return v instanceof Number?((Number)v).doubleValue():d; }
    double optDouble(String k) { return optDouble(k,0); }
    boolean optBoolean(String k,boolean d) { Object v=values.get(k); return v instanceof Boolean?(Boolean)v:d; }
    JSONArray optJSONArray(String k) { return null; }
  }
  static class JSONArray extends ArrayList<JSONObject> {
    int length() { return size(); }
    JSONObject optJSONObject(int i) { return get(i); }
  }
  static class GameSystems {
    static class SystemDef { String folder,collection; SystemDef(String s){folder=s;collection=s;} }
    static SystemDef byFolder(String s) { return new SystemDef(s); }
  }
  static class WallpaperAccent {
    static String REGISTRY_FIELD="accent",METADATA_FIELD="x-lucent-accent";
    static String sanitize(String v) { return v; }
  }
  static boolean hydrateRegistryFromExistingMetadata(JSONArray rows) { return false; }
  static boolean refreshWallpaperAccents(JSONArray rows) { return false; }
  static void writeJsonAtomic(File path,JSONArray rows) { throw new AssertionError("unexpected registry rewrite"); }
  static String dedupeGameIdentity(String s) { return s.toLowerCase(Locale.US); }
  static String cleanTitle(String s) { return s; }
  static String metadataSafe(String s) { return s; }
  static String launchCommand(String s) { return "internal:"+s; }
  static String format(double d) { return Double.toString(d); }
  static String formatScore(double d) { return Double.toString(d); }
  static String join(List<String> list,String delimiter) { return String.join(delimiter,list); }
  static void appendMetadataList(StringBuilder out,String key,JSONArray list) {}
  static void check(boolean b,String message) { if(!b) throw new AssertionError(message); }
  static void write(File f,String value) throws Exception {
    f.getParentFile().mkdirs(); Files.writeString(f.toPath(),value);
  }
  static JSONObject row(File rom,String system) {
    return new JSONObject().put("file",rom.toString()).put("system",system)
      .put("title",rom.getName()).put("sourceIdentity","owned:"+system).put("addedAt",123L)
      .put("critic",87).put("user",8.8).put("boxArt","retained-cover.png")
      .put("video","retained-video.mp4").put("ownerNote","preserve");
  }
  public static void main(String[] args) throws Exception {
    File root=new File(args[0]); PEGASUS=new File(root,"shared");
    REGISTRY=new File(PEGASUS,"registry.json");
    AUTO_METADATA=new File(root,"foreign/metafiles/99-lucent-auto-import.metadata.pegasus.txt");
    LUCENT_AUTO_METADATA=new File(root,"own/metafiles/99-lucent-auto-import.metadata.pegasus.txt");
    LEGACY_AUTO_METADATA=new File(PEGASUS,"99-lucent-auto-import.metadata.pegasus.txt");
    File gba=new File(root,"ROMs/gba/First.gba"), snes=new File(root,"ROMs/snes/Second.sfc");
    write(gba,"gba-payload"); write(snes,"snes-payload");
    JSONArray rows=new JSONArray(); JSONObject first=row(gba,"gba");
    rows.add(first); rows.add(row(snes,"snes"));
    File generated=new File(LUCENT_AUTO_METADATA.getParentFile(),"99-lucent-auto-gba.metadata.pegasus.txt");
    File ownerFile=new File(LUCENT_AUTO_METADATA.getParentFile(),"owner.metadata.pegasus.txt");
    write(ownerFile,"game: Owner record\nfile: /owner-only\n");
    MetadataProbe probe=new MetadataProbe();
    check(probe.writeMetadata(rows),"initial publication not reported");
    String expected=Files.readString(generated.toPath());
    check(expected.contains("assets.video: retained-video.mp4") && expected.contains("x-critic: 8.7"),
          "rendered enrichment missing");
    check(generated.setLastModified(1000000L),"could not set timestamp");
    check(!probe.writeMetadata(rows),"unchanged files requested restart");
    check(generated.lastModified()==1000000L,"unchanged generated file rewritten");
    Path hidden=gba.toPath().resolveSibling(".detached-gba"); Files.move(gba.toPath(),hidden);
    check(probe.writeMetadata(rows),"removed system file not reported");
    check(!generated.exists(),"absent ROM still in generated library");
    check(!probe.writeMetadata(rows),"stable absent ROM requested restart");
    Files.move(hidden,gba.toPath());
    check(probe.writeMetadata(rows),"returning registered game not reported");
    check(Files.readString(generated.toPath()).equals(expected),"return lost metadata");
    check(!probe.writeMetadata(rows),"stable return requested restart");
    first.put("archived",true);
    check(probe.writeMetadata(rows) && !generated.exists(),"archived game ignored");
    first.put("forceInclude",true);
    check(probe.writeMetadata(rows) && generated.isFile(),"explicit inclusion ignored");
    check(rows.size()==2 && rows.get(0)==first && first.optString("ownerNote").equals("preserve"),
          "registry lost or duplicated existing record");
    check(Files.readString(ownerFile.toPath()).equals("game: Owner record\nfile: /owner-only\n"),
          "owner metadata changed");
    check(Files.readString(gba.toPath()).equals("gba-payload") &&
          Files.readString(snes.toPath()).equals("snes-payload"),"ROM content changed");
    File blocked=new File(root,"blocked"); write(blocked,"not a directory");
    try {
      writeGeneratedMetadataIfChanged(new File(blocked,"file"),"cannot commit\n");
      throw new AssertionError("failed write returned success");
    } catch(IOException expectedFailure) {}
    System.out.println("metadata reconciliation PASS");
  }
''' + methods + '\n}\n'
        with tempfile.TemporaryDirectory(prefix='emufusion-metadata-reconcile-') as temp:
            unit = Path(temp) / 'MetadataProbe.java'
            unit.write_text(harness)
            compiled = subprocess.run([str(JAVA / 'javac'), '-d', temp, str(unit)],
                                      capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run([str(JAVA / 'java'), '-cp', temp, 'MetadataProbe', temp],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('metadata reconciliation PASS', result.stdout)


if __name__ == '__main__':
    unittest.main()
