"""Embedded CPU policy and real ARM64 fastmem-emitter boundary tests.

The executable test uses the vendored emitter function and its actual Oaknut
assembler, not a Python model of address checks. It does not execute a whole
guest, driver, or emulator and cannot attribute an observed device heap failure.
"""
import platform
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
TREE = ROOT / "engines/build/switch-src/eden"
ADAPTER = ROOT / "engines/patches/eden-lucent-adapter.cpp"
EMITTER = TREE / "src/dynarmic/src/dynarmic/backend/arm64/emit_arm64_memory.cpp"


class EdenCpuMemoryPolicyTest(unittest.TestCase):
    def test_embedded_load_selects_accurate_before_initialization(self):
        source = ADAPTER.read_text()
        load = source[source.index("static bool adapter_load("):]
        load = load[:load.index("engine_session.InitializeEmulation(")]
        settings = re.findall(
            r"Settings::values\.(cpu_backend|cpu_accuracy)\.SetValue\("
            r"Settings::(?:CpuBackend|CpuAccuracy)::(\w+)\);", load)
        self.assertEqual([("cpu_backend", "Dynarmic"), ("cpu_accuracy", "Accurate")],
                         settings)

    def test_accurate_preserves_actual_guest_address_width(self):
        source = (TREE / "src/core/arm/dynarmic/arm_dynarmic_64.cpp").read_text()
        self.assertIn("config.fastmem_address_space_bits = std::uint32_t(address_space_bits);",
                      source)
        self.assertIn("config.silently_mirror_fastmem = false;", source)
        accurate = source.split("case Settings::CpuAccuracy::Accurate:", 1)[1]
        self.assertTrue(accurate.lstrip().startswith("default:\n        break;"))
        self.assertNotIn("fastmem_address_space_bits =", accurate)
        auto = source.split("case Settings::CpuAccuracy::Auto:", 1)[1].split("break;", 1)[0]
        # Negative control describes the prior runtime mode, not the desired one.
        self.assertIn("config.fastmem_address_space_bits = 64;", auto)

    @unittest.skipUnless(platform.machine().lower() in ("arm64", "aarch64"),
                         "requires an ARM64 host to execute emitted instructions")
    def test_real_emitted_bounds_checks_reject_host_canary_access(self):
        compiler = shutil.which("clang++")
        self.assertIsNotNone(compiler, "native compiler required for this qualification test")
        cache = (TREE / "build-android/CMakeCache.txt").read_text()
        oaknut = re.search(r"^oaknut_SOURCE_DIR:STATIC=(.+)$", cache, re.M)
        self.assertIsNotNone(oaknut)
        include = Path(oaknut.group(1)) / "include"
        self.assertTrue((include / "oaknut/oaknut.hpp").is_file())
        source = EMITTER.read_text()
        # Copy the exact standalone lookup plus its helper; no behavior rewrite.
        lookup = source[source.index("inline bool ShouldExt32("):]
        lookup = lookup[:lookup.index("template<std::size_t bitsize>\nvoid FastmemEmitReadMemory")]
        program = r'''
#include <array>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <memory>
#include <utility>
#include <oaknut/code_block.hpp>
#include <oaknut/oaknut.hpp>
using namespace oaknut::util;
using SharedLabel = std::shared_ptr<oaknut::Label>;
// Caller-saved base register for this standalone ABI harness. The production
// emitter uses X25 with its enclosing JIT's callee-save prologue.
constexpr auto Xfastmem = X1;
constexpr auto Xscratch0 = X16;
struct EmitContext {
    struct { std::size_t fastmem_address_space_bits; bool silently_mirror_fastmem; } conf;
};
''' + lookup + r'''
using Probe = std::uint64_t (*)(std::uint64_t, std::uintptr_t, std::uint64_t);
constexpr std::uint64_t rejected = 0xfeed;
struct GeneratedProbe {
    oaknut::CodeBlock memory{4096};
    Probe fn;
    GeneratedProbe(std::size_t bits, bool store) {
        memory.unprotect();
        oaknut::CodeGenerator code{memory.ptr()};
        fn = code.xptr<Probe>();
        EmitContext ctx{{bits, false}};
        const auto fallback = std::make_shared<oaknut::Label>();
        const auto [base, offset] = FastmemEmitVAddrLookup<64>(code, ctx, X0, fallback);
        if (store) {
            code.STR(X2, base, offset);
            code.MOV(X0, X2);
        } else {
            code.LDR(X0, base, offset);
        }
        code.RET();
        code.l(*fallback);
        code.MOV(X0, rejected);
        code.RET();
        memory.protect();
        memory.invalidate_all();
    }
};
int main() {
    std::array<std::uint64_t, 2> owned{0x1234, 0x5678};
    const auto owned_base = reinterpret_cast<std::uintptr_t>(owned.data());
    for (std::size_t bits : {12, 32, 36, 39}) {
        GeneratedProbe read{bits, false}, write{bits, true};
        assert(read.fn(0, owned_base, 0) == owned[0]);
        assert(read.fn(8, owned_base, 0) == owned[1]);
        assert(write.fn(8, owned_base, 0xabcd) == 0xabcd);
        assert(owned[1] == 0xabcd);
        // Controlled host canary. The synthetic base + invalid guest address
        // intentionally resolves to it if the emitted range check is absent.
        for (std::uint64_t address : {std::uint64_t{1} << bits,
                                      (std::uint64_t{1} << bits) + 8,
                                      UINT64_MAX - 7}) {
            std::uint64_t canary = 0x9876;
            const auto base = reinterpret_cast<std::uintptr_t>(&canary) - address;
            assert(read.fn(address, base, 0) == rejected);
            assert(write.fn(address, base, 0xdead) == rejected);
            assert(canary == 0x9876);
        }
    }
    GeneratedProbe unchecked_read{64, false}, unchecked_write{64, true};
    std::uint64_t canary = 0x9876;
    const std::uint64_t address = std::uint64_t{1} << 39;
    const auto base = reinterpret_cast<std::uintptr_t>(&canary) - address;
    assert(unchecked_read.fn(address, base, 0) == 0x9876);
    assert(unchecked_write.fn(address, base, 0xdead) == 0xdead);
    assert(canary == 0xdead);
    std::puts("PASS: real ARM64 emitted read/write bounds; unchecked negative control reaches canary");
}
'''
        with tempfile.TemporaryDirectory(prefix="eden-fastmem-emitter-") as directory:
            path = Path(directory)
            (path / "probe.cpp").write_text(program)
            subprocess.run([compiler, "-std=c++20", "-O2", "-I", str(include),
                            str(path / "probe.cpp"), "-o", str(path / "probe")], check=True)
            result = subprocess.run([str(path / "probe")], capture_output=True,
                                    text=True, check=True, timeout=20)
            self.assertIn("PASS: real ARM64", result.stdout)


if __name__ == "__main__":
    unittest.main()
