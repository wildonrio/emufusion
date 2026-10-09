"""Run the real Java disc preflight on constructed WUX/RVZ containers."""
import os
import hashlib
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'unified-android/src/com/thorium/preview/game/DiscImagePreflight.java'
JDK = Path(os.environ.get('JAVA_HOME', '/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home'), 'bin')


class WuxPreflightTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = tempfile.TemporaryDirectory()
        folder = Path(cls.build.name)
        fixture = folder / 'CheckDisc.java'
        fixture.write_text('''
import java.io.File;
import com.thorium.preview.game.DiscImagePreflight;
public class CheckDisc {
    public static void main(String[] args) throws Exception {
        try { DiscImagePreflight.validate(args[0], new File(args[1]));
            System.out.print("valid");
        } catch (DiscImagePreflight.InvalidImageException failure) {
            System.out.print(failure.getMessage());
        }
    }
}
''')
        subprocess.run([str(JDK/'javac'), '--release', '8', '-d', str(folder),
                        str(SOURCE), str(fixture)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.build.cleanup()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.file = Path(self.directory.name) / 'game.WUX'

    def run_disc(self, expected, system='wiiu'):
        result = subprocess.run([str(JDK/'java'), '-Xmx32m', '-cp', self.build.name,
                                 'CheckDisc', system, str(self.file)],
                                text=True, capture_output=True, check=True, timeout=8)
        self.assertIn(expected, result.stdout)

    def chd(self, map_offset=124, metadata=0, map_bytes=16, length=160, version=5):
        self.file = Path(self.directory.name) / 'game.chd'
        header = bytearray(124)
        struct.pack_into('>8sII', header, 0, b'MComprHD', 124, version)
        struct.pack_into('>I', header, 16, 0x63646c7a)
        struct.pack_into('>QQ', header, 40, map_offset, metadata)
        with self.file.open('wb') as output:
            output.write(header)
            if 124 <= map_offset <= length - 16:
                output.seek(map_offset)
                output.write(struct.pack('>I', map_bytes))
            output.truncate(length)

    def test_chd_v5_map_within_file(self):
        self.chd()
        self.run_disc('valid', 'dreamcast')

    def test_chd_truncated_before_map(self):
        self.chd(map_offset=0x367f6e2f)
        self.run_disc('game data is incomplete', 'dreamcast')

    def test_chd_truncated_map_payload_and_metadata(self):
        self.chd(map_bytes=100)
        self.run_disc('compressed map is incomplete', 'dreamcast')
        self.chd(metadata=1000)
        self.run_disc('game data is incomplete', 'dreamcast')

    def test_chd_older_formats_left_to_core(self):
        self.chd(version=4, map_offset=0)
        self.run_disc('valid', 'ps2')

    def wux(self, indices, sector=256, logical=None, length=None):
        logical = len(indices)*sector if logical is None else logical
        header = struct.pack('<III4xQI4x', 0x30585557, 0x1099d02e, sector, logical, 0)
        table = struct.pack('<'+'I'*len(indices), *indices)
        base = ((32+len(table)+sector-1)//sector)*sector
        extent = max((base+i*sector+(logical-n*sector if n==len(indices)-1 else sector)
                      for n,i in enumerate(indices)), default=base)
        with self.file.open('wb') as out:
            out.write(header+table)
            out.truncate(extent if length is None else length)
        return base, extent

    def test_valid_deduplicated_shuffled_and_partial_final_sector(self):
        for indices,logical in [([2,0,2,1],1024),([0],1),([2,0,1],513)]:
            with self.subTest(indices=indices, logical=logical):
                self.wux(indices, logical=logical)
                self.run_disc('valid')

    def test_data_truncation_and_unsigned_indices(self):
        _,end=self.wux([1,0,2])
        with self.file.open('r+b') as out: out.truncate(end-1)
        self.run_disc('game data is incomplete')
        self.wux([0xffffffff], length=512)
        self.run_disc('1099511628032 bytes')

    def test_incomplete_table_and_header(self):
        self.wux([0]*100, length=431)
        self.run_disc('sector table is incomplete')
        self.file.write_bytes(b'WUX0')
        self.run_disc('container header is incomplete')

    def test_header_parameters(self):
        for offset,packed,expected in [
            (0,b'bad!', 'signature'), (4,b'bad!', 'signature'),
            (8,struct.pack('<I',255),'sector size'),
            (8,struct.pack('<I',0x10000000),'sector size'),
            (16,struct.pack('<Q',0),'logical disc size'),
            (16,struct.pack('<Q',1<<63),'logical disc size'),
            (16,struct.pack('<Q',(0xffffffff+1)*256),'sector table length'),
        ]:
            with self.subTest(offset=offset,packed=packed):
                self.wux([0])
                with self.file.open('r+b') as out:
                    out.seek(offset); out.write(packed)
                self.run_disc(expected)

    def test_full_disc_table_streams_across_chunks_without_payload_read(self):
        # A normal-size logical Wii U image needs ~3MB of indices. A sparse
        # 12GB physical extent proves validation doesn't allocate/read payload.
        count=763712
        indices=[0]*count
        indices[-1]=387882
        self.wux(indices, sector=32768)
        self.run_disc('valid')
        with self.file.open('r+b') as out: out.truncate(450756608)
        self.run_disc('12713230336 bytes')

    def test_dispatch_does_not_change_other_systems_or_formats(self):
        self.file.write_bytes(b'not a WUX')
        self.run_disc('valid', system='switch')
        self.file=self.file.with_suffix('.wua')
        self.file.write_bytes(b'not a WUX')
        self.run_disc('valid')

    def test_existing_rvz_validation_still_runs(self):
        self.file=self.file.with_suffix('.rvz')
        secondary=bytes(0xd5)
        header=bytearray(0x48)
        header[:4]=b'RVZ\1'
        struct.pack_into('>I',header,0x0c,len(secondary))
        header[0x10:0x24]=hashlib.sha1(secondary).digest()
        struct.pack_into('>Q',header,0x2c,len(header)+len(secondary))
        header[0x34:]=hashlib.sha1(header[:0x34]).digest()
        self.file.write_bytes(header+secondary)
        self.run_disc('valid',system='gamecube')
        self.file.write_bytes(header+secondary[:-1])
        self.run_disc('container is truncated',system='gamecube')

    def test_native_load_order_and_visible_failure_wiring(self):
        session=(SOURCE.parent/'NativeAdapterEngineSession.java').read_text()
        self.assertLess(session.index('DiscImagePreflight.validate(request.systemId, game)'),
                        session.index('new NativeAdapterHost(entry.coreFile, trusted)'))
        self.assertIn('failure instanceof DiscImagePreflight.InvalidImageException',session)
        host=(SOURCE.parent/'InWindowGameHost.java').read_text()
        body=host.split('private void showFatalError(String message, boolean runtimeFailure)',1)[1]
        body=body.split('private void explainUnavailable',1)[0]
        self.assertLess(body.index('BootVideoOverlay.finish();'),body.index('status.setText('))
        self.assertNotIn('gameplayPresented = true',body)


if __name__ == '__main__':
    unittest.main()
