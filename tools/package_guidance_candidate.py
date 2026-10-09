"""Exact two-literal shader patch atop the measured software-signature build."""
import shutil
import sys
import package_async_signature_candidate as package

package.OUT = package.ROOT / 'docs/qa/guidance-apk-2026-09-16'
package.BASE = package.ROOT / 'docs/qa/software-signature-2026-09-15'
package.BASE_APK = package.BASE / 'async-signature.apk'
package.EXPECTED_BASE_SHA = '8680614375dc38d3a2d69c261527c5dfde84905a170edf6cb961d377e68f0355'
package.EXPECTED_OCCURRENCES = 2
package.OLD = 'uBypassSearch>.5&&uUseTemporalGuide<.5'
package.NEW = package.OLD+'&&uUseReciprocalGuide<.5&&uUseGlobalSeed<.5&&uUseNeighborProposal<.5'

if __name__ == '__main__':
    if sys.argv[1:] == ['--prepare']:
        assert package.sha(package.BASE_APK) == package.EXPECTED_BASE_SHA
        before=(package.BASE/'input/smali'/package.TARGET).read_text()
        assert before.count(package.OLD)==2 and package.NEW not in before
        # Mechanical exact-string rewrite of generated disassembly only.
        shutil.copytree(package.BASE/'input',package.OUT/'input')
        (package.OUT/'input/smali'/package.TARGET).write_text(before.replace(package.OLD,package.NEW))
    elif not sys.argv[1:]:
        package.main()
    else:
        raise SystemExit('Use --prepare, or no arguments after assemble/decode')
