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
# The aPS3e adapter is still compiled against the pinned former-name header.
LEGACY_ABI_HEADERS = [ROOT / 'unified-android/native/include' / name for name in (
    'lucent_native_adapter.h',)]


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
        # Java package, classes, tags, preferences, files, QML memory keys,
        # packaged engine library names and the engine ABI are all renamed.
        offenders = []
        for base in (ROOT / 'unified-android/src', ROOT / 'unified-android/stubs',
                     ROOT / 'android-companion/src', ROOT / 'theme'):
            for path in base.rglob('*'):
                if path.suffix not in ('.java', '.qml') or path.name == 'LegacyNames.java':
                    continue
                for number, line in enumerate(path.read_text(errors='replace').splitlines(), 1):
                    if re.search(r'(?i)(?<!trans)lucent', line):
                        offenders.append(f'{path.relative_to(ROOT)}:{number}: {line.strip()}')
        self.assertEqual([], offenders)
        self.assertEqual(1, LEGACY.count('"lucent"'))

    def test_native_host_names_former_engine_hooks_in_one_header(self):
        # Prebuilt engines still export their hooks under the former names
        # until each is rebuilt (rename phase C2); only the fallback header
        # and the two ABI headers those engines were compiled against name it.
        native = ROOT / 'unified-android/native'
        allowed = {native / 'include/emufusion_legacy_engine_abi.h'} | set(LEGACY_ABI_HEADERS)
        offenders = []
        for path in native.rglob('*'):
            if not path.is_file() or path in allowed or path.suffix not in (
                    '.c', '.h', '.cpp', '.java', '.sh', '.txt'):
                continue
            for number, line in enumerate(path.read_text(errors='replace').splitlines(), 1):
                if re.search(r'(?i)(?<!trans)lucent', line):
                    offenders.append(f'{path.relative_to(ROOT)}:{number}: {line.strip()}')
        self.assertEqual([], offenders)

    def test_libretro_core_recipes_and_patches_use_the_new_name(self):
        # Rename phase C2b rebuilt every libretro core from renamed recipes and
        # patches, C2c the Cemu and Eden adapters; only aPS3e remains.
        adapters = ('aps3e-',)
        offenders = []
        recipes = [ROOT / 'engines/build_core.sh', ROOT / 'engines/build_scummvm_core.sh']
        recipes += [p for p in (ROOT / 'engines/patches').iterdir() if not p.name.startswith(adapters)]
        for path in recipes:
            for number, line in enumerate(path.read_text(errors='replace').splitlines(), 1):
                if re.search(r'(?i)(?<!trans)lucent', line):
                    offenders.append(f'{path.relative_to(ROOT)}:{number}: {line.strip()}')
        self.assertEqual([], offenders)

    def test_emufusion_abi_headers_are_the_pinned_headers_renamed(self):
        # Same ABI, new names: each EmuFusion header must be exactly the
        # header the prebuilt adapters compiled against, renamed.
        def renamed(text):
            spelling = {'lucent': 'emufusion', 'Lucent': 'EmuFusion', 'LUCENT': 'EMUFUSION'}
            return re.sub(r'(?i)(?<!trans)lucent', lambda m: spelling[m.group(0)], text)
        for legacy in LEGACY_ABI_HEADERS:
            current = legacy.with_name(legacy.name.replace('lucent_', 'emufusion_'))
            self.assertEqual(renamed(legacy.read_text()), current.read_text(), current.name)

    def test_theme_memory_settings_metadata_and_markers_move_once(self):
        bodies = '\n'.join(method(INSTALLER, signature) for signature in (
            'private static void renameIfAbsent(',
            'private static void migrateThemeMemory(',
            'private static void rewriteSelectedTheme(',
            'private static void renameGeneratedMetadata(',
            'private static String readText(',
            'private static void writeText(',
        ))
        marker = '\n'.join(method(LEGACY, signature) for signature in (
            'static void moveEngineMarkers(', 'static void moveSaveMarkers(',
            'private static File[] children(', 'private static void renameMarkers(',
            'private static void renameMarker(',
        ))
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
  static final String CORE_OPTION_OVERRIDES = LegacyNames.CORE_OPTION_OVERRIDES;
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
    write(new File(engine, "pcsx2-keep"), "user data");
    write(new File(engine, "emufusion-core-overrides.txt"), "keep");
    File scummvm = new File(root, "files/engine-saves/scummvm/0123456789abcdef0123456789abcdef");
    write(new File(scummvm, ".lucent-scummvm-00000000000000ab.resume"), "3");
    write(new File(scummvm, "monkey.s03"), "save");
    File qaScummvm = new File(root, "files/engine-saves-qa/session/scummvm/fedcba9876543210fedcba9876543210");
    write(new File(qaScummvm, ".lucent-scummvm-00000000000000cd.resume"), "4");

    migrateThemeMemory(memory);
    rewriteSelectedTheme(new File(config, "settings.txt"), legacyPath);
    renameGeneratedMetadata(metafiles);
    moveEngineMarkers(new File(root, "engine-system"));
    moveSaveMarkers(new File(root, "files"));

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
          new File(engine, "emufusion-core-overrides.txt").isFile(), "markers renamed only");
    check("3".equals(read(new File(scummvm, ".emufusion-scummvm-00000000000000ab.resume"))) &&
          !new File(scummvm, ".lucent-scummvm-00000000000000ab.resume").exists() &&
          "save".equals(read(new File(scummvm, "monkey.s03"))) &&
          new File(qaScummvm, ".emufusion-scummvm-00000000000000cd.resume").isFile(), "save markers renamed only");

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
