"""Execute Cemu's actual touch branch against single- and dual-screen windows."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tools.tests.test_native_adapter_retirement_completion import member
from tools.tests.test_phone_analog_controls import STUBS, JAVA
from tools.tests.test_native_adapter_start_pause import ENV

ROOT = Path(__file__).resolve().parents[2]
ADAPTER = ROOT / 'engines/patches/cemu-lucent-adapter.cpp'


class CemuPhoneScreenTest(unittest.TestCase):
    def compile_cpp(self, harness):
        with tempfile.TemporaryDirectory(prefix='cemu-phone-touch-') as directory:
            cpp = Path(directory) / 'test.cpp'
            cpp.write_text(harness)
            binary = Path(directory) / 'test'
            subprocess.run([shutil.which('clang++'), '-std=c++20', '-fsanitize=address,undefined',
                            '-I', str(ROOT / 'unified-android/native/include'),
                            str(cpp), '-o', str(binary)], check=True, capture_output=True)
            result = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_actual_touch_branch_uses_the_visible_canvas(self):
        source = ADAPTER.read_text()
        start = source.rindex('case LUCENT_PAD_TOUCH_PRESSED:')
        branch = member(source[start:], 'case LUCENT_PAD_TOUCH_PRESSED:')
        body = branch[branch.index('{'):]
        harness = r'''
#include <atomic>
#include <cassert>
#include <mutex>
using sint32 = int;
struct Point { int x=0,y=0; };
struct Mouse { std::mutex m_mutex; Point position; bool left_down=false,left_down_toggle=false; };
struct InputManager {
 Mouse m_pad_mouse,m_main_mouse;
 static InputManager& instance(){static InputManager value;return value;}
};
namespace WindowSystem {
 struct Info { std::atomic<int> phys_width{2400},phys_height{1080};
               std::atomic<int> phys_pad_width{0},phys_pad_height{0}; };
 Info& GetWindowInfo(){static Info value;return value;}
}
struct Engine { float touch_x=.25f,touch_y=.75f; void* pad_window=nullptr; };
void touch(Engine* engine,float value)
''' + body + r'''
int main(){
 Engine engine;
 auto& input=InputManager::instance();
 touch(&engine,1);
 assert(input.m_main_mouse.left_down);
 assert(input.m_main_mouse.position.x==600 && input.m_main_mouse.position.y==810);
 assert(!input.m_pad_mouse.left_down);
 touch(&engine,0);assert(!input.m_main_mouse.left_down && !input.m_main_mouse.left_down_toggle);
 engine.pad_window=&engine;
 WindowSystem::GetWindowInfo().phys_pad_width=1240;
 WindowSystem::GetWindowInfo().phys_pad_height=1080;
 touch(&engine,1);
 assert(input.m_pad_mouse.left_down);
 assert(input.m_pad_mouse.position.x==310 && input.m_pad_mouse.position.y==810);
 assert(!input.m_main_mouse.left_down);
 touch(&engine,0);assert(!input.m_pad_mouse.left_down);
}
'''
        self.compile_cpp(harness)

    def test_actual_view_control_profile_dual_screen_and_local_ownership(self):
        source = ADAPTER.read_text()
        helper = member(source, 'static void set_primary_screen(')
        routing = member(source, 'if (control == LUCENT_PAD_SCREEN_VIEW)')
        self.compile_cpp(r'''
#include <atomic>
#include <cassert>
#include <cmath>
#include <mutex>
#include "lucent_native_adapter.h"
using uint32=uint32_t;
namespace ActiveSettings { bool initialPad=false; bool DisplayDRCEnabled(){return initialPad;} }
namespace WindowSystem {
 enum class PlatformKeyCodes { TAB };
 struct Info { bool tab=false; void set_keystate(uint32,bool v){tab=v;} };
 Info& GetWindowInfo(){static Info value;return value;}
}
struct Mouse { std::mutex m_mutex; bool left_down=false,left_down_toggle=false; };
struct InputManager { Mouse m_main_mouse,m_pad_mouse;
 static InputManager& instance(){static InputManager value;return value;} };
struct lucent_native_engine { void* pad_window=nullptr; bool gamepad_on_primary=false; };
''' + helper + r'''
void dispatch(lucent_native_engine* engine,uint32_t controller_index,
              lucent_native_control control,float value){
''' + routing + r'''
}
int main(){
 static_assert(LUCENT_PAD_TOUCH_PRESSED==21 && LUCENT_PAD_SCREEN_VIEW==22);
 lucent_native_engine engine;
 auto& input=InputManager::instance();
 auto& info=WindowSystem::GetWindowInfo();
 for(bool profile:{false,true}) {
  ActiveSettings::initialPad=profile;
  for(bool requested:{false,true,false,true}) {
   input.m_main_mouse.left_down=input.m_pad_mouse.left_down=true;
   dispatch(&engine,0,LUCENT_PAD_SCREEN_VIEW,requested?1.f:0.f);
   assert(engine.gamepad_on_primary==requested);
   assert((profile^info.tab)==requested);
   assert(!input.m_main_mouse.left_down && !input.m_pad_mouse.left_down);
   dispatch(&engine,1,LUCENT_PAD_SCREEN_VIEW,requested?0.f:1.f);
   assert(engine.gamepad_on_primary==requested); // remote input cannot swap
   dispatch(&engine,0,LUCENT_PAD_SCREEN_VIEW,NAN);
   assert(engine.gamepad_on_primary==requested);
  }
 }
 engine.pad_window=&engine;
 dispatch(&engine,0,LUCENT_PAD_SCREEN_VIEW,1.f);
 assert(!engine.gamepad_on_primary && !info.tab); // physical two-screen route
}
''')

    def test_actual_phone_stylus_and_session_routing(self):
        game = ROOT / 'unified-android/src/com/thorium/preview/game'
        session = (game / 'NativeAdapterEngineSession.java').read_text()
        signatures = ['@Override public boolean canSwitchPrimaryScreen()',
                      '@Override public boolean isGamepadOnPrimary()',
                      '@Override public boolean switchPrimaryScreen()',
                      '@Override public void onPrimaryTouch(',
                      '@Override public void onSecondaryTouch(',
                      'private void releasePhoneTouch()']
        harness = r'''
package com.thorium.preview.game;
import android.view.MotionEvent;
import java.util.*;
import java.util.concurrent.atomic.AtomicBoolean;
interface EngineSession {
 boolean canSwitchPrimaryScreen(); boolean isGamepadOnPrimary(); boolean switchPrimaryScreen();
 void onPrimaryTouch(MotionEvent e,int w,int h); void onSecondaryTouch(float x,float y,boolean p);
}
class Surface { boolean valid=true; boolean isValid(){return valid;} }
class NativeAdapterHost {
 List<float[]> calls=new ArrayList<>();
 void setControl(int player,int control,float value){calls.add(new float[]{player,control,value});}
}
public class PhoneScreenTest implements EngineSession {
 static final int LOCAL_PLAYER=0;
 static class Entry{String id="cemu";} final Entry entry=new Entry();
 NativeAdapterHost host=new NativeAdapterHost();
 Surface secondarySurface;
 boolean started=true,prepared=true,resumeRequested=true,gamepadOnPrimary;
 final AtomicBoolean stopping=new AtomicBoolean(),released=new AtomicBoolean();
 final WiiUPhoneTouch phoneTouch=new WiiUPhoneTouch();
 int relayed;
 void setLocalControl(NativeAdapterHost active,int control,float value){
  relayed++;active.setControl(0,control,value);
 }
 // METHODS
 static void check(boolean ok){if(!ok)throw new AssertionError();}
 static MotionEvent e(int action,int index,int[] ids,float... xy){return new MotionEvent(action,index,ids,xy);}
 static void near(float a,float b){check(Math.abs(a-b)<.0001f);}
 public static void main(String[] args){
  for(int[] size:new int[][]{{1280,720},{2400,1080},{960,720}}) {
   int w=size[0],h=size[1];
   PhoneScreenTest s=new PhoneScreenTest();
   s.onPrimaryTouch(e(0,0,new int[]{7},w*.5f,h*.5f),w,h);
   check(s.host.calls.isEmpty()); // TV has no invisible stylus
   check(s.canSwitchPrimaryScreen() && s.switchPrimaryScreen() && s.isGamepadOnPrimary());
   check(s.relayed==0); // view selection never leaves this device
   near(22,s.host.calls.get(0)[1]);near(1,s.host.calls.get(0)[2]);
   s.onPrimaryTouch(e(0,0,new int[]{7},w*.5f,h*.5f),w,h);
   near(.5f,s.host.calls.get(1)[2]);near(.5f,s.host.calls.get(2)[2]);near(1,s.host.calls.get(3)[2]);
   s.onPrimaryTouch(e(5,1,new int[]{7,9},w*.5f,h*.5f,0,0),w,h);
   s.onPrimaryTouch(e(6,1,new int[]{7,9},w*.5f,h*.5f,0,0),w,h);
   near(1,s.host.calls.get(s.host.calls.size()-1)[2]); // unrelated finger does not lift stylus
   s.onPrimaryTouch(e(2,0,new int[]{7},0,0),w,h);
   if(w!=1280)near(0,s.host.calls.get(s.host.calls.size()-1)[2]); // bars
   s.onPrimaryTouch(e(2,0,new int[]{7},Float.NaN,1),w,h);
   for(float[] call:s.host.calls)check(Float.isFinite(call[2]));
   near(0,s.host.calls.get(s.host.calls.size()-1)[2]);
   s.onPrimaryTouch(e(0,0,new int[]{7},w*.5f,h*.5f),w,h);
   s.releasePhoneTouch();near(0,s.host.calls.get(s.host.calls.size()-1)[2]);
   check(s.switchPrimaryScreen() && !s.isGamepadOnPrimary());
   near(22,s.host.calls.get(s.host.calls.size()-1)[1]);near(0,s.host.calls.get(s.host.calls.size()-1)[2]);
   s.secondarySurface=new Surface();int before=s.host.calls.size();
   check(!s.canSwitchPrimaryScreen() && !s.switchPrimaryScreen());
   s.onPrimaryTouch(e(0,0,new int[]{7},w*.5f,h*.5f),w,h);s.releasePhoneTouch();
   check(s.host.calls.size()==before); // do not cancel physical lower-panel touch
   s.secondarySurface=null;s.entry.id="eden";
   check(!s.canSwitchPrimaryScreen() && !s.switchPrimaryScreen());
   s.entry.id="cemu";s.stopping.set(true);check(!s.switchPrimaryScreen());
  }
 }
}
'''.replace('// METHODS', '\n'.join(member(session, name) for name in signatures))
        with tempfile.TemporaryDirectory(prefix='cemu-phone-java-') as directory:
            root = Path(directory)
            motion = root / 'android/view/MotionEvent.java'
            motion.parent.mkdir(parents=True)
            motion.write_text(STUBS['android/view/MotionEvent.java'])
            main = root / 'PhoneScreenTest.java'
            main.write_text(harness)
            result = subprocess.run([str(JAVA / 'javac'), '--release', '8', '-d', str(root),
                            str(motion), str(game / 'WiiUPhoneTouch.java'), str(main)],
                            env=ENV, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(JAVA / 'java'), '-cp', str(root),
                            'com.thorium.preview.game.PhoneScreenTest'], env=ENV, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_menu_and_lifecycle_use_the_session_contract(self):
        game = ROOT / 'unified-android/src/com/thorium/preview/game'
        host = (game / 'InWindowGameHost.java').read_text()
        menu = member(host, 'private FrameLayout createPauseOverlay()')
        self.assertIn('session.switchPrimaryScreen()) hidePauseMenu()', menu)
        self.assertIn('pauseButtons.add(primaryScreenButton)', menu)
        show = member(host, 'private void showPauseMenu()')
        self.assertIn('session.canSwitchPrimaryScreen()', show)
        self.assertIn('"Switch to TV" : "Switch to GamePad"', show)
        session = (game / 'NativeAdapterEngineSession.java').read_text()
        for name in ('@Override public void pause(', '@Override public void quiesceForExit()',
                     '@Override public void onSecondarySurfaceAvailable('):
            self.assertIn('releasePhoneTouch();', member(session, name))


if __name__ == '__main__':
    unittest.main()
