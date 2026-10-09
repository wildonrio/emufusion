"""Run the real media-pending predicate against files removed after completion."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.tests.test_first_install_startup import JAVA, ROOT, method

IMPORTER = ROOT / 'android-companion/src/com/thorium/preview/ImportManager.java'


class MissingMediaRecoveryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='emufusion-media-recovery-test-')
        folder = Path(cls.temp.name)
        source = IMPORTER.read_text()
        predicates = '\n'.join(method(source, signature) for signature in (
            'private static boolean mediaPending(',
            'private static boolean mediaComplete(',
            'private static boolean readableMedia('))
        harness = folder / 'MediaRecoveryProbe.java'
        harness.write_text(r'''
import java.io.*;
import java.nio.file.*;
import java.util.*;
class JSONObject {
  final Map<String,Object> values = new HashMap<>();
  JSONObject put(String key, Object value) { values.put(key, value); return this; }
  String optString(String key) { return (String)values.getOrDefault(key, ""); }
  int optInt(String key, int fallback) {
    Object value=values.get(key); return value instanceof Number ? ((Number)value).intValue() : fallback;
  }
  long optLong(String key, long fallback) {
    Object value=values.get(key); return value instanceof Number ? ((Number)value).longValue() : fallback;
  }
  double optDouble(String key, double fallback) {
    Object value=values.get(key); return value instanceof Number ? ((Number)value).doubleValue() : fallback;
  }
}
public class MediaRecoveryProbe {
  static void check(boolean condition, String message) {
    if (!condition) throw new AssertionError(message);
  }
  public static void main(String[] args) throws Exception {
    String mode=args[0]; Path root=Paths.get(args[1]);
    JSONObject row=new JSONObject().put("mediaVersion", 1).put("enrichmentVersion", 2)
      .put("mediaStage", 5).put("mediaNextRetryAt", Long.MAX_VALUE).put("critic", 80);
    for (String field : new String[]{"file", "boxArt", "background", "video"}) {
      Path asset=root.resolve(field); Files.write(asset, new byte[2048]);
      row.put(field, asset.toString());
    }
    check(!mediaPending(row, 0), "An intact completed game must not download again");
    if (mode.startsWith("lost-")) {
      String field=mode.substring(5); Path asset=Paths.get(row.optString(field));
      Files.delete(asset);
      check(mediaPending(row, 0), "Deleted " + field + " stuck forever behind completed checkpoint");
      Files.write(asset, new byte[2048]);
      check(!mediaPending(row, 0), "Reinserted/restored media must be reused");
    } else if (mode.equals("truncated")) {
      Files.write(Paths.get(row.optString("video")), new byte[128]);
      check(mediaPending(row, 0), "Truncated media is not complete");
    } else if (mode.equals("provider-backoff")) {
      Files.delete(Paths.get(row.optString("video")));
      row.put("enrichmentVersion", 0).put("mediaNextRetryAt", System.currentTimeMillis()+900000);
      check(!mediaPending(row, 0), "Unavailable-provider backoff must remain bounded");
      row.put("mediaNextRetryAt", System.currentTimeMillis()-1);
      check(mediaPending(row, 0), "Due retries must resume");
    } else if (mode.equals("manual-refresh")) {
      check(mediaPending(row, System.currentTimeMillis()), "Explicit refresh must still redownload");
    } else if (mode.equals("removed-game")) {
      Files.delete(Paths.get(row.optString("file")));
      Files.delete(Paths.get(row.optString("video")));
      check(!mediaPending(row, 0), "A removed ROM must not trigger media downloads");
      check(!mediaPending(null, 0), "A null registry row must not trigger downloads");
    } else if (mode.equals("legacy-pending")) {
      row.put("mediaVersion", 0);
      check(mediaPending(row, 0), "Legacy rows must join the resumable queue");
    } else throw new AssertionError("Unknown test " + mode);
    System.out.println("PASS " + mode);
  }
''' + predicates + '\n}\n')
        subprocess.run([str(JAVA / 'javac'), '-d', cls.temp.name, str(harness)],
                       check=True, capture_output=True, text=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_case(self, mode):
        with tempfile.TemporaryDirectory(prefix='emufusion-media-recovery-files-') as temp:
            result = subprocess.run([str(JAVA / 'java'), '-cp', self.temp.name,
                'MediaRecoveryProbe', mode, temp], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('PASS ' + mode, result.stdout)

    def test_deleted_box_art_requeues_then_reuses_restored_asset(self): self.run_case('lost-boxArt')
    def test_deleted_wallpaper_requeues_then_reuses_restored_asset(self): self.run_case('lost-background')
    def test_deleted_video_requeues_then_reuses_restored_asset(self): self.run_case('lost-video')
    def test_truncated_media_requeues(self): self.run_case('truncated')
    def test_failed_provider_backoff_is_preserved(self): self.run_case('provider-backoff')
    def test_manual_refresh_still_forces_work(self): self.run_case('manual-refresh')
    def test_removed_rom_does_not_trigger_download(self): self.run_case('removed-game')
    def test_old_registry_rows_still_resume(self): self.run_case('legacy-pending')


if __name__ == '__main__': unittest.main()
