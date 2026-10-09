"""Reuse exact-edit APK audit for the software-only classifier branch.

The output filename retains the shared packager's async-signature.apk name;
its parent directory and hash identify this distinct, CPU-path experiment.
The source's richer begin-failure message is not included in this package.
"""
import package_async_signature_candidate as package

package.OUT = package.ROOT / 'docs/qa/software-signature-2026-09-15'
package.OLD = '''    .line 3957
    :cond_9
    iget-boolean p1, p0, Lcom/thorium/preview/game/DisplayFrameGenerator;->densePyramidEnabled:Z

    if-eqz p1, :cond_a

    .line 3965'''
package.NEW = '''    .line 3957
    :cond_9
    iget-boolean p1, p0, Lcom/thorium/preview/game/DisplayFrameGenerator;->densePyramidEnabled:Z

    if-eqz p1, :cond_a

    iget-boolean p1, p0, Lcom/thorium/preview/game/DisplayFrameGenerator;->denseV28ReducedAnalysisRequested:Z

    if-nez p1, :software_gpu_signature

    iget-object p1, p0, Lcom/thorium/preview/game/DisplayFrameGenerator;->externalSignatureTimer:Lcom/thorium/preview/game/DenseGpuTimer;

    if-eqz p1, :cond_a

    :software_gpu_signature

    .line 3965'''

if __name__ == '__main__':
    package.main()
