// Exercise the real RPCS3 pointer classes at the erased savestate storage boundary.
#include "util/types.hpp"
#include "util/shared_ptr.hpp"
#include <cassert>
#include <cstdlib>

// The real pointer code's failed-invariant reporting is the only host link stub.
namespace fmt {
[[noreturn]] void raw_verify_error(std::source_location, const char8_t*, usz) {
    std::abort();
}
}

static int destroyed = 0;
struct object {
    int value = 37;
    ~object() { ++destroyed; }
};

int main() {
    using stx::shared_ptr;
    using stx::atomic_ptr;
    auto ptr = stx::make_shared<object>();
    atomic_ptr<object> slot;
    {
        auto callback = [ptr](void* storage) {
#ifdef TEST_BROKEN
            *static_cast<shared_ptr<object>*>(storage) = ptr;
#else
            *static_cast<atomic_ptr<object>*>(storage) = ptr;
#endif
        };
        callback(&slot);
    }
    {
        auto restored = slot.load();
        assert(restored.get() == ptr.get());
        assert(restored->value == 37);
    }
    ptr.reset();
    assert(destroyed == 0);
    slot.reset();
    assert(destroyed == 1);
}
