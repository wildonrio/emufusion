"""Original ImageReader carrier leases are not fixed-output presentation leases.

Runs the extracted production source-reference, preparation and retirement
methods in the existing native harness. For the lease decisions only the Vulkan
fence query is controlled; fixed-slot state, pointer matches, failure latching
and retirement execute production code. No hardware/cadence proof is claimed.
"""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

from tools.tests.test_lsfg_private_endpoint_pair import fixture_source


CASES = r"""
void setSource(Fixture& f, uint32_t index, State state, AHardwareBuffer* source) {
    auto& slot=f.live_[index];
    slot.state=state;
    slot.sourceLeft=&f.cachedSourceImage(source);
    slot.sourceRight=&f.cachedSourceImage(&right);
    slot.request=request();
    slot.privateProofPrepared=true;
    // Never default a missing/unsubmitted copy fence to SUCCESS. In particular,
    // proof readiness or a later state is not itself a source-copy observation.
    assert(f.deviceFunctions_.status.at(slot.copyFence)==VK_NOT_READY);
}

void stateMatrix() {
    for(State state:{State::CopyQueued,State::PrivateAwaitingReady,
            State::PrivateProofQueued,State::PrivateReady,State::AwaitingReady,
            State::Presented,State::SurfaceProofQueued,
            State::SurfaceDroppedAwaitingReady,State::SurfaceDroppedAwaitingProof,
            State::SurfaceDeliveredAwaitingRelease,State::Abandoned}) {
        Fixture f;setSource(f,0,state,&left);auto& slot=f.live_[0];
        const auto requestBefore=slot.request;
        assert(f.referencesSourceImage(&left) && f.referencesSourceImage(&right));
        assert(!f.fatal_ && slot.state==state);
        f.deviceFunctions_.status.at(slot.copyFence)=VK_SUCCESS;
        assert(!f.referencesSourceImage(&left) && !f.referencesSourceImage(&right));
        // The private proof fence remains pending. Releasing original carriers
        // cannot retire fixed output, destroy identity, or unblock slot reuse.
        assert(slot.state==state && slot.sourceLeft && slot.sourceRight);
        assert(slot.request.presentId==requestBefore.presentId);
        assert(slot.request.left==requestBefore.left && slot.request.right==requestBefore.right);
        assert(f.deviceFunctions_.resets==0 && f.deviceFunctions_.submits==0);
        assert(f.deviceFunctions_.status.at(slot.presentFence)==VK_NOT_READY);
    }
}

void sharedBuffer() {
    Fixture f;setSource(f,0,State::SurfaceDeliveredAwaitingRelease,&left);
    setSource(f,1,State::CopyQueued,&left);
    f.deviceFunctions_.status.at(f.live_[0].copyFence)=VK_SUCCESS;
    assert(f.referencesSourceImage(&left));
    f.deviceFunctions_.status.at(f.live_[1].copyFence)=VK_SUCCESS;
    assert(!f.referencesSourceImage(&left));
    // Carrier reused again while an older fixed output is still displayed.
    setSource(f,2,State::PrivateAwaitingReady,&left);
    assert(f.referencesSourceImage(&left));
    f.deviceFunctions_.status.at(f.live_[2].copyFence)=VK_SUCCESS;
    assert(!f.referencesSourceImage(&left));
    assert(f.live_[0].state==State::SurfaceDeliveredAwaitingRelease);
}

void failClosed() {
    for(bool missing:{false,true}) {
        Fixture f;setSource(f,0,State::CopyQueued,&left);
        if(missing)f.live_[0].copyFence=VK_NULL_HANDLE;
        else f.deviceFunctions_.status.at(f.live_[0].copyFence)=-4;
        rejects([&]{f.referencesSourceImage(&left);});
        assert(f.fatal_ && f.live_[0].sourceLeft && f.live_[0].state==State::CopyQueued);
        const int queries=f.deviceFunctions_.queries;
        rejects([&]{f.referencesSourceImage(&left);});
        assert(f.deviceFunctions_.queries==queries);
    }
    // Do not short-circuit on an earlier pending copy and conceal a failed
    // later copy of the same carrier.
    Fixture f;setSource(f,0,State::CopyQueued,&left);setSource(f,1,State::CopyQueued,&left);
    f.deviceFunctions_.status.at(f.live_[1].copyFence)=-4;
    rejects([&]{f.referencesSourceImage(&left);});assert(f.fatal_);
    assert(f.live_[0].sourceLeft && f.live_[1].sourceLeft);
}

void ignoreUnrelated() {
    Fixture f;auto& idle=f.live_[0];idle.sourceLeft=&f.cachedSourceImage(&left);
    idle.copyFence=VK_NULL_HANDLE;
    setSource(f,1,State::CopyQueued,&other);
    f.deviceFunctions_.status.at(f.live_[1].copyFence)=-4;
    assert(!f.referencesSourceImage(&left) && !f.fatal_);
    assert(f.deviceFunctions_.queries==0);
    rejects([&]{f.referencesSourceImage(nullptr);});assert(!f.fatal_);
}

void fixedRetirementStillRequired() {
    Fixture f;const auto prepared=begin(f);auto& slot=f.live_[prepared.slotIndex];
    // Simulate the copy completed, but the private proof is still using fixed
    // copies. No mocked retirement shortcut or compositor release is involved.
    slot.privateProofPrepared=true;
    slot.state=State::PrivateProofQueued;
    ::close(slot.readySyncFd);slot.readySyncFd=-1;
    f.deviceFunctions_.status.at(slot.copyFence)=VK_SUCCESS;
    f.abandonPrivatePrepared(prepared);
    assert(slot.state==State::Abandoned);
    assert(!f.referencesSourceImage(&left) && !f.referencesSourceImage(&right));
    assert(slot.sourceLeft && slot.sourceRight);
    f.deviceFunctions_.status.at(slot.presentFence)=VK_SUCCESS;
    assert(!f.referencesSourceImage(&left));
    assert(slot.state==State::Idle && !slot.sourceLeft && !slot.sourceRight);
    assert(f.pendingPresentations_==0);
}

void noResetUntilIdle() {
    Fixture f;std::array<Prepared,3> prepared;
    for(auto& p:prepared)p=begin(f);
    for(const auto& p:prepared)f.deviceFunctions_.status.at(f.live_[p.slotIndex].copyFence)=VK_SUCCESS;
    assert(!f.referencesSourceImage(&left));
    const int resets=f.deviceFunctions_.resets,submits=f.deviceFunctions_.submits;
    assert(!f.tryPreparePrivateEndpointPair(&left,&right));
    assert(f.deviceFunctions_.resets==resets && f.deviceFunctions_.submits==submits);
    // Only exact retirement makes the slot eligible for another copy. Its
    // actual preparation method then resets that fence to NOT_READY.
    f.abandonPrivatePrepared(prepared[0]);
    assert(f.live_[prepared[0].slotIndex].state==State::Idle);
    auto reused=f.tryPreparePrivateEndpointPair(&left,&right);assert(reused);
    assert(reused->slotIndex==prepared[0].slotIndex);
    assert(f.deviceFunctions_.status.at(f.live_[reused->slotIndex].copyFence)==VK_NOT_READY);
    assert(f.referencesSourceImage(&left));
    ::close(reused->inputReadySyncFd);
}

int main(int argc,char** argv) {
    assert(argc==2);const std::string name=argv[1];
    if(name=="states")stateMatrix();else if(name=="shared")sharedBuffer();
    else if(name=="errors")failClosed();else if(name=="unrelated")ignoreUnrelated();
    else if(name=="retirement")fixedRetirementStillRequired();
    else if(name=="reuse")noResetUntilIdle();else assert(false);
    std::cout<<"PASS "<<name<<'\n';
}
"""


class SourceCopyLeaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory(prefix="lsfg-source-copy-lease-")
        cls.addClassCleanup(cls.scratch.cleanup)
        directory = Path(cls.scratch.name)
        fixture = fixture_source()
        source = directory / "fixture.cpp"
        source.write_text(fixture[:fixture.index("int main(")] + CASES)
        cls.binary = directory / "fixture"
        result = subprocess.run([
            "c++", "-std=c++20", "-Wall", "-Wextra", "-Werror",
            "-Wno-missing-field-initializers", "-g", "-O1",
            "-fno-omit-frame-pointer", "-fsanitize=address,undefined",
            str(source), "-o", str(cls.binary),
        ], capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    def case(self, name):
        env = dict(os.environ, ASAN_OPTIONS="detect_leaks=0:abort_on_error=1",
                   UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")
        result = subprocess.run([str(self.binary), name], capture_output=True,
                                text=True, timeout=10, env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS " + name, result.stdout)

    def test_exact_copy_fence_controls_all_live_states(self):
        self.case("states")

    def test_repeated_ahb_reuse_requires_every_matching_copy(self):
        self.case("shared")

    def test_missing_or_failed_copy_fence_quarantines_without_releasing(self):
        self.case("errors")

    def test_idle_and_unrelated_slots_do_not_create_source_ownership(self):
        self.case("unrelated")

    def test_abandoned_source_release_does_not_retire_unfinished_fixed_proof(self):
        self.case("retirement")

    def test_copy_fence_is_reset_only_when_retired_slot_reused(self):
        self.case("reuse")


if __name__ == "__main__":
    unittest.main(verbosity=2)
