"""Startup discovery must work without Downloads, network, or a live QML menu."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.tests.test_first_install_startup import method, JAVA, ROOT

IMPORTER = ROOT / 'android-companion/src/com/thorium/preview/ImportManager.java'
APPLICATION = ROOT / 'unified-android/src/com/thorium/preview/LucentApplication.java'
SERVICE = ROOT / 'android-companion/src/com/thorium/preview/PreviewService.java'


class LocalLibraryDiscoveryTest(unittest.TestCase):
    def test_reopen_discovers_added_rom_on_same_volume_without_rewriting_unchanged_library(self):
        """Execute production bootstrap; a volume path is not a contents fingerprint."""
        bootstrap = method(IMPORTER.read_text(), 'private boolean bootstrapLocalLibrary(')
        harness = r'''
import java.io.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicBoolean;
import android.content.Context;
public final class BootstrapProbe {
  static final String TAG="test";
  static final class Log { static void i(String tag, String message) {} }
  static final class JSONObject {
    final Map<String,Object> values=new HashMap<>();
    JSONObject put(String key, Object value) { values.put(key,value); return this; }
  }
  static final class JSONArray extends ArrayList<JSONObject> {
    void put(JSONObject value) { add(value); }
  }
  static final class Candidate {
    final File source; final String identity;
    Candidate(File source) { this.source=source; identity=source.toString()+":"+source.length(); }
  }
  static final class ImportedGame {
    final Candidate candidate; final String title;
    ImportedGame(Candidate candidate, File file) {
      this.candidate=candidate; title=file.getName();
    }
    JSONObject toJson() {
      return new JSONObject().put("sourceIdentity",candidate.identity).put("title",title)
          .put("file",candidate.source);
    }
  }
  final Context context=new Context();
  final AtomicBoolean initialScanStarted=new AtomicBoolean(true);
  File volume, REGISTRY;
  JSONArray registry=new JSONArray();
  boolean usable;
  int scans, metadataWrites, registryWrites, enrichments;
  String rendered="";
  List<File> libraryRoots() { return Collections.singletonList(volume); }
  boolean hasUsableFrontendLibrary() { return usable; }
  String canonical(String path) throws IOException { return new File(path).getCanonicalPath(); }
  void setStatus(String phase,double progress,String message,List<String> titles,int count,boolean reload) {}
  JSONArray readRegistry() { return registry; }
  Set<String> registeredSources(JSONArray rows) {
    Set<String> ids=new HashSet<>();
    for(JSONObject row:rows) ids.add((String)row.values.get("sourceIdentity"));
    return ids;
  }
  List<Candidate> discoverExistingCandidates() {
    scans++;
    List<Candidate> candidates=new ArrayList<>();
    for(File file:volume.listFiles()) if(file.getName().endsWith(".rom")) candidates.add(new Candidate(file));
    return candidates;
  }
  void enrichBundledMetadata(ImportedGame game) { enrichments++; }
  void writeJsonAtomic(File file,JSONArray rows) { registryWrites++; }
  boolean writeMetadata(JSONArray rows) {
    StringBuilder next=new StringBuilder();
    for(JSONObject row:rows) {
      File file=(File)row.values.get("file");
      if(file.isFile()) next.append(file).append('\n');
    }
    usable=next.length()>0;
    boolean changed=!rendered.equals(next.toString());
    if(changed) { metadataWrites++; rendered=next.toString(); }
    return changed;
  }
  static void check(boolean value,String message) { if(!value) throw new AssertionError(message); }
  public static void main(String[] args) throws Exception {
    BootstrapProbe p=new BootstrapProbe(); p.volume=new File(args[0]);
    p.REGISTRY=new File(p.volume,"registry.json");
    File first=new File(p.volume,"First.rom"); Files.writeString(first.toPath(),"first-owned-rom");
    check(p.bootstrapLocalLibrary(),"first game not published");
    check(p.registry.size()==1 && p.metadataWrites==1,"first game not indexed exactly once");
    JSONObject existing=p.registry.get(0); existing.put("ownerNote","preserve");
    File second=new File(p.volume,"Second.rom"); Files.writeString(second.toPath(),"second-owned-rom");
    check(p.bootstrapLocalLibrary(),"new ROM on unchanged volume was permanently skipped");
    check(p.scans==2 && p.registry.size()==2 && p.metadataWrites==2,
          "reopen did not publish second game");
    check(p.registry.get(0)==existing && "preserve".equals(existing.values.get("ownerNote")),
          "existing registry row overwritten");
    check(!p.bootstrapLocalLibrary(),"unchanged library requested another frontend restart");
    check(p.registry.size()==2 && p.metadataWrites==2 && p.registryWrites==2 && p.enrichments==2,
          "unchanged scan duplicated or rewrote games");
    check(Files.readString(first.toPath()).equals("first-owned-rom") &&
          Files.readString(second.toPath()).equals("second-owned-rom"),"discovery modified ROMs");
    // Simulate a removable volume going away and returning. Its existing
    // registry identity is preserved; neither transition adds a registry row.
    Path hidden=first.toPath().resolveSibling("First.detached");
    Files.move(first.toPath(),hidden);
    check(p.bootstrapLocalLibrary(),"removed registered ROM did not refresh remaining library");
    check(!p.rendered.contains("First.rom") && p.registry.size()==2,
          "removal either stayed visible or discarded the durable registry row");
    check(!p.bootstrapLocalLibrary(),"unchanged detached volume caused a restart loop");
    Files.move(hidden,first.toPath());
    check(p.bootstrapLocalLibrary(),"returning registered ROM not republished");
    check(p.rendered.contains("First.rom") && p.registry.size()==2,
          "returning ROM missing or duplicated");
    check(!p.bootstrapLocalLibrary(),"unchanged restored volume caused a restart loop");
    check(p.metadataWrites==4 && p.registryWrites==2 && p.enrichments==2,
          "reattachment rewrote registry or repeated enrichment");
    System.out.println("same-volume reopen PASS");
  }
''' + bootstrap + '\n}\n'
        with tempfile.TemporaryDirectory(prefix='emufusion-bootstrap-') as temp:
            root = Path(temp)
            android = root / 'android/content'
            android.mkdir(parents=True)
            (android / 'Context.java').write_text('''
package android.content;
public final class Context {
  public static final int MODE_PRIVATE=0;
  final SharedPreferences prefs=new SharedPreferences();
  public SharedPreferences getSharedPreferences(String name,int mode) { return prefs; }
}
''')
            (android / 'SharedPreferences.java').write_text('''
package android.content;
public final class SharedPreferences {
  String value="";
  public String getString(String key,String fallback) { return value.isEmpty()?fallback:value; }
  public SharedPreferences edit() { return this; }
  public SharedPreferences putString(String key,String value) { this.value=value; return this; }
  public boolean commit() { return true; }
}
''')
            unit = root / 'BootstrapProbe.java'
            unit.write_text(harness)
            files = root / 'roms'
            files.mkdir()
            compiled = subprocess.run([str(JAVA/'javac'), '-d', temp, str(unit),
                                      str(android/'Context.java'), str(android/'SharedPreferences.java')],
                                     capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            run = subprocess.run([str(JAVA/'java'), '-cp', temp, 'BootstrapProbe', str(files)],
                                 capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn('same-volume reopen PASS', run.stdout)

    def test_bootstrap_is_local_in_place_and_checkpoints_before_marking_ready(self):
        source = IMPORTER.read_text()
        bootstrap = method(source, 'private boolean bootstrapLocalLibrary(')
        self.assertIn('discoverExistingCandidates()', bootstrap)
        self.assertIn('new ImportedGame(candidate, candidate.source)', bootstrap)
        self.assertIn('row.put("localDiscovery", true)', bootstrap)
        scan = method(source, 'private void runScan(')
        self.assertNotIn('if (!fullDiscovery && row.optBoolean("localDiscovery", false)) continue', scan)
        self.assertIn('mediaPending(row, mediaRefreshAfter())', scan)
        self.assertIn('enrichMediaQueue(imported, registry, cacheRoot, mediaRoot)', scan)
        for forbidden in ('importCandidate(', 'canonicalTitle(', 'enrichBoxArt(',
                          'enrichVideo(', 'reviewArtlessGames(', '.delete(', 'copy('):
            self.assertNotIn(forbidden, bootstrap)
        self.assertLess(bootstrap.index('writeMetadata(registry)'),
                        bootstrap.index('preferences.edit().putString'))
        self.assertNotIn('if (hadLibrary && storageKey.equals', bootstrap)
        self.assertIn('else initialScanStarted.set(false)', bootstrap)
        initial = method(source, 'void startInitialScan(')
        self.assertIn('onInitialLibraryScanFinished(changed)', initial)
        self.assertIn('running.compareAndSet(false, true)', initial)
        self.assertIn('worker.start()', initial)

    def test_completion_does_not_need_a_qml_heartbeat_and_waits_for_theme(self):
        source = APPLICATION.read_text()
        callback = method(source, 'void onInitialLibraryScanFinished(')
        self.assertIn('firstSetupRestartReady |= changed', callback)
        self.assertIn('scheduleFirstSetupRestart()', callback)
        schedule = method(source, 'private void scheduleFirstSetupRestart(')
        self.assertIn('initialLibraryScanFinished', schedule)
        self.assertIn('ThemeInstaller.isFrontendConfigured()', schedule)
        restart = method(source, 'private final Runnable firstSetupRestart = new Runnable()')
        self.assertIn('owner.hasWindowFocus()', restart)
        self.assertIn('InWindowGameHost.tryBeginImportFrontendRestart()', restart)
        self.assertIn('FrontendRestartActivity.createIntent(owner)', restart)
        self.assertIn('ACTION_INITIAL_LIBRARY_SCAN', source)
        self.assertIn('ACTION_INITIAL_LIBRARY_SCAN.equals(intent.getAction())', SERVICE.read_text())

    def test_volume_discovery_uses_android_api_when_storage_listing_is_denied(self):
        roots = method(IMPORTER.read_text(), 'private List<File> libraryRoots(')
        self.assertIn('getStorageVolumes()', roots)
        self.assertIn('volume.getDirectory()', roots)
        self.assertIn('Environment.getExternalStorageDirectory()', roots)

    def test_real_filesystem_metadata_readiness_and_stale_path_deduplication(self):
        source = IMPORTER.read_text()
        methods = '\n'.join(method(source, signature) for signature in (
            'private static boolean hasUsableFrontendLibrary(',
            'private static File readableMetadataRom(',
            'private static Set<String> existingMetadataPaths(',
            'private static Set<String> existingMetadataGameIdentities(',
            'private static List<File> metadataFiles(',
            'private static void addGameIdentities(',
            'private static String field(',
            'private static List<String> splitStanzas(',
            'private static String readText(',
            'private static GameSystems.SystemDef systemFromRomPath('))
        harness = r'''
package com.thorium.preview;
import java.io.*;
import java.nio.file.*;
import java.util.*;
public final class DiscoveryProbe {
  static File PEGASUS, PEGASUS_CONFIG, LUCENT_CONFIG;
  static String canonical(String s) { try { return new File(s).getCanonicalPath(); }
    catch(Exception e) { throw new RuntimeException(e); } }
  static String normalize(String s) { return s.toLowerCase(Locale.US); }
  static String scoreAlias(String s) { return s; }
  static String stem(String s) { int p=s.lastIndexOf('.'); return p<0?s:s.substring(0,p); }
  static void check(boolean b, String m) { if(!b) throw new AssertionError(m); }
  static void write(File f, String s) throws Exception {
    f.getParentFile().mkdirs(); Files.writeString(f.toPath(), s);
  }
  public static void main(String[] args) throws Exception {
    File root = new File(args[0]);
    PEGASUS = new File(root,"shared/pegasus-frontend");
    PEGASUS_CONFIG = new File(root,"foreign-package");
    LUCENT_CONFIG = new File(root,"our-package");
    File own = new File(LUCENT_CONFIG,"metafiles/nes.metadata.pegasus.txt");
    File foreign = new File(PEGASUS_CONFIG,"metafiles/nes.metadata.pegasus.txt");
    File rom = new File(root,"ROMs/nes/Fixture.nes");
    write(rom,"payload");
    check(!hasUsableFrontendLibrary(),"ROM alone is not an indexed library");
    write(foreign,"game: Fixture\nfile: " + rom + "\n");
    check(!hasUsableFrontendLibrary(),"other app's metadata passed readiness");
    write(own,"game: Fixture\nfile: /absent/Games/nes/Fixture.nes\n");
    check(!hasUsableFrontendLibrary(),"stale paths passed readiness");
    check(!existingMetadataPaths().contains("/absent/Games/nes/Fixture.nes"),"stale ROM suppresses discovery");
    write(foreign,"# retired\n");
    check(existingMetadataGameIdentities().isEmpty(),"stale title suppresses replacement path");
    write(own,"game: Fixture\nfile: " + own.getParentFile().toPath().relativize(rom.toPath()) + "\n");
    check(hasUsableFrontendLibrary(),"relative ROM path not resolved");
    check(existingMetadataPaths().contains(rom.getCanonicalPath()),"relative ROM was not canonicalized");
    check(existingMetadataGameIdentities().contains("nes|fixture"),"readable title not deduplicated");
    check(Files.readString(rom.toPath()).equals("payload"),"discovery modified ROM");
    System.out.println("discovery filesystem PASS");
  }
''' + methods + '\n}\n'
        with tempfile.TemporaryDirectory(prefix='emufusion-discovery-') as temp:
            unit = Path(temp) / 'DiscoveryProbe.java'
            unit.write_text(harness)
            catalog = ROOT / 'android-companion/src/com/thorium/preview/GameSystems.java'
            subprocess.run([str(JAVA/'javac'), '-d', temp, str(unit), str(catalog)],
                           check=True, capture_output=True, text=True)
            run = subprocess.run([str(JAVA/'java'), '-cp', temp,
                                  'com.thorium.preview.DiscoveryProbe', temp],
                                 check=True, capture_output=True, text=True)
            self.assertIn('discovery filesystem PASS', run.stdout)


if __name__ == '__main__':
    unittest.main()
