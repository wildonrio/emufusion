"""Execute the production cartridge-save restore method before the first frame."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.tests.test_libretro_release_completion import method

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'unified-android/src/com/thorium/preview/game/LibretroEngineSession.java'
JAVA = Path(os.environ.get('JAVA_HOME', '/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home'), 'bin')
SHELL = r'''
import java.io.*;
import java.util.*;
public class CartridgeRestore {
    static final String TAG="test";
    static final int MAX_SAVE_RAM_BYTES=16*1024*1024;
    static class Entry {String id; Entry(String id){this.id=id;}}
    final Entry entry;
    CartridgeRestore(String engine){entry=new Entry(engine);}
    static class Log {static void w(String t,String m){} static void i(String t,String m){}}
    static class DurableBlobStore {
        static byte[] value;
        static byte[] read(File file,int maximum){return value;}
    }
    static class LibretroHost {
        final byte[] memory;
        int frames,writes;
        boolean fail;
        LibretroHost(int capacity){memory=new byte[capacity];Arrays.fill(memory,(byte)0xff);}
        byte[] readSaveRam(){return memory.clone();}
        void runFrame(){frames++;}
        void writeSaveRam(byte[] value)throws Exception{
            if(fail)throw new IOException("write rejected");
            if(value.length!=memory.length)throw new AssertionError("native length mismatch");
            System.arraycopy(value,0,memory,0,value.length);writes++;
        }
    }
    RESTORE
    static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
    public static void main(String[] args)throws Exception{
        String engine=args[0];int size=Integer.parseInt(args[1]),capacity=Integer.parseInt(args[2]);
        boolean permitted=Boolean.parseBoolean(args[3]);
        DurableBlobStore.value=new byte[size];
        for(int i=0;i<size;i++)DurableBlobStore.value[i]=(byte)(i*29+17);
        byte[] original=DurableBlobStore.value.clone();
        LibretroHost core=new LibretroHost(capacity);
        new CartridgeRestore(engine).restoreSaveRam(core,new File("unused"));
        check(Arrays.equals(original,DurableBlobStore.value),"stored bytes mutated");
        if(permitted){
            check(core.writes==1,"valid cartridge save was not restored");
            check(core.frames==0,"game ran before its battery save was restored");
            check(Arrays.equals(original,Arrays.copyOf(core.memory,size)),"saved prefix changed");
            for(int i=size;i<capacity;i++)check(core.memory[i]==(byte)0xff,"padding is not erased memory");
        }else{
            check(core.writes==0,"unqualified size mismatch was accepted");
            check(core.frames==4,"existing bounded fallback changed");
        }
        core=new LibretroHost(size);core.fail=true;
        boolean rejected=false;
        try{new CartridgeRestore(engine).restoreSaveRam(core,new File("unused"));}
        catch(IOException expected){rejected=true;}
        check(rejected,"native write error was hidden");
    }
}
'''


class MgbaSaveBufferRestoreTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='mgba-save-buffer-')
        cls.path = Path(cls.temp.name)
        harness = SHELL.replace('RESTORE', method(SOURCE.read_text(), 'restoreSaveRam'))
        java = cls.path / 'CartridgeRestore.java'
        java.write_text(harness)
        subprocess.run([str(JAVA / 'javac'), '-d', str(cls.path), str(java)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def check_case(self, engine, size, capacity, permitted):
        result = subprocess.run([str(JAVA / 'java'), '-cp', str(self.path),
                                 'CartridgeRestore', engine, str(size), str(capacity),
                                 str(permitted).lower()], text=True, capture_output=True, timeout=5)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_mgba_provisional_buffer_before_any_guest_frame(self):
        for size in (512, 8192, 32768, 65536):
            with self.subTest(size=size):
                self.check_case('mgba', size, 131072, True)

    def test_exact_sizes_and_other_core_behavior(self):
        for engine in ('mgba', 'mesen-s', 'melonds-ds'):
            for size in (8192, 65536, 131072):
                with self.subTest(engine=engine, size=size):
                    self.check_case(engine, size, size, True)

    def test_no_generic_padding_truncation_or_unknown_size(self):
        for engine, size, capacity in (('mesen-s', 65536, 131072),
                                      ('mgba', 65536, 32768),
                                      ('mgba', 60000, 131072),
                                      ('mgba', 512, 65536)):
            with self.subTest(engine=engine, size=size, capacity=capacity):
                self.check_case(engine, size, capacity, False)


if __name__ == '__main__':
    unittest.main()
