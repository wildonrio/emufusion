"""Real HTTP failure tests plus lifecycle/checkpoint wiring regression guards."""
from pathlib import Path
import http.server
import subprocess
import tempfile
import threading
import time
import unittest

from tools.tests.test_first_install_startup import JAVA, ROOT, method

SOURCE = ROOT / 'android-companion/src/com/thorium/preview/LibraryHttp.java'
IMPORTER = ROOT / 'android-companion/src/com/thorium/preview/ImportManager.java'


class LibraryTransferTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='emufusion-network-test-')
        folder = Path(cls.temp.name)
        unit = folder / 'LibraryHttp.java'
        unit.write_text(SOURCE.read_text())
        harness = folder / 'TransferProbe.java'
        harness.write_text(r'''
package com.thorium.preview;
import java.io.*;
import java.nio.file.*;
import java.util.*;
public final class TransferProbe {
  static byte[] content(int seed) {
    byte[] data=new byte[4096];
    for(int i=0;i<data.length;i++) data[i]=(byte)((i*7+seed)%251);
    return data;
  }
  // A download cut off by its time limit, then asked for again.
  static void resumeCase(String mode, String base, File target) throws Exception {
    String first=base+"/video", second=mode.equals("other-url") ? base+"/other" : first;
    try (LibraryHttp.Scope cut=LibraryHttp.begin(400,0,null)) {
      try { LibraryHttp.download(first,target,1<<20); throw new AssertionError("Not cut off"); }
      catch(IOException expected) {}
    }
    File part=new File(target+".part");
    boolean kept=part.isFile() && part.length()>0;
    if(mode.equals("no-version")) {
      if(kept) throw new AssertionError("A partial without a file version cannot be resumed safely");
      return;
    }
    if(!kept) throw new AssertionError("Cut-off download was not kept");
    int before=LibraryHttp.resumedDownloads();
    try (LibraryHttp.Scope rest=LibraryHttp.begin(5000,0,null)) {
      LibraryHttp.download(second,target,1<<20);
    }
    int seed=mode.equals("resume") ? 1 : mode.equals("resume-changed") ? 2 : 3;
    if(!Arrays.equals(content(seed),Files.readAllBytes(target.toPath())))
      throw new AssertionError("Wrong bytes after "+mode);
    boolean resumed=LibraryHttp.resumedDownloads()!=before;
    if(mode.equals("resume")!=resumed) throw new AssertionError("Resume counted wrongly: "+resumed);
    if(part.exists() || new File(target+".part.origin").exists())
      throw new AssertionError("Partial files left behind");
  }
  public static void main(String[] args) throws Exception {
    String mode=args[0], base=args[1]; File target=new File(args[2]);
    if(mode.startsWith("resume") || mode.equals("other-url") || mode.equals("no-version")) {
      resumeCase(mode,base,target);
      System.out.println("PASS "+mode);
      return;
    }
    int[] progress={0}; long started=System.nanoTime();
    try (LibraryHttp.Scope scope=LibraryHttp.begin(
          mode.equals("deadline") ? 250 : 5000,
          mode.equals("refresh") || mode.equals("truncated") ? System.currentTimeMillis()+100 : 0,
          (host,n,total)->progress[0]++)) {
      if(mode.equals("deadline")) {
        try { LibraryHttp.fetch(base+"/drip",10000); throw new AssertionError("No deadline"); }
        catch(IOException expected) {}
        if((System.nanoTime()-started)/1e6>1500) throw new AssertionError("Deadline too late");
        if(scope.error.isEmpty()) throw new AssertionError("Failure not reported");
      } else if(mode.equals("cooldown")) {
        for(int i=0;i<2;i++) {
          try { LibraryHttp.fetch(base+"/unavailable",10000); throw new AssertionError(); }
          catch(IOException expected) {}
        }
        // A broken source does not block another source in the same queue.
        LibraryHttp.fetch(base.replace("127.0.0.1","localhost")+"/ok",10000);
      } else if(mode.equals("truncated")) {
        byte[] old=Files.readAllBytes(target.toPath());
        try { LibraryHttp.download(base+"/truncated",target,10000); throw new AssertionError(); }
        catch(IOException expected) {}
        if(!Arrays.equals(old,Files.readAllBytes(target.toPath()))) throw new AssertionError("Old media lost");
        if(new File(target+".part").exists()) throw new AssertionError("Partial file leaked");
      } else {
        LibraryHttp.download(base+"/ok",target,10000);
        if(Files.readAllBytes(target.toPath())[0]!='B') throw new AssertionError("No fresh media");
        if(progress[0]<2) throw new AssertionError("No byte progress");
      }
    }
    System.out.println("PASS "+mode);
  }
}
''')
        subprocess.run([str(JAVA/'javac'), '-d', cls.temp.name, str(unit), str(harness)],
                       check=True, capture_output=True, text=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_case(self, mode):
        requests = []
        ranged = []
        state = {'video': 0}

        def content(seed):
            return bytes((i * 7 + seed) % 251 for i in range(4096))

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def resumable(self):
                # /video: version v1, changed to v2 after the first request in
                # the resume-changed case; /other is another file entirely.
                state['video'] += 1
                version = 'v2' if mode == 'resume-changed' and state['video'] > 1 else 'v1'
                seed = 3 if self.path == '/other' else (2 if version == 'v2' else 1)
                data = content(seed)
                tag = '"%s"' % version
                asked = self.headers.get('Range')
                ranged.append((self.path, asked, self.headers.get('If-Range')))
                if asked and self.headers.get('If-Range') == tag:
                    start = int(asked.split('=')[1].rstrip('-'))
                    self.send_response(206)
                    self.send_header('Content-Range', 'bytes %d-%d/%d' % (start, len(data) - 1, len(data)))
                    self.send_header('Content-Length', str(len(data) - start))
                    self.send_header('Content-Type', 'video/mp4')
                    self.send_header('ETag', tag)
                    self.end_headers()
                    self.wfile.write(data[start:])
                    return
                self.send_response(200)
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Content-Type', 'video/mp4')
                if mode != 'no-version':
                    self.send_header('ETag', tag)
                self.end_headers()
                if state['video'] == 1:
                    self.wfile.write(data[:1500])
                    self.wfile.flush()
                    time.sleep(1.5)
                    return
                self.wfile.write(data)

            def do_GET(self):
                requests.append(self.path)
                try:
                    if self.path in ('/video', '/other'):
                        self.resumable()
                        return
                    self.send_response(503 if self.path == '/unavailable' else 200)
                    self.send_header('Content-Type', 'application/octet-stream')
                    self.send_header('Content-Length', '2048')
                    self.end_headers()
                    if self.path == '/drip':
                        for _ in range(40):
                            self.wfile.write(b'B'*32)
                            self.wfile.flush()
                            time.sleep(0.05)
                    elif self.path == '/truncated':
                        self.wfile.write(b'B'*700)
                    else:
                        self.wfile.write(b'B'*2048)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with tempfile.TemporaryDirectory(prefix='emufusion-transfer-target-') as temp:
                target = Path(temp)/'media.bin'
                if mode in ('refresh', 'truncated'):
                    target.write_bytes(b'A'*2048)
                result = subprocess.run([str(JAVA/'java'), '-cp', self.temp.name,
                    'com.thorium.preview.TransferProbe', mode,
                    f'http://127.0.0.1:{server.server_port}', str(target)],
                    capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('PASS', result.stdout)
                if mode == 'cooldown':
                    self.assertEqual(requests.count('/unavailable'), 1)
                    self.assertIn('/ok', requests)
                if mode in ('resume', 'resume-changed'):
                    self.assertEqual(ranged[1], ('/video', 'bytes=1500-', '"v1"'))
                if mode == 'other-url':
                    self.assertEqual(ranged[1], ('/other', None, None))
        finally:
            server.shutdown()
            server.server_close()

    def test_download_reports_progress(self): self.run_case('success')
    def test_trickle_response_has_total_deadline(self): self.run_case('deadline')
    def test_failed_replacement_preserves_existing_media(self): self.run_case('truncated')
    def test_manual_refresh_really_downloads_again(self): self.run_case('refresh')
    def test_unavailable_provider_backs_off_without_blocking_other_provider(self): self.run_case('cooldown')
    # Owner, 2026-10-24: a slow link never finished a preview video in one pass.
    def test_cut_off_download_resumes_where_it_stopped(self): self.run_case('resume')
    def test_changed_file_is_downloaded_whole_again(self): self.run_case('resume-changed')
    def test_partial_of_another_url_is_discarded(self): self.run_case('other-url')
    def test_partial_without_file_version_is_not_kept(self): self.run_case('no-version')


class VideoCandidateTest(unittest.TestCase):
    def test_archive_fallback_requires_full_game_title(self):
        source = IMPORTER.read_text()
        score = method(source, 'private static int archiveCandidateScore(')
        with tempfile.TemporaryDirectory(prefix='emufusion-video-match-') as temp:
            folder = Path(temp)
            harness = folder/'VideoProbe.java'
            harness.write_text('''
import java.util.*;
import com.thorium.emufusion.metadata.TitleMatcher;
class GameSystems { static class SystemDef { String collection="Nintendo Game Boy Advance"; } }
public class VideoProbe {
static String normalize(String s) { return TitleMatcher.normalize(s); }
static String scoreAlias(String s) { return TitleMatcher.compact(s); }
''' + score + '''
public static void main(String[] args) {
  GameSystems.SystemDef gba=new GameSystems.SystemDef();
  if(archiveCandidateScore("Mario Kart: Super Circuit",gba,
      "Mario Kart Tour official gameplay trailer")>=90) throw new AssertionError("Wrong game");
  if(archiveCandidateScore("Mario Kart: Super Circuit",gba,
      "Mario Kart Super Circuit TV Commercial Nintendo Game Boy Advance")<90)
    throw new AssertionError("Exact game rejected");
  if(archiveCandidateScore("Super Mario Bros. 3",null,
      "Super Mario Bros. gameplay NES")>=90) throw new AssertionError("Wrong sequel");
  if(archiveCandidateScore("Mario Kart: Super Circuit",gba,
      "Driv3r _gba(480P).mp4")>=90) throw new AssertionError("Wrong file in mixed item");
  if(archiveCandidateScore("Mario Kart: Super Circuit",gba,
      "Mario Kart Super Circuit TV Commercial 1 Nintendo Game Boy Advance - GBA - 2001(360P).mp4")<90)
    throw new AssertionError("Exact file rejected");
}
}
''')
            matcher = ROOT/'unified-android/src/com/thorium/emufusion/metadata/TitleMatcher.java'
            subprocess.run([str(JAVA/'javac'), '-d', temp, str(matcher), str(harness)],
                           check=True, capture_output=True, text=True)
            subprocess.run([str(JAVA/'java'), '-cp', temp, 'VideoProbe'],
                           check=True, capture_output=True, text=True)
        search = method(source, 'private VideoMatch archiveSearchVideo(')
        self.assertNotIn('substring(0, queryColon)', search)
        self.assertIn('archive-search-v4/', search)
        item = method(source, 'private VideoMatch archiveItemVideo(')
        self.assertIn('if (archiveCandidateScore(title, system, name) < 90) continue;', item)


class MediaQueueWiringTest(unittest.TestCase):
    def test_every_stage_checkpoints_and_retries_without_claiming_missing_assets_complete(self):
        source = IMPORTER.read_text()
        queue = method(source, 'private boolean enrichMediaQueue(')
        self.assertIn('"media-queue/"', queue)
        self.assertIn('row.optInt("mediaStage", 0)', queue)
        self.assertIn('writeTextAtomic(checkpoint, row.toString(2))', queue)
        self.assertIn('"mediaNextRetryAt"', queue)
        self.assertIn('"enrichmentVersion", complete ? 2 : 0', queue)
        self.assertIn('"Progress saved; resumes automatically"', queue)
        self.assertIn('Collections.singletonList(title)', queue)
        self.assertIn('bytes / 1024', queue)
        self.assertIn('mediaPending(row, mediaRefreshAfter())', source)

    def test_sleep_keeps_cpu_only_during_bounded_work_and_releases_in_finally(self):
        source = IMPORTER.read_text()
        queue = method(source, 'private boolean enrichMediaQueue(')
        self.assertIn('PARTIAL_WAKE_LOCK', queue)
        self.assertIn('wake.acquire(budgets[stage] + 10_000L)', queue)
        self.assertIn('if (wake.isHeld()) wake.release()', queue)
        self.assertNotIn('SCREEN_BRIGHT_WAKE_LOCK', source)
        self.assertIn('scheduleMediaResume()', method(source, 'void startInitialScan('))
        self.assertIn('mediaHandler.postDelayed(this, 120_000L)', source)
        self.assertIn('importManager.close()',
                      (ROOT/'android-companion/src/com/thorium/preview/PreviewService.java').read_text())
        self.assertIn('android.permission.WAKE_LOCK', (ROOT/'unified-android/build.sh').read_text())


if __name__ == '__main__': unittest.main()
