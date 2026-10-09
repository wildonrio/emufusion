"""Execute Java ordinal routing and the three production native button maps."""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from tools.tests.test_native_adapter_retirement_completion import member
from tools.tests.test_native_adapter_start_pause import ENV, JAVA
from tools.tests.test_aps3e_axis_release import PREFIX, input_functions

ROOT = Path(__file__).resolve().parents[2]
SESSION = ROOT / 'unified-android/src/com/thorium/preview/game/NativeAdapterEngineSession.java'
PATCHES = ROOT / 'engines/patches'


class NativeStickClicksTest(unittest.TestCase):
    def cpp(self, source):
        with tempfile.TemporaryDirectory(prefix='native-stick-clicks-') as directory:
            path = Path(directory) / 'test.cpp'
            binary = Path(directory) / 'test'
            path.write_text(source)
            subprocess.run(['c++', '-std=c++20', '-Wall', '-Wextra', '-Werror',
                            '-fsanitize=address,undefined', '-I',
                            str(ROOT / 'unified-android/native/include'),
                            str(path), '-o', str(binary)], check=True, capture_output=True)
            result = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_java_routes_clicks_for_all_three_engines_without_changing_old_ordinals(self):
        source = SESSION.read_text()
        constants = '\n'.join(re.findall(r'private static final int PAD_[^;]+;', source))
        body = member(source, 'private int controlOrdinal(')
        harness = '''
import com.thorium.lucent.input.CanonicalControl;
public class ClickRoutes {
 static class Entry { String id; Entry(String id){this.id=id;} }
 Entry entry;
''' + constants + body + '''
 public static void main(String[] args){
  ClickRoutes s=new ClickRoutes();
  for(String engine:new String[]{"aps3e","eden","cemu"}){
   s.entry=new Entry(engine);
   if(s.controlOrdinal(CanonicalControl.L3)!=23 ||
      s.controlOrdinal(CanonicalControl.R3)!=24)
    throw new AssertionError(engine+" missing stick click");
   if(s.controlOrdinal(CanonicalControl.START)!=12 ||
      s.controlOrdinal(CanonicalControl.SELECT)!=13 ||
      s.controlOrdinal(CanonicalControl.SOUTH)!=(engine.equals("aps3e")?0:1) ||
      s.controlOrdinal(CanonicalControl.EAST)!=(engine.equals("aps3e")?1:0) ||
      s.controlOrdinal(null)!=-1) throw new AssertionError("existing control changed");
  }
 }
}
'''
        with tempfile.TemporaryDirectory(prefix='native-click-java-') as directory:
            path = Path(directory) / 'ClickRoutes.java'
            path.write_text(harness)
            canonical = ROOT / 'unified-android/src/com/thorium/lucent/input/CanonicalControl.java'
            subprocess.run([str(JAVA / 'javac'), '-d', directory, str(canonical), str(path)],
                           check=True, capture_output=True, env=ENV)
            result = subprocess.run([str(JAVA / 'java'), '-cp', directory, 'ClickRoutes'],
                                    capture_output=True, text=True, env=ENV)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_ps3_click_press_release_independent_of_axes_and_face_buttons(self):
        source = (PATCHES / 'aps3e-lucent-adapter.cpp').read_text()
        self.cpp(PREFIX + input_functions(source) + r'''
int main(){
 lucent_native_engine engine;
 static_assert(LUCENT_PAD_A==0 && LUCENT_PAD_RSTICK_Y==18 && LUCENT_PAD_SCREEN_VIEW==22);
 for(auto pair : {std::pair{23,19},std::pair{24,22}}){
  auto control=static_cast<lucent_native_control>(pair.first);
  adapter_set_control(&engine,0,LUCENT_PAD_LSTICK_X,-1.f);
  adapter_set_control(&engine,0,LUCENT_PAD_A,1.f);
  adapter_set_control(&engine,0,control,1.f);
  if(ae::values[pair.second]!=255 || ae::values[9]!=255 || ae::values[6]!=255) return 31;
  adapter_set_control(&engine,0,control,0.f);
  if(ae::values[pair.second] || ae::values[9]!=255 || ae::values[6]!=255) return 32;
  unsigned before=ae::calls;
  adapter_set_control(&engine,1,control,1.f);
  if(ae::calls!=before) return 33;
 }
}
''')

    def test_switch_native_click_map(self):
        source = (PATCHES / 'eden-lucent-adapter.cpp').read_text()
        self.cpp('''
#include <cstdint>
#include "lucent_native_adapter.h"
namespace InputCommon { struct VirtualGamepad { enum class VirtualButton {
 ButtonA,ButtonB,ButtonX,ButtonY,StickL,StickR,TriggerL,TriggerR,TriggerZL,TriggerZR,
 ButtonPlus,ButtonMinus,ButtonLeft,ButtonUp,ButtonRight,ButtonDown,ButtonHome
}; }; }
''' + member(source, 'static bool virtual_button_for(') + '''
int main(){
 using VB=InputCommon::VirtualGamepad::VirtualButton;
 VB result{};
 if(!virtual_button_for(static_cast<lucent_native_control>(23),result)||result!=VB::StickL) return 41;
 if(!virtual_button_for(static_cast<lucent_native_control>(24),result)||result!=VB::StickR) return 42;
 if(!virtual_button_for(LUCENT_PAD_A,result)||result!=VB::ButtonA) return 43;
 if(virtual_button_for(LUCENT_PAD_SCREEN_VIEW,result)) return 44;
}
''')

    def test_wiiu_vpad_and_pro_click_map_and_release_membership(self):
        source = (PATCHES / 'cemu-lucent-adapter.cpp').read_text()
        enums = 'kButtonId_' + ',kButtonId_'.join([
            'A','B','X','Y','L','R','ZL','ZR','Plus','Minus','Up','Down','Left','Right',
            'StickL','StickR','Home'])
        self.cpp('''
#include <cstdint>
#include "lucent_native_adapter.h"
using uint64=uint64_t;
''' + 'struct VPADController {enum {' + enums + '};};\n'
            + 'struct ProController {enum {' + enums + '};};\n'
            + member(source, 'bool vpad_button_for(')
            + member(source, 'bool pro_button_for(') + '''
int main(){
 uint64 result;
 if(!vpad_button_for(static_cast<lucent_native_control>(23),result)||result!=VPADController::kButtonId_StickL) return 51;
 if(!vpad_button_for(static_cast<lucent_native_control>(24),result)||result!=VPADController::kButtonId_StickR) return 52;
 if(!pro_button_for(static_cast<lucent_native_control>(23),result)||result!=ProController::kButtonId_StickL) return 53;
 if(!pro_button_for(static_cast<lucent_native_control>(24),result)||result!=ProController::kButtonId_StickR) return 54;
 if(pro_button_for(LUCENT_PAD_HOME,result)||vpad_button_for(LUCENT_PAD_SCREEN_VIEW,result)) return 55;
}
''')
        release = member(source, 'void release_all_controls()')
        digital = re.search(r'kSharedDigital\[\]\s*=\s*\{([^}]+)\}', release).group(1)
        self.assertIn('LUCENT_PAD_L3', digital)
        self.assertIn('LUCENT_PAD_R3', digital)


if __name__ == '__main__':
    unittest.main()
