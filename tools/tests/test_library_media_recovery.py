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
            'private static boolean hasMedia(',
            'private static boolean definitiveMiss(',
            'private static boolean readableMedia('))
        # The real declarations, each up to its terminating semicolon.
        constants = '\n'.join(
            source[source.index(name):].split(';', 1)[0] + ';' for name in (
                'static final String MEDIA_SOURCE_SET =',
                'private static final long DEFINITIVE_MISS_MS =',
                'private static final String[] MEDIA_KINDS ='))
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
  JSONObject optJSONObject(String key) {
    Object value=values.get(key); return value instanceof JSONObject ? (JSONObject)value : null;
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
    } else if (mode.equals("recovered-incomplete")) {
      // Thor, 2026-10-11: a game whose provider never had a video, re-marked
      // enrichmentVersion=2 by metadata recovery, was reopened on every
      // 2-minute poll. It must wait for its scheduled retry.
      Files.delete(Paths.get(row.optString("video")));
      row.put("mediaCompletedAt", 0L).put("mediaRetryCount", 3)
         .put("mediaNextRetryAt", System.currentTimeMillis()+4L*3600000L);
      check(!mediaPending(row, 0), "Never-complete recovered game reopened before its retry");
      row.put("mediaNextRetryAt", System.currentTimeMillis()-1);
      check(mediaPending(row, 0), "Due retry must resume");
    } else if (mode.equals("completed-then-lost")) {
      row.put("mediaCompletedAt", System.currentTimeMillis()-1000);
      check(!mediaPending(row, 0), "Intact completed game must not download");
      Files.delete(Paths.get(row.optString("boxArt")));
      check(mediaPending(row, 0), "A once-complete game that lost a file must reopen");
    } else if (mode.equals("definitive-miss")) {
      // Owner, 2026-10-11: every source answered and none has a video. That
      // game is settled; it must not be searched again every week.
      Files.delete(Paths.get(row.optString("video")));
      row.put("mediaCompletedAt", System.currentTimeMillis()-1000)
         .put("mediaNextRetryAt", System.currentTimeMillis()-1);
      check(mediaPending(row, 0), "A missing video with no recorded answer must be searched");
      row.put("mediaMisses", new JSONObject().put("video", new JSONObject()
         .put("sources", MEDIA_SOURCE_SET).put("at", System.currentTimeMillis())));
      check(mediaComplete(row), "A definitive miss settles that media kind");
      row.put("mediaNextRetryAt", Long.MAX_VALUE);
      check(!mediaPending(row, 0), "A definitive miss must not be searched again");
      check(mediaPending(row, System.currentTimeMillis()), "An explicit refresh still asks again");
    } else if (mode.equals("stale-sources-miss")) {
      Files.delete(Paths.get(row.optString("boxArt")));
      row.put("mediaCompletedAt", System.currentTimeMillis()-1000)
         .put("mediaMisses", new JSONObject().put("boxArt", new JSONObject()
         .put("sources", "2025-01-01:libretro").put("at", System.currentTimeMillis())));
      check(!mediaComplete(row), "A miss against an older source set is asked of the new sources");
      check(mediaPending(row, 0), "New sources must be consulted");
    } else if (mode.equals("expired-miss")) {
      Files.delete(Paths.get(row.optString("background")));
      row.put("mediaCompletedAt", System.currentTimeMillis()-1000)
         .put("mediaMisses", new JSONObject().put("background", new JSONObject()
         .put("sources", MEDIA_SOURCE_SET).put("at", System.currentTimeMillis()-DEFINITIVE_MISS_MS-1)));
      check(mediaPending(row, 0), "An expired miss is asked again: catalogs grow");
    } else if (mode.equals("missing-ratings")) {
      row.put("critic", 0).put("mediaCompletedAt", System.currentTimeMillis()-1000);
      check(!mediaComplete(row), "Missing ratings keep the game incomplete");
      row.put("mediaMisses", new JSONObject().put("ratings", new JSONObject()
         .put("sources", MEDIA_SOURCE_SET).put("at", System.currentTimeMillis())));
      check(mediaComplete(row), "Ratings no source has are settled too");
    } else if (mode.equals("legacy-pending")) {
      row.put("mediaVersion", 0);
      check(mediaPending(row, 0), "Legacy rows must join the resumable queue");
    } else throw new AssertionError("Unknown test " + mode);
    System.out.println("PASS " + mode);
  }
''' + constants + '\n' + predicates + '\n}\n')
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
    def test_recovered_incomplete_waits_for_retry(self): self.run_case('recovered-incomplete')
    def test_completed_then_lost_reopens(self): self.run_case('completed-then-lost')
    def test_definitive_miss_is_not_searched_again(self): self.run_case('definitive-miss')
    def test_miss_against_old_sources_is_retried(self): self.run_case('stale-sources-miss')
    def test_expired_miss_is_retried(self): self.run_case('expired-miss')
    def test_missing_ratings_settle_on_definitive_miss(self): self.run_case('missing-ratings')

    def test_only_answered_lookups_record_a_miss(self):
        source = IMPORTER.read_text()
        outcome = source[source.index('private static void recordMediaOutcome('):][:900]
        self.assertIn('if (LibraryHttp.indefiniteFailures() != indefiniteBefore) return;', outcome)
        http = (ROOT / 'android-companion/src/com/thorium/preview/LibraryHttp.java').read_text()
        transfer = http[http.index('private static void transfer('):]
        # 404/410 answer; everything else (timeouts, 5xx, 429, backoff) does not.
        self.assertIn('if (code == 404 || code == 410) {', transfer)
        self.assertEqual(transfer.count('noteIndefiniteFailure();'), 3)
        queue = source[source.index('private boolean enrichMediaQueue('):][:9000]
        self.assertIn('int indefiniteBefore = LibraryHttp.indefiniteFailures();', queue)
        self.assertIn('if (kind != null) recordMediaOutcome(row, kind, indefiniteBefore);', queue)
        self.assertIn('if (row.optLong("mediaRefreshEpoch", 0) < refresh) row.remove("mediaMisses");', queue)

    def test_failing_providers_back_off_and_retries_are_quiet(self):
        source = IMPORTER.read_text()
        self.assertIn('firstDelay << (2 * Math.max(0, Math.min(misses - 1, 8)))', source)
        self.assertIn('Math.min(7L * 86_400_000L,', source)
        self.assertIn('.put("mediaCompletedAt", complete ? System.currentTimeMillis() : 0L)', source)
        self.assertIn('boolean reload = newGames > 0 || mediaChanged || prerequisiteRoutesChanged;', source)
        self.assertIn('next.put("quiet", statusQuiet);', source)
        resume = source[source.index('private final Runnable resumeMedia'):][:900]
        self.assertIn('quietScan = true;', resume)
        # Never compete with the emulator: no quiet pass starts during
        # gameplay, and a running one checkpoints and stops when a game starts.
        self.assertIn('!running.get() && !gameplayActive && networkAvailable()', resume)
        self.assertIn('if (statusQuiet && gameplayActive) {', source)
        service = (ROOT / 'android-companion/src/com/thorium/preview/PreviewService.java').read_text()
        self.assertIn('importManager.setGameplayActive(true);', service)
        self.assertIn('importManager.setGameplayActive(false);', service)


if __name__ == '__main__': unittest.main()
