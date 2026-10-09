"""Execute the actual JNI entry body and prove warmup bypasses guest/PCM callbacks."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(os.environ.get('EMUFUSION_GLES_RESUME_JNI_SOURCE', str(
    ROOT / 'unified-android/native/lucent_libretro_jni.c')))


class GlesResumeEntryTests(unittest.TestCase):
    def test_production_entry_does_not_run_guest_while_warming(self):
        source = SOURCE.read_text()
        name = 'Java_com_thorium_preview_ExperimentalGlesLibretroHost_nativeRunAndPresentStatusGles'
        if name not in source:  # saved fail-before baseline
            name = name.replace('StatusGles', 'Gles')
        start = source.index(name)
        end = source.index('\nJNIEXPORT ', start)
        body = 'jint ' + source[start:end]
        # The two JNI paths share the real context/warmup/guest implementation.
        # Include that production helper rather than substituting a test stub.
        recovery_name = 'Java_com_thorium_preview_ExperimentalGlesLibretroHost_nativeRunWithoutPresentStatusGles'
        recovery_checks = ''
        if 'static jint run_gles_guest_step(' in source:
            helper_start = source.index('static jint run_gles_guest_step(')
            helper_end = source.index('\nJNIEXPORT ', helper_start)
            body = source[helper_start:helper_end] + '\n' + body
            recovery_start = source.index(recovery_name)
            recovery_end = source.index('\nJNIEXPORT ', recovery_start)
            body += '\njint ' + source[recovery_start:recovery_end]
            recovery_checks = r'''
 gate_success=true; gate_ready=false;
 assert(RECOVERY(&env,NULL,1)==0 && guest_runs==2 && real_presents==2);
 gate_ready=true;
 assert(RECOVERY(&env,NULL,1)==1 && guest_runs==3 && real_presents==2);
 gate_success=false;
 assert(RECOVERY(&env,NULL,1)==0 && guest_runs==3 && real_presents==2 && errors==3);
 assert(RECOVERY(&env,NULL,0)==0 && guest_runs==3 && real_presents==2 && errors==4);
'''.replace('RECOVERY', recovery_name)
        harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#define ERROR_SIZE 512
typedef int jboolean;
typedef int jint;
typedef long long jlong;
typedef void *jclass;
#define JNI_TRUE 1
#define JNI_FALSE 0
struct env_callbacks;
typedef const struct env_callbacks *JNIEnv;
struct env_callbacks { int (*ExceptionCheck)(JNIEnv *); };
typedef struct { void *host; void *backend; } lucent_gles_jni_session;
lucent_gles_jni_session session={(void *)1,(void *)2};
int guest_runs, real_presents, errors;
bool gate_ready, gate_success=true, swapped=true;
lucent_gles_jni_session *from_gles_handle(jlong handle) { return handle ? &session : NULL; }
int exception_check(JNIEnv *env) { (void)env; return 0; }
void throw_state(JNIEnv *env, char *error) { (void)env; (void)error; errors++; }
bool lucent_android_gles_prepare_resume(void *b, bool *ready, char *e, size_t n) {
 (void)b; (void)e; (void)n; *ready=gate_ready; return gate_success;
}
bool lucent_retro_run_frame(void *h,char *e,size_t n) {
 (void)h; (void)e; (void)n; guest_runs++; return true;
}
bool lucent_android_gles_present_if_ready(void *b,bool *p,char *e,size_t n) {
 (void)b; (void)e; (void)n; real_presents++; *p=swapped; return true;
}
BODY
int main(void) {
 struct env_callbacks callbacks={exception_check}; JNIEnv env=&callbacks;
 assert(ENTRY(&env,NULL,1)==JNI_FALSE && guest_runs==0 && real_presents==0);
 gate_ready=true;
 assert(ENTRY(&env,NULL,1)==2 && guest_runs==1 && real_presents==1);
 swapped=false;
 assert(ENTRY(&env,NULL,1)==1 && guest_runs==2 && real_presents==2);
 gate_success=false;
 assert(ENTRY(&env,NULL,1)==JNI_FALSE && guest_runs==2 && real_presents==2 && errors==1);
 assert(ENTRY(&env,NULL,0)==JNI_FALSE && guest_runs==2 && errors==2);
RECOVERY_CHECKS
 puts("PASS real JNI entry: warmup has no guest execution or presented/PCM callback; ready/errors keep existing semantics");
}
'''.replace('BODY', body).replace('ENTRY', name).replace('RECOVERY_CHECKS', recovery_checks)
        with tempfile.TemporaryDirectory(prefix='emufusion-resume-entry-') as directory:
            path = Path(directory) / 'test.c'
            path.write_text(harness)
            binary = Path(directory) / 'test'
            subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', str(path), '-o', str(binary)], check=True)
            result = subprocess.run([str(binary)], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            print(result.stdout.strip())


if __name__ == '__main__':
    unittest.main()
