"""Execute the production PS2 selector and verify both packaged identities."""
import copy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

from tools.tests.test_first_install_startup import JAVA, ROOT, method
from tools.tests.test_engine_artifact_manifest import MODULE as MANIFEST
from tools.tests.test_phase2_apk_verifier import MODULE as APK


class Ps2HostPageVariantsTest(unittest.TestCase):
    def test_actual_selector_uses_exact_matching_pages_and_rejects_bad_variants(self):
        source = (ROOT / 'unified-android/src/com/thorium/preview/game/Phase2QualificationCatalog.java').read_text()
        methods = '\n'.join(method(source, name) for name in (
            'static JSONObject selectPageSizeArtifact(', 'private static JSONObject find('))
        harness = r'''
import java.util.*;
class JSONObject extends HashMap<String,Object> {
  String optString(String k){return containsKey(k)?String.valueOf(get(k)):"";}
  int optInt(String k,int d){return containsKey(k)?((Number)get(k)).intValue():d;}
  JSONArray optJSONArray(String k){return (JSONArray)get(k);}
  JSONObject with(String k,Object v){put(k,v);return this;}
}
class JSONArray extends ArrayList<JSONObject> {
  int length(){return size();} JSONObject optJSONObject(int i){return get(i);}
}
class Log {static void i(String t,String m){}}
public class Ps2PageProbe {
  static final String TAG="test";
  static String normalize(String s){return s.trim().toLowerCase(Locale.US);}
  static void check(boolean x){if(!x)throw new AssertionError();}
  public static void main(String[] a){
    JSONObject base=new JSONObject().with("hostPageSize",4096).with("sourceCommit","abc");
    JSONObject v=new JSONObject().with("hostPageSize",16384).with("sourceCommit","abc")
      .with("fileName","liblucent_core_armsx2_16k.so");
    check(selectPageSizeArtifact("armsx2",base,4096)==base);
    check(selectPageSizeArtifact("armsx2",base,16384)==null);
    JSONArray vs=new JSONArray();vs.add(v);base.put("pageSizeVariants",vs);
    check(selectPageSizeArtifact("armsx2",base,16384)==v);
    check(selectPageSizeArtifact("armsx2",base,4096)==base);
    for(long n:new long[]{-1,0,8192,65536})check(selectPageSizeArtifact("armsx2",base,n)==null);
    vs.add(v);check(selectPageSizeArtifact("armsx2",base,16384)==null);vs.remove(1);
    v.put("fileName","../wrong.so");check(selectPageSizeArtifact("armsx2",base,16384)==null);
    v.put("fileName","liblucent_core_armsx2_16k.so");v.put("sourceCommit","wrong");
    check(selectPageSizeArtifact("armsx2",base,16384)==null);
    check(selectPageSizeArtifact("dolphin",base,16384)==base);
    base.put("hostPageSize",16384);check(selectPageSizeArtifact("armsx2",base,4096)==null);
  }
''' + methods + '\n}\n'
        with tempfile.TemporaryDirectory() as temp:
            unit = Path(temp)/'Ps2PageProbe.java'
            unit.write_text(harness)
            subprocess.run([str(JAVA/'javac'),str(unit)],check=True,capture_output=True)
            subprocess.run([str(JAVA/'java'),'-cp',temp,'Ps2PageProbe'],check=True,capture_output=True)
        self.assertIn('Os.sysconf(OsConstants._SC_PAGESIZE)', source)
        self.assertLess(source.index('artifact = selectPageSizeArtifact'),
                        source.index('InternalEngineCatalog.verifiedSha256(context, core)'))

    def test_manifest_requires_and_hashes_both_ps2_variants(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            registry=root/'registry.json'
            registry.write_text(json.dumps({'engines':[{'id':'armsx2','source':{'commit':'a'*40}}]}))
            (root/'liblucent_core_armsx2.so').write_bytes(b'4k')
            with self.assertRaises(ValueError): MANIFEST.generate(registry,root)
            (root/'liblucent_core_armsx2_16k.so').write_bytes(b'16k')
            artifacts=MANIFEST.generate(registry,root)['artifacts']
            self.assertEqual(len(artifacts),1)
            self.assertEqual(artifacts[0]['hostPageSize'],4096)
            self.assertEqual(artifacts[0]['sha256'],hashlib.sha256(b'4k').hexdigest())
            self.assertEqual(artifacts[0]['pageSizeVariants'][0]['sha256'],hashlib.sha256(b'16k').hexdigest())

    def test_package_gate_rejects_missing_tampered_duplicate_and_mislabelled_variants(self):
        payload=b'16k'; digest=hashlib.sha256(payload).hexdigest()
        variant={'hostPageSize':16384,'fileName':'liblucent_core_armsx2_16k.so',
                 'sourceCommit':'a'*40,'sha256':digest}
        artifact={'hostPageSize':4096,'pageSizeVariants':[variant]}
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,'w') as z:z.writestr('lib/arm64-v8a/'+variant['fileName'],payload)
        with zipfile.ZipFile(buf) as z:
            self.assertEqual(APK.verify_ps2_page_variant(z,artifact,'a'*40,{digest}),[])
            self.assertTrue(APK.verify_ps2_page_variant(z,artifact,'a'*40,set()))
            for key,value in [('hostPageSize',4096),('fileName','wrong.so'),('sourceCommit','b'*40),('sha256','0'*64)]:
                bad=copy.deepcopy(artifact);bad['pageSizeVariants'][0][key]=value
                self.assertTrue(APK.verify_ps2_page_variant(z,bad,'a'*40,{digest}))
            for variants in ([],[variant,variant]):
                self.assertTrue(APK.verify_ps2_page_variant(z,dict(artifact,pageSizeVariants=variants),'a'*40,{digest}))
        empty=io.BytesIO()
        with zipfile.ZipFile(empty,'w'):pass
        with zipfile.ZipFile(empty) as z:self.assertTrue(APK.verify_ps2_page_variant(z,artifact,'a'*40,{digest}))


if __name__ == '__main__': unittest.main()
