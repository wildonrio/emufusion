"""The Lucent -> EmuFusion rename carries saved state across the update.

Runs the real ThemeInstaller and LegacyNames migration methods against a
temporary Pegasus tree laid out as 3.2.39 left it on the Thor, and checks that
the old product name survives only where the migration needs it.
"""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
JAVA = Path(os.environ.get('JAVA_HOME', '/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home'), 'bin')
COMPANION = ROOT / 'android-companion/src/com/thorium/preview'
INSTALLER = (COMPANION / 'ThemeInstaller.java').read_text()
LEGACY = (COMPANION / 'LegacyNames.java').read_text()
JSON_JAR = Path.home() / '.m2/repository/org/json/json'


def method(source, signature):
    start = source.index(signature)
    brace = source.index('{', start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


def constants(source):
    return '\n'.join(line for line in source.splitlines()
                     if re.match(r'\s+(?:public |private )?static final String \w+ =', line))


class LegacyNameMigrationTest(unittest.TestCase):
    def test_old_name_lives_only_in_legacy_names(self):
        # Java package, classes, tags, preferences, files and QML memory keys
        # are renamed; native libraries and engine ABI names are a later phase.
        native = re.compile(r'liblucent_|loadLibrary\("lucent_|lucent_native_|lucent_retro_|'
                            r'lucent_libretro_host|lucent-core-overrides|LUCENT_INCLUDE_PHASE3|'
                            r'eden-lucent-adapter|translucent', re.I)
        offenders = []
        for base in (ROOT / 'unified-android/src', ROOT / 'android-companion/src', ROOT / 'theme'):
            for path in base.rglob('*'):
                if path.suffix not in ('.java', '.qml') or path.name == 'LegacyNames.java':
                    continue
                for number, line in enumerate(path.read_text(errors='replace').splitlines(), 1):
                    if 'lucent' in line.lower() and not native.search(line):
                        offenders.append(f'{path.relative_to(ROOT)}:{number}: {line.strip()}')
        self.assertEqual([], offenders)
        self.assertEqual(1, LEGACY.count('"lucent"'))

    def test_theme_memory_settings_metadata_and_markers_move_once(self):
        bodies = '\n'.join(method(INSTALLER, signature) for signature in (
            'private static void renameIfAbsent(',
            'private static void migrateThemeMemory(',
            'private static void rewriteSelectedTheme(',
            'private static void renameGeneratedMetadata(',
            'private static String readText(',
            'private static void writeText(',
        ))
        marker = method(LEGACY, 'static void moveEngineMarkers(')
        harness = r'''
import java.io.*;
import java.util.*;
public class MigrationProbe {
  static final String TAG="test";
  static File THEME;
  static class Log { static void i(String t,String m){} static void w(String t,String m){} }
  static class LegacyNames {
''' + constants(LEGACY) + '''
  }
  static final String ENGINE_MARKER_PREFIX = LegacyNames.ENGINE_MARKER_PREFIX;
  static class ImportManager { static final String AUTO_METADATA_PREFIX = "99-emufusion-auto-"; }
''' + bodies.replace('org.json.JSONObject', 'Json') + '\n' + marker + r'''
  // Minimal flat JSON object (string/number/boolean values) for the probe.
  static class Json {
    final LinkedHashMap<String,String> values = new LinkedHashMap<>();
    Json() {}
    Json(String text) {
      java.util.regex.Matcher m = java.util.regex.Pattern.compile(
          "\"([^\"]+)\":(\"[^\"]*\"|[^,}]+)").matcher(text);
      while (m.find()) values.put(m.group(1), m.group(2));
    }
    Iterator<String> keys() { return new ArrayList<>(values.keySet()).iterator(); }
    boolean has(String k) { return values.containsKey(k); }
    Object get(String k) { return values.get(k); }
    void put(String k, Object v) { values.put(k, String.valueOf(v)); }
    int length() { return values.size(); }
    public String toString() {
      StringBuilder b = new StringBuilder("{");
      for (Map.Entry<String,String> e : values.entrySet())
        b.append(b.length() > 1 ? "," : "").append('"').append(e.getKey()).append("\":").append(e.getValue());
      return b.append('}').toString();
    }
  }
  static void check(boolean ok, String why) { if (!ok) throw new AssertionError(why); }
  static String read(File f) throws Exception { return new String(java.nio.file.Files.readAllBytes(f.toPath()), "UTF-8"); }
  static void write(File f, String s) throws Exception { f.getParentFile().mkdirs(); java.nio.file.Files.write(f.toPath(), s.getBytes("UTF-8")); }
  public static void main(String[] args) throws Exception {
    File root = new File(args[0]);
    File config = new File(root, "config"), pegasus = new File(root, "pegasus");
    THEME = new File(pegasus, "themes/emufusion");
    File memory = new File(config, "theme_settings");
    write(new File(memory, "lucent.json"),
        "{\"emufusionWidescreenHack\":false,\"lucentFrameGenerationModeV3\":\"auto\",\"lucentSystemLedBrightness\":2,\"thoriumGame\":7}");
    String legacyPath = new File(pegasus, "themes/lucent").getAbsolutePath() + "/";
    write(new File(config, "settings.txt"), "general.theme: " + legacyPath + "\nproviders.androidapps.enabled: false\n");
    File metafiles = new File(config, "metafiles");
    write(new File(metafiles, "99-lucent-auto-gba.metadata.pegasus.txt"), "game: A\n");
    write(new File(metafiles, "99-lucent-auto-gba.metadata.pegasus.txt.bak"), "game: A\n");
    write(new File(metafiles, "owner.metadata.pegasus.txt"), "game: Mine\n");
    File engine = new File(root, "engine-system/armsx2");
    write(new File(engine, ".lucent-runtime-assets"), "rev");
    write(new File(engine, "lucent-core-overrides.txt"), "keep");

    migrateThemeMemory(memory);
    rewriteSelectedTheme(new File(config, "settings.txt"), legacyPath);
    renameGeneratedMetadata(metafiles);
    moveEngineMarkers(new File(root, "engine-system"));

    File current = new File(memory, "emufusion.json");
    check(current.isFile() && !new File(memory, "lucent.json").exists(), "memory file moved");
    Json moved = new Json(read(current));
    check("\"auto\"".equals(moved.get("emufusionFrameGenerationModeV3")), "mode carried");
    check("2".equals(moved.get("emufusionSystemLedBrightness")), "LED carried");
    check("7".equals(moved.get("thoriumGame")) && "false".equals(moved.get("emufusionWidescreenHack")), "others kept");
    check(!moved.has("lucentFrameGenerationModeV3"), "old key dropped");
    check(read(new File(config, "settings.txt")).contains("general.theme: " + THEME.getAbsolutePath() + "/"), "theme path");
    check(new File(metafiles, "99-emufusion-auto-gba.metadata.pegasus.txt").isFile() &&
          new File(metafiles, "99-emufusion-auto-gba.metadata.pegasus.txt.bak").isFile() &&
          !new File(metafiles, "99-lucent-auto-gba.metadata.pegasus.txt").exists() &&
          new File(metafiles, "owner.metadata.pegasus.txt").isFile(), "generated metadata renamed only");
    check(new File(engine, ".emufusion-runtime-assets").isFile() && !new File(engine, ".lucent-runtime-assets").exists() &&
          new File(engine, "lucent-core-overrides.txt").isFile(), "markers renamed only");

    // The previous QML can write old keys once more before the new theme
    // loads; the next start folds them in without overriding newer values.
    write(current, "{\"emufusionFrameGenerationModeV3\":\"auto\",\"lucentFrameGenerationModeV3\":\"off\",\"lucentSoundEffects\":false}");
    migrateThemeMemory(memory);
    Json folded = new Json(read(current));
    check("\"auto\"".equals(folded.get("emufusionFrameGenerationModeV3")), "newer value wins");
    check("false".equals(folded.get("emufusionSoundEffects")) && !folded.has("lucentSoundEffects"), "late key folded");
    long stamp = current.lastModified();
    migrateThemeMemory(memory);
    check(read(current).equals(folded.toString()), "idempotent");
    System.out.println("MIGRATION_OK");
  }
}
'''
        with tempfile.TemporaryDirectory(prefix='legacy-names-') as tmp:
            source = Path(tmp, 'MigrationProbe.java')
            source.write_text(harness)
            built = subprocess.run([str(JAVA / 'javac'), '-d', tmp, str(source)],
                                   capture_output=True, text=True, timeout=60)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            run = subprocess.run([str(JAVA / 'java'), '-cp', tmp, 'MigrationProbe', tmp],
                                 capture_output=True, text=True, timeout=60)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn('MIGRATION_OK', run.stdout)


if __name__ == '__main__':
    unittest.main()
