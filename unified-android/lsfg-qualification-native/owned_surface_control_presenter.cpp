#include "owned_surface_control_presenter.hpp"

#include <android/api-level.h>
#include <android/choreographer.h>
#include <android/log.h>
#include <android/surface_control.h>
#include <android/sync.h>
#include <dlfcn.h>
#include <poll.h>
#include <pthread.h>
#include <sched.h>
#include <sys/resource.h>
#include <time.h>
#include <unistd.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <deque>
#include <map>
#include <mutex>
#include <new>
#include <sstream>
#include <stdexcept>
#include <thread>
#include <utility>
#include <vector>

namespace emufusion::lsfg {

class OwnedSurfaceControlPresenter::Impl final {
public:
    static constexpr std::size_t kMaxFrameTimelines = 8;
    static constexpr uint64_t kMinFrameTimelineSubmissionReserveNs =
            2'000'000ULL;
    static constexpr uint64_t kMaxFrameTimelineTargetErrorNs = 250'000ULL;
    static constexpr uint64_t kMaximumRejectionLogs = 12;
    static constexpr uint64_t kMaximumApplyTailLogs = 12;
    static constexpr uint64_t kMaximumCommitDiagnosticLogs = 12;
    static constexpr uint64_t kApplyTailDiagnosticThresholdNs = 1'000'000ULL;
    static constexpr int kTimedApplyNice = -10;
    static constexpr int kThorTimedApplyCpu = 6;

    struct Pending {
        uint64_t presentId = 0;
        uint64_t desiredPresentTimeNs = 0;
        uint64_t frameTimelineVsyncId = 0;
        uint64_t frameTimelineExpectedNs = 0;
        uint64_t latchTimeNs = 0;
        // Diagnostic copies only. Keep the signed framework sentinel separate
        // from the existing positive-only physical-timing gate below. Copied
        // FD numbers do not own descriptors or authorize buffer reuse.
        int64_t rawCallbackLatchTimeNs = 0;
        uint64_t callbackPreviousPresentId = 0;
        int callbackPreviousReleaseFenceFd = -2;
        uint64_t releaseCallbackPresentId = 0;
        uint64_t frameTimelineDeadlineNs = 0;
        uint64_t frameTimelineRefreshDurationNs = 0;
        uint64_t enqueueNs = 0;
        uint64_t workerDequeueNs = 0;
        uint64_t applyLockAcquiredNs = 0;
        uint64_t transactionApplyStartNs = 0;
        uint64_t transactionApplyEndNs = 0;
        uint64_t transactionApplyCpuStartNs = 0;
        uint64_t transactionApplyCpuEndNs = 0;
        // setBuffer owns the acquire FD before apply submits the transaction.
        // Only a definitely un-applied, deleted transaction may be cancelled.
        bool bufferTransferred = false;
        bool transactionCancelled = false;
        bool applyAttempted = false;
        bool applyReturned = false;
        bool dispatchFailed = false;
        // Callback-observation diagnostics only, not compositor/physical proof.
        // A false snapshot means not observed yet, not that Android had not committed.
        uint64_t commitObservationSerial = 0;
        bool commitCallbackObserved = false;
        uint64_t commitCallbackObservedNs = 0;
        uint64_t dispatchObservedNs = 0;
        uint64_t predecessorPresentId = 0;
        bool predecessorCommitSnapshotKnown = false;
        bool predecessorCommitObservedAtDispatch = false;
        uint64_t predecessorCommitObservedNs = 0;
        uint64_t nextDispatchPresentId = 0;
        uint64_t nextDispatchObservedNs = 0;
        bool commitObservedAtNextDispatch = false;
        uint64_t commitObservedNsAtNextDispatch = 0;
        AHardwareBuffer* buffer = nullptr;
        int presentFenceFd = -2;
        int releaseFenceFd = -2;
        int acquireFenceFd = -2;
        bool callbackReceived = false;
        bool submissionRejected = false;
        bool physicalDelivered = false;
        bool unavailableReported = false;
        bool released = false;
    };

    struct SharedState {
        ~SharedState() {
            for (auto& entry : pending) {
                Pending& row = entry.second;
                if (row.presentFenceFd >= 0) ::close(row.presentFenceFd);
                if (row.releaseFenceFd >= 0) ::close(row.releaseFenceFd);
                if (row.acquireFenceFd >= 0) ::close(row.acquireFenceFd);
                if (row.buffer != nullptr) AHardwareBuffer_release(row.buffer);
            }
        }

        std::mutex mutex;
        std::map<uint64_t, Pending> pending;
        std::deque<uint64_t> scheduled;
        std::condition_variable scheduledCondition;
        uint64_t callbacks = 0;
        uint64_t completed = 0;
        uint64_t dropped = 0;
        uint64_t immediateRejected = 0;
        uint64_t scheduledRejected = 0;
        uint64_t rejectionLogs = 0;
        uint64_t applyTailLogs = 0;
        uint64_t nextCommitObservationSerial = 0;
        uint64_t commitCallbacks = 0;
        uint64_t duplicateCommitCallbacks = 0;
        uint64_t unmatchedCommitCallbacks = 0;
        uint64_t commitCallbacksAfterClose = 0;
        uint64_t commitDiagnosticLogs = 0;
        bool commitObservationAvailable = false;
        uint64_t dispatchFailurePresentId = 0;
        const char* dispatchFailureReason = nullptr; // Static literal, first failure only.
        // One exact last-dispatch record survives pending-row retirement.
        // Do not use an ID high-water: startup IDs are larger than live IDs.
        uint64_t lastCommitPresentId = 0;
        uint64_t lastCommitObservationSerial = 0;
        bool lastCommitCallbackObserved = false;
        uint64_t lastCommitCallbackObservedNs = 0;
        bool closing = false;
        bool workerStarted = false;
        bool workerSchedulingValid = false;
    };

    struct CallbackContext {
        std::shared_ptr<SharedState> state;
        ASurfaceControl* surface = nullptr;
        uint64_t presentId = 0;
        uint64_t previousPresentId = 0;
    };

    struct CommitCallbackContext {
        std::shared_ptr<SharedState> state;
        uint64_t presentId = 0;
        uint64_t observationSerial = 0;
    };

    struct TimelineState {
        using GetInstance = AChoreographer* (*)();
        using PostVsync = void (*)(AChoreographer*,
                AChoreographer_vsyncCallback, void*);
        using GetFrameTime = int64_t (*)(
                const AChoreographerFrameCallbackData*);
        using GetLength = size_t (*)(
                const AChoreographerFrameCallbackData*);
        using GetVsyncId = AVsyncId (*)(
                const AChoreographerFrameCallbackData*, size_t);
        using GetExpected = int64_t (*)(
                const AChoreographerFrameCallbackData*, size_t);
        using GetDeadline = int64_t (*)(
                const AChoreographerFrameCallbackData*, size_t);

        ~TimelineState() {
            if (androidLibrary != nullptr) ::dlclose(androidLibrary);
        }

        std::mutex mutex;
        void* androidLibrary = nullptr;
        AChoreographer* choreographer = nullptr;
        PostVsync postVsync = nullptr;
        GetFrameTime getFrameTime = nullptr;
        GetLength getLength = nullptr;
        GetVsyncId getVsyncId = nullptr;
        GetExpected getExpected = nullptr;
        GetDeadline getDeadline = nullptr;
        std::array<OwnedSurfaceControlPresenter::FrameTimeline,
                kMaxFrameTimelines> timelines{};
        std::size_t count = 0;
        uint64_t callbackSequence = 0;
        uint64_t frameTimeNs = 0;
        bool closing = false;
    };

    struct TimelineCallbackContext {
        std::shared_ptr<TimelineState> state;
    };

    Impl(ANativeWindow* parent, uint32_t bufferWidth, uint32_t bufferHeight)
            : state_(std::make_shared<SharedState>()) {
        if (parent == nullptr || bufferWidth == 0 || bufferHeight == 0)
            throw std::invalid_argument("invalid SurfaceControl parent/geometry");
        if (android_get_device_api_level() < 31)
            throw std::runtime_error("SurfaceControl qualification requires API 31");
        androidLibrary_ = ::dlopen("libandroid.so", RTLD_NOW | RTLD_LOCAL);
        if (androidLibrary_ == nullptr)
            throw std::runtime_error("unable to open libandroid for API 31");
        try {
            acquireSurface_ = reinterpret_cast<AcquireSurface>(
                    ::dlsym(androidLibrary_, "ASurfaceControl_acquire"));
            setBackPressure_ = reinterpret_cast<SetBackPressure>(
                    ::dlsym(androidLibrary_,
                            "ASurfaceTransaction_setEnableBackPressure"));
            setFrameTimeline_ = reinterpret_cast<SetFrameTimeline>(
                    ::dlsym(androidLibrary_,
                            "ASurfaceTransaction_setFrameTimeline"));
            // Optional API31 observation must not add a load-time dependency
            // or change backend availability on older/vendor runtimes.
            setOnCommit_ = reinterpret_cast<SetOnCommit>(
                    ::dlsym(androidLibrary_, "ASurfaceTransaction_setOnCommit"));
            state_->commitObservationAvailable = setOnCommit_ != nullptr;
            if (acquireSurface_ == nullptr || setBackPressure_ == nullptr)
                throw std::runtime_error(
                        "SurfaceControl API 31 entry points unavailable");
            surface_ = ASurfaceControl_createFromWindow(
                    parent, "EmuFusion LSFG owned output");
            if (surface_ == nullptr)
                throw std::runtime_error(
                        "ASurfaceControl_createFromWindow failed");
            source_ = {0, 0, static_cast<int32_t>(bufferWidth),
                       static_cast<int32_t>(bufferHeight)};
            destination_ = {0, 0, ANativeWindow_getWidth(parent),
                            ANativeWindow_getHeight(parent)};
            if (destination_.right <= 0 || destination_.bottom <= 0)
                throw std::runtime_error(
                        "SurfaceControl parent has invalid bounds");
            timedApplyWorker_ = std::thread([this]() { timedApplyWorkerMain(); });
            std::unique_lock<std::mutex> lock(state_->mutex);
            state_->scheduledCondition.wait(lock, [this]() {
                return state_->workerStarted;
            });
            if (!state_->workerSchedulingValid)
                throw std::runtime_error(
                        "SurfaceControl timed-apply worker scheduling failed");
        } catch (...) {
            timedApplyStop_.store(true, std::memory_order_release);
            {
                std::lock_guard<std::mutex> lock(state_->mutex);
                state_->closing = true;
            }
            state_->scheduledCondition.notify_all();
            if (timedApplyWorker_.joinable()) timedApplyWorker_.join();
            if (surface_ != nullptr) ASurfaceControl_release(surface_);
            surface_ = nullptr;
            ::dlclose(androidLibrary_);
            androidLibrary_ = nullptr;
            throw;
        }
    }

    ~Impl() {
        timedApplyStop_.store(true, std::memory_order_release);
        {
            std::lock_guard<std::mutex> lock(state_->mutex);
            state_->closing = true;
        }
        state_->scheduledCondition.notify_all();
        if (timedApplyWorker_.joinable()) timedApplyWorker_.join();
        if (timelineState_ != nullptr) {
            std::lock_guard<std::mutex> lock(timelineState_->mutex);
            timelineState_->closing = true;
        }
        if (surface_ != nullptr) {
            ASurfaceTransaction* transaction = ASurfaceTransaction_create();
            if (transaction != nullptr) {
                ASurfaceTransaction_setVisibility(transaction, surface_,
                        ASURFACE_TRANSACTION_VISIBILITY_HIDE);
                ASurfaceTransaction_apply(transaction);
                ASurfaceTransaction_delete(transaction);
            }
            ASurfaceControl_release(surface_);
            surface_ = nullptr;
        }
        if (androidLibrary_ != nullptr) {
            ::dlclose(androidLibrary_);
            androidLibrary_ = nullptr;
        }
    }

    bool present(AHardwareBuffer* buffer, int acquireFenceFd,
                 uint64_t presentId, uint64_t desiredPresentTimeNs,
                 uint64_t compositorFrameTimelineVsyncId,
                 uint64_t compositorFrameTimelineExpectedNs,
                 uint64_t compositorFrameTimelineDeadlineNs,
                 uint64_t compositorRefreshDurationNs) {
        // The caller transfers this FD on success OR exception. Only an
        // explicit false returns it untouched; JNI therefore never has to
        // guess whether a tokenless apply exception happened before transfer.
        struct EntryFence {
            int fd;
            ~EntryFence() { if (fd >= 0) ::close(fd); }
        } entryFence{acquireFenceFd};
        if (buffer == nullptr || presentId == 0 || desiredPresentTimeNs == 0 ||
                acquireFenceFd < -1 ||
                compositorFrameTimelineVsyncId >
                        static_cast<uint64_t>(INT64_MAX))
            throw std::invalid_argument("invalid SurfaceControl presentation");
        if (compositorFrameTimelineVsyncId != 0) {
            if (compositorFrameTimelineExpectedNs == 0 ||
                    compositorFrameTimelineDeadlineNs == 0 ||
                    compositorFrameTimelineDeadlineNs >=
                            compositorFrameTimelineExpectedNs ||
                    desiredPresentTimeNs >= compositorFrameTimelineExpectedNs ||
                    absoluteDifference(
                            compositorFrameTimelineExpectedNs -
                                    desiredPresentTimeNs,
                            kMinFrameTimelineSubmissionReserveNs) >
                                    kMaxFrameTimelineTargetErrorNs ||
                    compositorRefreshDurationNs == 0 ||
                    compositorRefreshDurationNs > UINT64_MAX -
                            kMinFrameTimelineSubmissionReserveNs)
                throw std::invalid_argument(
                        "SurfaceControl frame timeline identity is invalid");
            const auto timeline = nativeFrameTimeline(
                    compositorFrameTimelineVsyncId);
            if (setFrameTimeline_ == nullptr) {
                const bool result = rejectImmediate(presentId, "frame-timeline-api-missing",
                        compositorFrameTimelineVsyncId,
                        compositorFrameTimelineExpectedNs,
                        compositorFrameTimelineDeadlineNs, std::nullopt,
                        compositorRefreshDurationNs);
                entryFence.fd = -1;
                return result;
            }
            // The newest AChoreographer callback is a rolling prediction
            // snapshot, not a registry of every still-submittable AVsyncId.
            // Absence is therefore not rejection. A still-visible row must
            // exactly corroborate the immutable identity selected by Java.
            // The AChoreographer prediction behind a vsync ID may be revised.
            // EmuFusion selected one immutable (ID, expected, deadline) row;
            // accepting a later deadline for the same token would silently
            // relabel a stale output slot. Fail closed instead.
            if (timeline.has_value() &&
                    (timeline->expectedPresentationTimeNs !=
                            compositorFrameTimelineExpectedNs ||
                    timeline->deadlineNs != compositorFrameTimelineDeadlineNs)) {
                const bool result = rejectImmediate(presentId, "timeline-revised",
                        compositorFrameTimelineVsyncId,
                        compositorFrameTimelineExpectedNs,
                        compositorFrameTimelineDeadlineNs, timeline,
                        compositorRefreshDurationNs);
                entryFence.fd = -1;
                return result;
            }
            const uint64_t nowNs = monotonicNs();
            // AChoreographer's deadline is already one compositor interval
            // plus its app-work reserve ahead of expected presentation. Adding
            // another refresh interval here double-counts the scan and rejects
            // valid buffers that are ready before the immutable deadline.
            const uint64_t openingReserveNs =
                    kMinFrameTimelineSubmissionReserveNs;
            if (compositorFrameTimelineDeadlineNs <= nowNs ||
                    compositorFrameTimelineDeadlineNs - nowNs <
                            openingReserveNs) {
                const bool result = rejectImmediate(presentId, "submission-window-missed",
                        compositorFrameTimelineVsyncId,
                        compositorFrameTimelineExpectedNs,
                        compositorFrameTimelineDeadlineNs, timeline,
                        compositorRefreshDurationNs, nowNs);
                entryFence.fd = -1;
                return result;
            }
        } else if (compositorFrameTimelineExpectedNs != 0 ||
                compositorFrameTimelineDeadlineNs != 0 ||
                compositorRefreshDurationNs != 0) {
            throw std::invalid_argument(
                    "SurfaceControl deadline has no frame timeline");
        }
        const uint64_t enqueueNs = monotonicNs();
        {
            std::lock_guard<std::mutex> lock(state_->mutex);
            throwIfDispatchFailedLocked();
            if (state_->closing || state_->pending.count(presentId) != 0)
                throw std::runtime_error("duplicate or closed SurfaceControl present");
            const auto inserted = state_->pending.emplace(presentId, Pending{
                .presentId = presentId,
                .desiredPresentTimeNs = desiredPresentTimeNs,
                .frameTimelineVsyncId = compositorFrameTimelineVsyncId,
                .frameTimelineExpectedNs =
                        compositorFrameTimelineExpectedNs,
                .frameTimelineDeadlineNs =
                        compositorFrameTimelineDeadlineNs,
                .frameTimelineRefreshDurationNs =
                        compositorRefreshDurationNs,
                .enqueueNs = enqueueNs,
            });
            try {
                if (compositorFrameTimelineVsyncId != 0)
                    state_->scheduled.push_back(presentId);
            } catch (...) {
                state_->pending.erase(inserted.first);
                throw;
            }
            // Finish all throwing clock/container work before accepting either
            // the extra AHB reference or the caller's acquire FD. The worker
            // cannot observe this row until the same mutex is released.
            AHardwareBuffer_acquire(buffer);
            inserted.first->second.buffer = buffer;
            inserted.first->second.acquireFenceFd = acquireFenceFd;
            entryFence.fd = -1;
        }
        if (compositorFrameTimelineVsyncId == 0) {
            try {
                applyScheduled(presentId);
            } catch (...) {
                rollback(presentId, -1);
                throw;
            }
            return true;
        }
        state_->scheduledCondition.notify_all();
        return true;
    }

    void applyScheduled(uint64_t presentId) {
        // Bootstrap/no-token calls arrive on the JNI owner while qualified
        // rows arrive on the timed worker.  SurfaceControl transaction order
        // and previous-release ownership must remain one total order.
        std::lock_guard<std::mutex> applyLock(applyMutex_);
        AHardwareBuffer* buffer = nullptr;
        int acquireFenceFd = -1;
        uint64_t desiredPresentTimeNs = 0;
        uint64_t compositorFrameTimelineVsyncId = 0;
        uint64_t compositorFrameTimelineExpectedNs = 0;
        uint64_t compositorFrameTimelineDeadlineNs = 0;
        {
            std::lock_guard<std::mutex> lock(state_->mutex);
            const auto found = state_->pending.find(presentId);
            if (found == state_->pending.end() || found->second.buffer == nullptr ||
                    found->second.acquireFenceFd < -1)
                throw std::runtime_error(
                        "scheduled SurfaceControl identity disappeared");
            Pending& row = found->second;
            row.applyLockAcquiredNs = monotonicNs();
            buffer = row.buffer;
            acquireFenceFd = row.acquireFenceFd;
            desiredPresentTimeNs = row.desiredPresentTimeNs;
            compositorFrameTimelineVsyncId = row.frameTimelineVsyncId;
            compositorFrameTimelineExpectedNs = row.frameTimelineExpectedNs;
            compositorFrameTimelineDeadlineNs = row.frameTimelineDeadlineNs;
        }

        // A competing bootstrap apply or scheduler preemption may consume the
        // worker's earlier preflight slack. Reject only BEFORE setBuffer takes
        // the acquire FD; after transfer, a late apply still owns a real
        // transaction whose callback/fences must be retained and measured.
        const uint64_t readyToApplyNs = monotonicNs();
        if (compositorFrameTimelineVsyncId != 0 &&
                compositorFrameTimelineDeadlineNs <= readyToApplyNs) {
            rejectScheduled(presentId, "deadline-expired-at-apply",
                    readyToApplyNs, 0, 0);
            return;
        }

        std::unique_ptr<ASurfaceTransaction, decltype(&ASurfaceTransaction_delete)>
                transactionOwner(ASurfaceTransaction_create(), &ASurfaceTransaction_delete);
        ASurfaceTransaction* transaction = transactionOwner.get();
        if (transaction == nullptr)
            throw std::runtime_error("ASurfaceTransaction_create failed");
        auto callback = std::make_unique<CallbackContext>(CallbackContext{
            .state = state_,
            .surface = surface_,
            .presentId = presentId,
            .previousPresentId = lastSubmittedPresentId_,
        });
        std::unique_ptr<ASurfaceControl, decltype(&ASurfaceControl_release)>
                callbackSurface(nullptr, &ASurfaceControl_release);
        std::unique_ptr<CommitCallbackContext> commitCallback(
                setOnCommit_ != nullptr ? new (std::nothrow)
                        CommitCallbackContext{state_, presentId, 0} : nullptr);
        bool applyAttempted = false;
        bool applyReturned = false;
        try {
            if (compositorFrameTimelineVsyncId != 0) {
                const auto latest = nativeFrameTimeline(compositorFrameTimelineVsyncId);
                const uint64_t handoffNs = monotonicNs();
                const bool revised = latest.has_value() &&
                        (latest->expectedPresentationTimeNs !=
                                compositorFrameTimelineExpectedNs ||
                        latest->deadlineNs != compositorFrameTimelineDeadlineNs);
                if (revised || compositorFrameTimelineDeadlineNs <= handoffNs) {
                    transactionOwner.reset();
                    rejectScheduled(presentId, revised ? "timeline-revised-at-handoff" :
                            "deadline-expired-at-handoff", handoffNs,
                            latest.has_value() ? latest->expectedPresentationTimeNs : 0,
                            latest.has_value() ? latest->deadlineNs : 0);
                    return;
                }
            }
            acquireSurface_(surface_);
            callbackSurface.reset(surface_);
            // setBuffer transfers the acquire FD to the Android transaction;
            // it does not itself apply that transaction to SurfaceFlinger.
            {
                std::lock_guard<std::mutex> lock(state_->mutex);
                const auto found = state_->pending.find(presentId);
                if (found == state_->pending.end()) {
                    throw std::runtime_error(
                            "SurfaceControl buffer transfer lost its identity");
                }
                ASurfaceTransaction_setBuffer(
                        transaction, surface_, buffer, acquireFenceFd);
                found->second.acquireFenceFd = -1;
                found->second.bufferTransferred = true;
            }
            ASurfaceTransaction_setGeometry(
                    transaction, surface_, source_, destination_, 0);
            ASurfaceTransaction_setVisibility(transaction, surface_,
                    ASURFACE_TRANSACTION_VISIBILITY_SHOW);
            ASurfaceTransaction_setZOrder(transaction, surface_, 1);
            setBackPressure_(transaction, surface_, true);
            // Select ONE Android timestamp policy. In Android 13,
            // setDesiredPresentTime marks the transaction non-auto-timestamped;
            // SurfaceFlinger then skips both frameIsEarly(vsyncId) and its
            // pending-buffer backpressure check. Combining it with a vsync token
            // can therefore overwrite an uncommitted predecessor despite the
            // backpressure flag (Thor 13d7, real request 3241).
            // Preserve the exact admitted token on a fresh auto-timestamped
            // transaction. Tokenless calibration retains its explicit bound.
            // Physical targets/deadlines and raw-fence qualification do not move.
            if (compositorFrameTimelineVsyncId != 0) {
                setFrameTimeline_(transaction, static_cast<AVsyncId>(
                        compositorFrameTimelineVsyncId));
            } else {
                ASurfaceTransaction_setDesiredPresentTime(
                        transaction, static_cast<int64_t>(desiredPresentTimeNs));
            }
            const uint64_t applyCpuStartNs = threadCpuNs();
            const uint64_t applyStartNs = monotonicNs();
            {
                std::lock_guard<std::mutex> lock(state_->mutex);
                Pending& row = state_->pending.at(presentId);
                throwIfDispatchFailedLocked();
                row.transactionApplyStartNs = applyStartNs;
                row.transactionApplyCpuStartNs = applyCpuStartNs;
                row.applyAttempted = true;
            }
            // From this boundary onward an exception cannot prove non-submission.
            // Android owns callback contexts once apply is attempted; callbacks may
            // run before the call returns. Never reclaim them from a catch path.
            applyAttempted = true;
            ASurfaceTransaction_setOnComplete(
                    transaction, callback.get(), &Impl::onComplete);
            if (commitCallback) {
                // No throwing clock/preflight work remains: a cancelled private
                // transaction must not appear in the predecessor dispatch chain.
                commitCallback->observationSerial = recordCommitDispatch(
                        presentId, callback->previousPresentId);
                setOnCommit_(
                        transaction, commitCallback.get(), &Impl::onCommit);
            }
            lastSubmittedPresentId_ = presentId;
            callback.release();
            callbackSurface.release();
            commitCallback.release();
            ASurfaceTransaction_apply(transaction);
            applyReturned = true;
            const uint64_t applyEndNs = diagnosticMonotonicNs();
            const uint64_t applyCpuEndNs = threadCpuNs();
            Pending diagnostic;
            {
                std::lock_guard<std::mutex> lock(state_->mutex);
                const auto found = state_->pending.find(presentId);
                if (found == state_->pending.end()) {
                    throw std::runtime_error(
                            "SurfaceControl apply lost its presentation identity");
                }
                found->second.applyReturned = true;
                found->second.transactionApplyEndNs = applyEndNs;
                found->second.transactionApplyCpuEndNs = applyCpuEndNs;
                if (applyEndNs == 0 || applyEndNs < applyStartNs)
                    recordDispatchFailureLocked(found->second,
                            "apply-return-clock-unavailable-or-reversed");
                diagnostic = found->second;
                throwIfDispatchFailedLocked();
            }
            transactionOwner.reset();
            logApplyTimingTail(diagnostic);
        } catch (...) {
            if (!applyAttempted) {
                // No apply call was attempted: deletion cancels the private
                // transaction and closes its transferred acquire FD. Contexts
                // and their surface reference are still RAII-owned here.
                transactionOwner.reset();
                std::lock_guard<std::mutex> lock(state_->mutex);
                const auto found = state_->pending.find(presentId);
                if (found != state_->pending.end())
                    found->second.transactionCancelled = true;
            } else {
                std::lock_guard<std::mutex> lock(state_->mutex);
                const auto found = state_->pending.find(presentId);
                if (found != state_->pending.end()) {
                    found->second.applyReturned = applyReturned;
                    recordDispatchFailureLocked(found->second,
                            "apply-exception-after-dispatch");
                }
            }
            throw;
        }
    }

    std::optional<Completion> pollCompletion() {
        std::lock_guard<std::mutex> lock(state_->mutex);
        if (state_->pending.empty()) return std::nullopt;
        pollReleaseFencesLocked();
        throwIfDispatchFailedLocked();
        auto found = std::find_if(state_->pending.begin(), state_->pending.end(),
                [](const auto& entry) {
                    return !entry.second.physicalDelivered;
                });
        if (found == state_->pending.end()) return std::nullopt;
        Pending& row = found->second;
        // Preserve submission order. A later callback cannot prove whether an
        // older transaction presented until the older callback itself arrives.
        // A callback with no fence is reported through the explicit drop path.
        // The callback runs independently of the submitting worker and can
        // arrive before ASurfaceTransaction_apply returns. Keep its fence
        // owned until the apply interval has been published; zero here is
        // unfinished bookkeeping, not a corrupt physical timestamp.
        if (!row.callbackReceived || row.presentFenceFd < 0 ||
                row.transactionApplyEndNs == 0)
            return std::nullopt;
        pollfd descriptor{row.presentFenceFd, POLLIN, 0};
        const int pollResult = ::poll(&descriptor, 1, 0);
        if (pollResult == 0) return std::nullopt;
        if (pollResult != 1 ||
                (descriptor.revents & (POLLIN | POLLERR | POLLHUP)) == 0)
            throw std::runtime_error("SurfaceControl present fence poll failed");
        std::unique_ptr<struct sync_file_info,
                decltype(&sync_file_info_free)> info(
                sync_file_info(row.presentFenceFd), &sync_file_info_free);
        if (!info || info->status != 1 || info->num_fences == 0)
            throw std::runtime_error("SurfaceControl present fence status invalid");
        uint64_t physicalTimestampNs = 0;
        const sync_fence_info* fences = sync_get_fence_info(info.get());
        for (uint32_t index = 0; index < info->num_fences; ++index) {
            if (fences[index].status != 1 || fences[index].timestamp_ns == 0)
                throw std::runtime_error("SurfaceControl child fence invalid");
            physicalTimestampNs = std::max<uint64_t>(
                    physicalTimestampNs, fences[index].timestamp_ns);
        }
        // apply() dispatches asynchronously. SurfaceFlinger may latch and
        // present while this client thread is descheduled before apply returns.
        // Only apply START is a lower bound for that transaction's latch; its
        // end is client bookkeeping, not a compositor milestone. Raw fence and
        // latch timestamps remain mandatory and are never replaced by CPU time.
        if (row.latchTimeNs == 0 || physicalTimestampNs < row.latchTimeNs ||
                row.transactionApplyStartNs == 0 ||
                row.transactionApplyEndNs < row.transactionApplyStartNs ||
                row.latchTimeNs < row.transactionApplyStartNs)
            throw std::runtime_error(
                    "SurfaceControl physical timestamp invalid presentId=" +
                    std::to_string(row.presentId) +
                    " physicalTimestampNs=" + std::to_string(physicalTimestampNs) +
                    " missingLatch=" + std::to_string(row.latchTimeNs == 0) +
                    " presentBeforeLatch=" +
                            std::to_string(physicalTimestampNs < row.latchTimeNs) +
                    " missingApplyStart=" +
                            std::to_string(row.transactionApplyStartNs == 0) +
                    " applyEndBeforeStart=" + std::to_string(
                            row.transactionApplyEndNs < row.transactionApplyStartNs) +
                    " latchBeforeApplyStart=" + std::to_string(
                            row.latchTimeNs < row.transactionApplyStartNs) +
                    " latchBeforeApplyReturn=" + std::to_string(
                            row.latchTimeNs < row.transactionApplyEndNs) +
                    " diagnostics=" + diagnosticJsonLocked());
        Completion completion{
            .presentId = row.presentId,
            .desiredPresentTimeNs = row.desiredPresentTimeNs,
            .latchTimeNs = row.latchTimeNs,
            .actualPresentTimeNs = physicalTimestampNs,
            .rawPresentFenceTimeNs = physicalTimestampNs,
            .frameTimelineDeadlineNs = row.frameTimelineDeadlineNs,
            .transactionApplyStartNs = row.transactionApplyStartNs,
            .transactionApplyEndNs = row.transactionApplyEndNs,
        };
        ::close(row.presentFenceFd);
        row.presentFenceFd = -1;
        row.physicalDelivered = true;
        ++state_->completed;
        return completion;
    }

    std::vector<uint64_t> takeUnavailablePresentFences() {
        std::lock_guard<std::mutex> lock(state_->mutex);
        throwIfDispatchFailedLocked();
        std::vector<uint64_t> result;
        for (auto& entry : state_->pending) {
            Pending& row = entry.second;
            if (row.physicalDelivered) continue;
            if ((!row.callbackReceived && !row.submissionRejected) ||
                    row.presentFenceFd >= 0) break;
            if (!row.unavailableReported) {
                row.unavailableReported = true;
                result.push_back(row.presentId);
                logMissingFenceCommitLocked(row);
            }
        }
        return result;
    }

    void markDropped(uint64_t presentId) {
        std::lock_guard<std::mutex> lock(state_->mutex);
        const auto found = state_->pending.find(presentId);
        if (found == state_->pending.end() ||
                (!found->second.callbackReceived &&
                        !found->second.submissionRejected) ||
                found->second.presentFenceFd >= 0 ||
                !found->second.unavailableReported ||
                found->second.physicalDelivered || found->second.dispatchFailed)
            throw std::runtime_error(
                    "invalid SurfaceControl dropped presentation identity");
        found->second.physicalDelivered = true;
        ++state_->dropped;
    }

    bool isReleased(uint64_t presentId) {
        std::lock_guard<std::mutex> lock(state_->mutex);
        pollReleaseFencesLocked();
        const auto found = state_->pending.find(presentId);
        if (found == state_->pending.end())
            throw std::runtime_error("unknown SurfaceControl presentation release");
        return found->second.released;
    }

    void retire(uint64_t presentId) {
        std::lock_guard<std::mutex> lock(state_->mutex);
        pollReleaseFencesLocked();
        const auto found = state_->pending.find(presentId);
        if (found == state_->pending.end() ||
                !found->second.physicalDelivered || !found->second.released)
            throw std::runtime_error("SurfaceControl presentation retired early");
        closeAndRelease(found->second);
        state_->pending.erase(found);
    }

    std::string diagnosticJson() const {
        std::lock_guard<std::mutex> lock(state_->mutex);
        return diagnosticJsonLocked();
    }

    void enableNativeFrameTimelineSource() {
        if (timelineState_ != nullptr) return;
        if (android_get_device_api_level() < 33 || setFrameTimeline_ == nullptr)
            throw std::runtime_error(
                    "native frame timeline requires Android API 33");
        auto state = std::make_shared<TimelineState>();
        state->androidLibrary = ::dlopen(
                "libandroid.so", RTLD_NOW | RTLD_LOCAL);
        if (state->androidLibrary == nullptr)
            throw std::runtime_error(
                    "unable to open libandroid for native frame timeline");
        const auto getInstance = reinterpret_cast<TimelineState::GetInstance>(
                ::dlsym(state->androidLibrary, "AChoreographer_getInstance"));
        state->postVsync = reinterpret_cast<TimelineState::PostVsync>(
                ::dlsym(state->androidLibrary,
                        "AChoreographer_postVsyncCallback"));
        state->getFrameTime = reinterpret_cast<TimelineState::GetFrameTime>(
                ::dlsym(state->androidLibrary,
                        "AChoreographerFrameCallbackData_getFrameTimeNanos"));
        state->getLength = reinterpret_cast<TimelineState::GetLength>(
                ::dlsym(state->androidLibrary,
                        "AChoreographerFrameCallbackData_getFrameTimelinesLength"));
        state->getVsyncId = reinterpret_cast<TimelineState::GetVsyncId>(
                ::dlsym(state->androidLibrary,
                        "AChoreographerFrameCallbackData_getFrameTimelineVsyncId"));
        state->getExpected = reinterpret_cast<TimelineState::GetExpected>(
                ::dlsym(state->androidLibrary,
                        "AChoreographerFrameCallbackData_getFrameTimelineExpectedPresentationTimeNanos"));
        state->getDeadline = reinterpret_cast<TimelineState::GetDeadline>(
                ::dlsym(state->androidLibrary,
                        "AChoreographerFrameCallbackData_getFrameTimelineDeadlineNanos"));
        if (getInstance == nullptr || state->postVsync == nullptr ||
                state->getFrameTime == nullptr || state->getLength == nullptr ||
                state->getVsyncId == nullptr || state->getExpected == nullptr ||
                state->getDeadline == nullptr)
            throw std::runtime_error(
                    "native frame timeline entry points unavailable");
        state->choreographer = getInstance();
        if (state->choreographer == nullptr)
            throw std::runtime_error(
                    "native frame timeline requires a calling Looper");
        timelineState_ = state;
        postNativeFrameTimelineCallback(state);
    }

    std::vector<OwnedSurfaceControlPresenter::FrameTimeline>
    nativeFrameTimelines(uint64_t* callbackSequence,
                         uint64_t* frameTimeNs) const {
        if (callbackSequence == nullptr || frameTimeNs == nullptr)
            throw std::invalid_argument(
                    "native frame timeline metadata output is absent");
        auto state = timelineState_;
        if (state == nullptr) {
            *callbackSequence = 0;
            *frameTimeNs = 0;
            return {};
        }
        std::lock_guard<std::mutex> lock(state->mutex);
        *callbackSequence = state->callbackSequence;
        *frameTimeNs = state->frameTimeNs;
        return std::vector<OwnedSurfaceControlPresenter::FrameTimeline>(
                state->timelines.begin(), state->timelines.begin() +
                        static_cast<std::ptrdiff_t>(state->count));
    }

    bool supportsFrameTimeline() const {
        return setFrameTimeline_ != nullptr && timelineState_ != nullptr;
    }

    bool canSubmitFrameTimeline(uint64_t vsyncId, uint64_t expectedNs,
                                uint64_t deadlineNs,
                                uint64_t refreshDurationNs) const {
        if (vsyncId == 0 || expectedNs == 0 || deadlineNs == 0 ||
                refreshDurationNs == 0 ||
                refreshDurationNs > UINT64_MAX -
                        kMinFrameTimelineSubmissionReserveNs)
            return false;
        const auto timeline = nativeFrameTimeline(vsyncId);
        if (setFrameTimeline_ == nullptr ||
                (timeline.has_value() &&
                        (timeline->expectedPresentationTimeNs != expectedNs ||
                        timeline->deadlineNs != deadlineNs)))
            return false;
        const uint64_t nowNs = monotonicNs();
        const uint64_t openingReserveNs =
                kMinFrameTimelineSubmissionReserveNs;
        return deadlineNs > nowNs && deadlineNs - nowNs >=
                openingReserveNs;
    }

private:
    bool rejectImmediate(
            uint64_t presentId, const char* reason, uint64_t selectedVsyncId,
            uint64_t selectedExpectedNs, uint64_t selectedDeadlineNs,
            const std::optional<OwnedSurfaceControlPresenter::FrameTimeline>&
                    observed,
            uint64_t refreshDurationNs, uint64_t observedAtNs = 0) {
        if (observedAtNs == 0) observedAtNs = monotonicNs();
        bool logRejection = false;
        {
            std::lock_guard<std::mutex> lock(state_->mutex);
            ++state_->immediateRejected;
            if (state_->rejectionLogs < kMaximumRejectionLogs) {
                ++state_->rejectionLogs;
                logRejection = true;
            }
        }
        if (logRejection) {
            const uint64_t observedExpectedNs = observed.has_value() ?
                    observed->expectedPresentationTimeNs : 0;
            const uint64_t observedDeadlineNs = observed.has_value() ?
                    observed->deadlineNs : 0;
            __android_log_print(ANDROID_LOG_ERROR, "EmuFusionSurfaceControl",
                    "Admission rejected presentId=%llu reason=%s vsyncId=%llu "
                    "selectedExpectedNs=%llu selectedDeadlineNs=%llu "
                    "observedAtNs=%llu observedExpectedNs=%llu "
                    "observedDeadlineNs=%llu refreshNs=%llu reserveNs=%lld",
                    static_cast<unsigned long long>(presentId), reason,
                    static_cast<unsigned long long>(selectedVsyncId),
                    static_cast<unsigned long long>(selectedExpectedNs),
                    static_cast<unsigned long long>(selectedDeadlineNs),
                    static_cast<unsigned long long>(observedAtNs),
                    static_cast<unsigned long long>(observedExpectedNs),
                    static_cast<unsigned long long>(observedDeadlineNs),
                    static_cast<unsigned long long>(refreshDurationNs),
                    static_cast<long long>(selectedDeadlineNs) -
                            static_cast<long long>(observedAtNs));
        }
        return false;
    }

    static uint64_t absoluteDifference(uint64_t left, uint64_t right) {
        return left >= right ? left - right : right - left;
    }

    void timedApplyWorkerMain() {
        pthread_setname_np(pthread_self(), "EmuFusion-SC");
        const bool priorityValid =
                setpriority(PRIO_PROCESS, 0, kTimedApplyNice) == 0 &&
                getpriority(PRIO_PROCESS, 0) <= kTimedApplyNice;
        cpu_set_t affinity;
        CPU_ZERO(&affinity);
        CPU_SET(kThorTimedApplyCpu, &affinity);
        const bool affinityValid = sched_setaffinity(
                0, sizeof(affinity), &affinity) == 0;
        if (!priorityValid || !affinityValid)
            // Best effort (2026-09-03): on the Thor with all eight CPUs
            // online and the app in top-app, the strict check still failed
            // and every LSFG open collapsed to the built-in generator
            // ("SurfaceControl timed-apply worker scheduling failed").  A
            // worker at default priority/affinity is degraded timing, not
            // an invalid transport; the physical present-fence evidence
            // still decides every slot.
            __android_log_print(ANDROID_LOG_WARN, "EmuFusionSurfaceControl",
                    "timed-apply worker scheduling degraded priorityValid=%d "
                    "affinityValid=%d errno=%d nice=%d cpu=%d",
                    priorityValid ? 1 : 0, affinityValid ? 1 : 0, errno,
                    kTimedApplyNice, kThorTimedApplyCpu);
        {
            std::lock_guard<std::mutex> lock(state_->mutex);
            state_->workerSchedulingValid = true;
            state_->workerStarted = true;
        }
        state_->scheduledCondition.notify_all();

        while (true) {
            uint64_t presentId = 0;
            uint64_t expectedNs = 0;
            uint64_t deadlineNs = 0;
            uint64_t vsyncId = 0;
            uint64_t refreshDurationNs = 0;
            {
                std::unique_lock<std::mutex> lock(state_->mutex);
                state_->scheduledCondition.wait(lock, [this]() {
                    return state_->closing || state_->dispatchFailurePresentId != 0 ||
                            !state_->scheduled.empty();
                });
                if (state_->closing || state_->dispatchFailurePresentId != 0) return;
                presentId = state_->scheduled.front();
                state_->scheduled.pop_front();
                const auto found = state_->pending.find(presentId);
                if (found == state_->pending.end()) continue;
                expectedNs = found->second.frameTimelineExpectedNs;
                deadlineNs = found->second.frameTimelineDeadlineNs;
                vsyncId = found->second.frameTimelineVsyncId;
                refreshDurationNs =
                        found->second.frameTimelineRefreshDurationNs;
                found->second.workerDequeueNs = diagnosticMonotonicNs();
            }
            decltype(nativeFrameTimeline(vsyncId)) latestTimeline;
            try {
                if (refreshDurationNs == 0 ||
                        refreshDurationNs > UINT64_MAX -
                                kMinFrameTimelineSubmissionReserveNs) {
                    rejectScheduled(presentId, "refresh-invalid",
                            diagnosticMonotonicNs(), 0, 0);
                    continue;
                }
                // Queue the already-prepared buffer as soon as this FIFO worker
                // can apply it. Waiting until deadline-minus-2ms deliberately
                // discards available slack and cannot cover observed 4.7ms apply
                // outliers. Android's exact frame-timeline token in auto-timestamp
                // mode, acquire fence and backpressure own visibility/ordering;
                // earlier submission is not permission for an earlier scan.
                // The 2ms admission minimum is still required, not a wake-up time.
                const uint64_t applyNowNs = monotonicNs();
                // The latest callback is a rolling prediction snapshot, not a
                // registry of still-valid AVsyncId tokens. Absence is therefore
                // expected once newer callbacks arrive. A still-visible row may
                // only corroborate the immutable enqueue-time identity; an exact
                // contradiction remains a fail-closed rejection.
                latestTimeline = nativeFrameTimeline(vsyncId);
                if (latestTimeline.has_value() &&
                        latestTimeline->expectedPresentationTimeNs != expectedNs) {
                    rejectScheduled(presentId, "expected-revised", applyNowNs,
                            latestTimeline->expectedPresentationTimeNs,
                            latestTimeline->deadlineNs);
                    continue;
                }
                if (latestTimeline.has_value() &&
                        latestTimeline->deadlineNs != deadlineNs) {
                    rejectScheduled(presentId, "deadline-revised", applyNowNs,
                            latestTimeline->expectedPresentationTimeNs,
                            latestTimeline->deadlineNs);
                    continue;
                }
                if (deadlineNs <= applyNowNs) {
                    rejectScheduled(presentId, "deadline-expired", applyNowNs,
                            latestTimeline.has_value() ?
                                    latestTimeline->expectedPresentationTimeNs : 0,
                            latestTimeline.has_value() ?
                                    latestTimeline->deadlineNs : 0);
                    continue;
                }
                applyScheduled(presentId);
            } catch (...) {
                rejectScheduled(presentId, "apply-exception", diagnosticMonotonicNs(),
                        latestTimeline.has_value() ?
                                latestTimeline->expectedPresentationTimeNs : 0,
                        latestTimeline.has_value() ?
                                latestTimeline->deadlineNs : 0);
            }
        }
    }

    void rejectScheduled(uint64_t presentId, const char* reason,
                         uint64_t observedAtNs,
                         uint64_t observedExpectedNs,
                         uint64_t observedDeadlineNs) {
        bool logRejection = false;
        uint64_t selectedExpectedNs = 0;
        uint64_t selectedDeadlineNs = 0;
        uint64_t selectedVsyncId = 0;
        {
            std::lock_guard<std::mutex> lock(state_->mutex);
            const auto found = state_->pending.find(presentId);
            if (found == state_->pending.end()) return;
            Pending& row = found->second;
            if (row.applyAttempted || row.callbackReceived ||
                    (row.bufferTransferred && !row.transactionCancelled)) {
                recordDispatchFailureLocked(row, "reject-after-buffer-handoff");
                return;
            }
            if (row.submissionRejected) return;
            if (row.acquireFenceFd >= 0) ::close(row.acquireFenceFd);
            row.acquireFenceFd = -1;
            row.submissionRejected = true;
            row.presentFenceFd = -1;
            row.releaseFenceFd = -1;
            row.released = true;
            selectedVsyncId = row.frameTimelineVsyncId;
            selectedExpectedNs = row.frameTimelineExpectedNs;
            selectedDeadlineNs = row.frameTimelineDeadlineNs;
            ++state_->scheduledRejected;
            if (state_->rejectionLogs < kMaximumRejectionLogs) {
                ++state_->rejectionLogs;
                logRejection = true;
            }
        }
        if (logRejection) {
            __android_log_print(ANDROID_LOG_ERROR, "EmuFusionSurfaceControl",
                    "Timed apply rejected presentId=%llu reason=%s vsyncId=%llu "
                    "selectedExpectedNs=%llu selectedDeadlineNs=%llu "
                    "observedAtNs=%llu observedExpectedNs=%llu "
                    "observedDeadlineNs=%llu reserveNs=%lld",
                    static_cast<unsigned long long>(presentId), reason,
                    static_cast<unsigned long long>(selectedVsyncId),
                    static_cast<unsigned long long>(selectedExpectedNs),
                    static_cast<unsigned long long>(selectedDeadlineNs),
                    static_cast<unsigned long long>(observedAtNs),
                    static_cast<unsigned long long>(observedExpectedNs),
                    static_cast<unsigned long long>(observedDeadlineNs),
                    static_cast<long long>(selectedDeadlineNs) -
                            static_cast<long long>(observedAtNs));
        }
    }

    static void postNativeFrameTimelineCallback(
            const std::shared_ptr<TimelineState>& state) {
        auto* callback = new TimelineCallbackContext{state};
        state->postVsync(state->choreographer,
                &Impl::onNativeFrameTimeline, callback);
    }

    static void onNativeFrameTimeline(
            const AChoreographerFrameCallbackData* data, void* opaque) {
        std::unique_ptr<TimelineCallbackContext> callback(
                static_cast<TimelineCallbackContext*>(opaque));
        const std::shared_ptr<TimelineState> state = callback->state;
        bool repost = false;
        {
            std::lock_guard<std::mutex> lock(state->mutex);
            if (!state->closing && data != nullptr) {
                const std::size_t supplied = state->getLength(data);
                state->count = std::min(supplied, kMaxFrameTimelines);
                state->frameTimeNs = static_cast<uint64_t>(
                        std::max<int64_t>(0, state->getFrameTime(data)));
                for (std::size_t index = 0; index < state->count; ++index) {
                    const AVsyncId id = state->getVsyncId(data, index);
                    const int64_t expected = state->getExpected(data, index);
                    const int64_t deadline = state->getDeadline(data, index);
                    state->timelines[index] = {
                        .vsyncId = id > 0 ? static_cast<uint64_t>(id) : 0,
                        .expectedPresentationTimeNs = expected > 0 ?
                                static_cast<uint64_t>(expected) : 0,
                        .deadlineNs = deadline > 0 ?
                                static_cast<uint64_t>(deadline) : 0,
                    };
                }
                ++state->callbackSequence;
                repost = true;
            }
        }
        if (repost) postNativeFrameTimelineCallback(state);
    }

    std::optional<OwnedSurfaceControlPresenter::FrameTimeline>
    nativeFrameTimeline(uint64_t vsyncId) const {
        auto state = timelineState_;
        if (state == nullptr || vsyncId == 0) return std::nullopt;
        std::lock_guard<std::mutex> lock(state->mutex);
        for (std::size_t index = 0; index < state->count; ++index) {
            if (state->timelines[index].vsyncId == vsyncId)
                return state->timelines[index];
        }
        return std::nullopt;
    }

    static uint64_t monotonicNs() {
        timespec now{};
        if (::clock_gettime(CLOCK_MONOTONIC, &now) != 0 ||
                now.tv_sec < 0 || now.tv_nsec < 0)
            throw std::runtime_error("CLOCK_MONOTONIC read failed");
        return static_cast<uint64_t>(now.tv_sec) * 1'000'000'000ULL +
                static_cast<uint64_t>(now.tv_nsec);
    }

    static uint64_t threadCpuNs() {
        timespec now{};
        // Diagnostic only: an unavailable CPU clock is explicitly unknown,
        // never evidence of zero work or authority to change a deadline.
        if (::clock_gettime(CLOCK_THREAD_CPUTIME_ID, &now) != 0 ||
                now.tv_sec < 0 || now.tv_nsec < 0) return 0;
        return static_cast<uint64_t>(now.tv_sec) * 1'000'000'000ULL +
                static_cast<uint64_t>(now.tv_nsec);
    }

    void recordDispatchFailureLocked(Pending& row, const char* reason) noexcept {
        row.dispatchFailed = true;
        if (state_->dispatchFailurePresentId != 0) return;
        state_->dispatchFailurePresentId = row.presentId;
        state_->dispatchFailureReason = reason;
    }

    void throwIfDispatchFailedLocked() const {
        if (state_->dispatchFailurePresentId == 0) return;
        const auto found = state_->pending.find(state_->dispatchFailurePresentId);
        const Pending row = found != state_->pending.end() ? found->second : Pending{};
        throw std::runtime_error("SurfaceControl dispatch failed presentId=" +
                std::to_string(state_->dispatchFailurePresentId) + " reason=" +
                (state_->dispatchFailureReason != nullptr ? state_->dispatchFailureReason : "unknown") +
                " bufferTransferred=" + std::to_string(row.bufferTransferred) +
                " transactionCancelled=" + std::to_string(row.transactionCancelled) +
                " applyAttempted=" + std::to_string(row.applyAttempted) +
                " applyReturned=" + std::to_string(row.applyReturned) +
                " applyStartNs=" + std::to_string(row.transactionApplyStartNs) +
                " applyEndNs=" + std::to_string(row.transactionApplyEndNs));
    }

    static uint64_t diagnosticMonotonicNs() noexcept {
        timespec now{};
        if (::clock_gettime(CLOCK_MONOTONIC, &now) != 0 ||
                now.tv_sec < 0 || now.tv_nsec < 0 || now.tv_nsec >= 1'000'000'000L ||
                static_cast<uint64_t>(now.tv_sec) >
                        (UINT64_MAX - static_cast<uint64_t>(now.tv_nsec)) /
                                1'000'000'000ULL) return 0;
        return static_cast<uint64_t>(now.tv_sec) * 1'000'000'000ULL +
                static_cast<uint64_t>(now.tv_nsec);
    }

    uint64_t recordCommitDispatch(uint64_t presentId,
                                  uint64_t predecessorPresentId) noexcept {
        try {
            std::lock_guard<std::mutex> lock(state_->mutex);
            const auto found = state_->pending.find(presentId);
            if (state_->closing || found == state_->pending.end() ||
                    state_->nextCommitObservationSerial == UINT64_MAX) return 0;
            Pending& row = found->second;
            if (row.commitObservationSerial != 0) return 0;
            row.commitObservationSerial = ++state_->nextCommitObservationSerial;
            row.dispatchObservedNs = diagnosticMonotonicNs();
            row.predecessorPresentId = predecessorPresentId;
            row.predecessorCommitSnapshotKnown = predecessorPresentId != 0 &&
                    state_->lastCommitPresentId == predecessorPresentId &&
                    state_->lastCommitObservationSerial != 0;
            if (row.predecessorCommitSnapshotKnown) {
                row.predecessorCommitObservedAtDispatch =
                        state_->lastCommitCallbackObserved;
                row.predecessorCommitObservedNs = state_->lastCommitCallbackObservedNs;
                const auto previous = state_->pending.find(predecessorPresentId);
                if (previous != state_->pending.end() &&
                        previous->second.commitObservationSerial ==
                                state_->lastCommitObservationSerial &&
                        previous->second.nextDispatchPresentId == 0) {
                    previous->second.nextDispatchPresentId = presentId;
                    previous->second.nextDispatchObservedNs = row.dispatchObservedNs;
                    previous->second.commitObservedAtNextDispatch =
                            state_->lastCommitCallbackObserved;
                    previous->second.commitObservedNsAtNextDispatch =
                            state_->lastCommitCallbackObservedNs;
                }
            }
            state_->lastCommitPresentId = presentId;
            state_->lastCommitObservationSerial = row.commitObservationSerial;
            state_->lastCommitCallbackObserved = false;
            state_->lastCommitCallbackObservedNs = 0;
            return row.commitObservationSerial;
        } catch (...) {
            // Optional observation must not alter handoff or failure policy.
            return 0;
        }
    }

    static void onCommit(void* opaque, ASurfaceTransactionStats*) noexcept {
        std::unique_ptr<CommitCallbackContext> callback(
                static_cast<CommitCallbackContext*>(opaque));
        try {
            std::lock_guard<std::mutex> lock(callback->state->mutex);
            SharedState& state = *callback->state;
            if (state.closing) {
                ++state.commitCallbacksAfterClose;
                return;
            }
            const auto found = state.pending.find(callback->presentId);
            const bool rowMatches = callback->observationSerial != 0 &&
                    found != state.pending.end() &&
                    found->second.commitObservationSerial == callback->observationSerial;
            const bool lastMatches = callback->observationSerial != 0 &&
                    state.lastCommitPresentId == callback->presentId &&
                    state.lastCommitObservationSerial == callback->observationSerial;
            if (!rowMatches && !lastMatches) {
                ++state.unmatchedCommitCallbacks;
                return;
            }
            if ((rowMatches && found->second.commitCallbackObserved) ||
                    (lastMatches && state.lastCommitCallbackObserved)) {
                ++state.duplicateCommitCallbacks;
                return;
            }
            const uint64_t observedNs = diagnosticMonotonicNs();
            if (rowMatches) {
                found->second.commitCallbackObserved = true;
                found->second.commitCallbackObservedNs = observedNs;
            }
            if (lastMatches) {
                state.lastCommitCallbackObserved = true;
                state.lastCommitCallbackObservedNs = observedNs;
            }
            ++state.commitCallbacks;
            // No fence queries, physical/release mutations, wakeups or pacing.
        } catch (...) {
            // A diagnostic callback must never throw across Android's C ABI.
        }
    }

    void logMissingFenceCommitLocked(const Pending& row) {
        if (state_->commitDiagnosticLogs >= kMaximumCommitDiagnosticLogs) return;
        ++state_->commitDiagnosticLogs;
        __android_log_print(ANDROID_LOG_ERROR, "EmuFusionSurfaceControl",
                "Missing fence commit observation presentId=%llu serial=%llu available=%d "
                "commitObserved=%d commitObservedNs=%llu dispatchNs=%llu "
                "predecessor=%llu predecessorKnown=%d predecessorObserved=%d "
                "predecessorObservedNs=%llu next=%llu nextDispatchNs=%llu "
                "observedAtNext=%d observedNsAtNext=%llu",
                static_cast<unsigned long long>(row.presentId),
                static_cast<unsigned long long>(row.commitObservationSerial),
                state_->commitObservationAvailable ? 1 : 0,
                row.commitCallbackObserved ? 1 : 0,
                static_cast<unsigned long long>(row.commitCallbackObservedNs),
                static_cast<unsigned long long>(row.dispatchObservedNs),
                static_cast<unsigned long long>(row.predecessorPresentId),
                row.predecessorCommitSnapshotKnown ? 1 : 0,
                row.predecessorCommitObservedAtDispatch ? 1 : 0,
                static_cast<unsigned long long>(row.predecessorCommitObservedNs),
                static_cast<unsigned long long>(row.nextDispatchPresentId),
                static_cast<unsigned long long>(row.nextDispatchObservedNs),
                row.commitObservedAtNextDispatch ? 1 : 0,
                static_cast<unsigned long long>(row.commitObservedNsAtNextDispatch));
    }

    void logApplyTimingTail(const Pending& row) {
        if (row.transactionApplyStartNs == 0 ||
                row.transactionApplyEndNs < row.transactionApplyStartNs) return;
        const uint64_t wallNs = row.transactionApplyEndNs -
                row.transactionApplyStartNs;
        const bool deadlineCrossed = row.frameTimelineDeadlineNs != 0 &&
                row.transactionApplyEndNs > row.frameTimelineDeadlineNs;
        if (wallNs < kApplyTailDiagnosticThresholdNs && !deadlineCrossed) return;
        {
            std::lock_guard<std::mutex> lock(state_->mutex);
            if (state_->applyTailLogs == kMaximumApplyTailLogs) return;
            ++state_->applyTailLogs;
        }
        const bool cpuKnown = row.transactionApplyCpuStartNs > 0 &&
                row.transactionApplyCpuEndNs >= row.transactionApplyCpuStartNs;
        __android_log_print(ANDROID_LOG_WARN, "EmuFusionSurfaceControl",
                "Apply timing tail presentId=%llu vsyncId=%llu "
                "expectedNs=%llu deadlineNs=%llu driverDesiredNs=%llu desiredTimeExplicit=%d "
                "enqueueNs=%llu dequeueNs=%llu lockAcquiredNs=%llu "
                "applyStartNs=%llu applyEndNs=%llu wallNs=%llu "
                "cpuKnown=%d cpuNs=%llu deadlineCrossed=%d",
                static_cast<unsigned long long>(row.presentId),
                static_cast<unsigned long long>(row.frameTimelineVsyncId),
                static_cast<unsigned long long>(row.frameTimelineExpectedNs),
                static_cast<unsigned long long>(row.frameTimelineDeadlineNs),
                static_cast<unsigned long long>(row.desiredPresentTimeNs),
                row.frameTimelineVsyncId == 0 ? 1 : 0,
                static_cast<unsigned long long>(row.enqueueNs),
                static_cast<unsigned long long>(row.workerDequeueNs),
                static_cast<unsigned long long>(row.applyLockAcquiredNs),
                static_cast<unsigned long long>(row.transactionApplyStartNs),
                static_cast<unsigned long long>(row.transactionApplyEndNs),
                static_cast<unsigned long long>(wallNs), cpuKnown ? 1 : 0,
                static_cast<unsigned long long>(cpuKnown ?
                        row.transactionApplyCpuEndNs -
                                row.transactionApplyCpuStartNs : 0),
                deadlineCrossed ? 1 : 0);
    }

    std::string diagnosticJsonLocked() const {
        uint64_t callbackReady = 0;
        uint64_t validPresentFence = 0;
        uint64_t submissionRejected = 0;
        for (const auto& entry : state_->pending) {
            const Pending& row = entry.second;
            if (row.callbackReceived) ++callbackReady;
            if (row.presentFenceFd >= 0) ++validPresentFence;
            if (row.submissionRejected) ++submissionRejected;
        }
        std::ostringstream record;
        record << "{\"pending\":" << state_->pending.size()
               << ",\"callbacks\":" << state_->callbacks
               << ",\"callbackReady\":" << callbackReady
               << ",\"validPresentFence\":" << validPresentFence
               << ",\"submissionRejected\":" << submissionRejected
               << ",\"immediateRejected\":" << state_->immediateRejected
               << ",\"scheduledRejected\":" << state_->scheduledRejected
               << ",\"rejectionLogs\":" << state_->rejectionLogs
               << ",\"applyTailLogs\":" << state_->applyTailLogs
               << ",\"commitCallbacks\":" << state_->commitCallbacks
               << ",\"duplicateCommitCallbacks\":" << state_->duplicateCommitCallbacks
               << ",\"unmatchedCommitCallbacks\":" << state_->unmatchedCommitCallbacks
               << ",\"commitCallbacksAfterClose\":" << state_->commitCallbacksAfterClose
               << ",\"commitDiagnosticLogs\":" << state_->commitDiagnosticLogs
               << ",\"commitObservationAvailable\":" << (state_->commitObservationAvailable ? 1 : 0)
               << ",\"dispatchFailurePresentId\":" << state_->dispatchFailurePresentId
               << ",\"completed\":" << state_->completed
               << ",\"dropped\":" << state_->dropped
               << ",\"uncompletedRows\":[";
        // Bounded, exact-identity diagnostics. A missing present fence is not
        // presentation evidence; preserve its raw state for the next device
        // run instead of guessing whether it was unsupported or dropped.
        std::size_t reported = 0;
        for (const auto& entry : state_->pending) {
            const Pending& row = entry.second;
            if (row.physicalDelivered) continue;
            if (reported == 4) break;
            if (reported++ != 0) record << ',';
            record << "{\"presentId\":" << row.presentId
                   << ",\"driverDesiredNs\":" << row.desiredPresentTimeNs
                   << ",\"desiredTimeExplicit\":" << (row.frameTimelineVsyncId == 0 ? 1 : 0)
                   << ",\"vsyncId\":" << row.frameTimelineVsyncId
                   << ",\"expectedNs\":" << row.frameTimelineExpectedNs
                   << ",\"deadlineNs\":" << row.frameTimelineDeadlineNs
                   << ",\"enqueueNs\":" << row.enqueueNs
                   << ",\"dequeueNs\":" << row.workerDequeueNs
                   << ",\"lockAcquiredNs\":" << row.applyLockAcquiredNs
                   << ",\"applyStartNs\":" << row.transactionApplyStartNs
                   << ",\"applyEndNs\":" << row.transactionApplyEndNs
                   << ",\"applyCpuStartNs\":" << row.transactionApplyCpuStartNs
                   << ",\"applyCpuEndNs\":" << row.transactionApplyCpuEndNs
                   << ",\"latchNs\":" << row.latchTimeNs
                   << ",\"rawCallbackLatchNs\":" << row.rawCallbackLatchTimeNs
                   << ",\"callbackReceived\":" << row.callbackReceived
                   << ",\"callbackPreviousPresentId\":" << row.callbackPreviousPresentId
                   << ",\"callbackPreviousReleaseFenceFd\":" << row.callbackPreviousReleaseFenceFd
                   << ",\"presentFenceFd\":" << row.presentFenceFd
                   << ",\"releaseCallbackPresentId\":" << row.releaseCallbackPresentId
                   << ",\"releaseFenceFd\":" << row.releaseFenceFd
                   << ",\"acquireFenceFd\":" << row.acquireFenceFd
                   << ",\"released\":" << row.released
                   << ",\"physicalDelivered\":" << row.physicalDelivered
                   << ",\"unavailableReported\":" << row.unavailableReported
                   << ",\"submissionRejected\":" << row.submissionRejected
                   << '}';
        }
        record << "]}";
        return record.str();
    }

    static void onComplete(void* opaque, ASurfaceTransactionStats* stats) {
        std::unique_ptr<CallbackContext> callback(
                static_cast<CallbackContext*>(opaque));
        const int64_t latch = ASurfaceTransactionStats_getLatchTime(stats);
        const int presentFence =
                ASurfaceTransactionStats_getPresentFenceFd(stats);
        const int previousReleaseFence =
                ASurfaceTransactionStats_getPreviousReleaseFenceFd(
                        stats, callback->surface);
        {
            std::lock_guard<std::mutex> lock(callback->state->mutex);
            const auto found = callback->state->pending.find(
                    callback->presentId);
            if (found == callback->state->pending.end() ||
                    found->second.callbackReceived) {
                if (presentFence >= 0) ::close(presentFence);
                if (previousReleaseFence >= 0) ::close(previousReleaseFence);
            } else {
                Pending& row = found->second;
                row.rawCallbackLatchTimeNs = latch;
                row.callbackPreviousPresentId = callback->previousPresentId;
                row.callbackPreviousReleaseFenceFd = previousReleaseFence;
                row.latchTimeNs = latch > 0 ? static_cast<uint64_t>(latch) : 0;
                row.presentFenceFd = presentFence;
                row.callbackReceived = true;
                ++callback->state->callbacks;
                if (callback->previousPresentId == 0) {
                    if (previousReleaseFence >= 0) ::close(previousReleaseFence);
                } else {
                    const auto previous = callback->state->pending.find(
                            callback->previousPresentId);
                    if (previous == callback->state->pending.end() ||
                            previous->second.releaseFenceFd != -2 ||
                            previous->second.released) {
                        if (previousReleaseFence >= 0) ::close(previousReleaseFence);
                    } else if (previousReleaseFence >= 0) {
                        previous->second.releaseCallbackPresentId = callback->presentId;
                        previous->second.releaseFenceFd = previousReleaseFence;
                    } else {
                        previous->second.releaseCallbackPresentId = callback->presentId;
                        previous->second.releaseFenceFd = -1;
                        previous->second.released = true;
                    }
                }
            }
        }
        ASurfaceControl_release(callback->surface);
    }

    void rollback(uint64_t presentId, int acquireFenceFd) {
        if (acquireFenceFd >= 0) ::close(acquireFenceFd);
        std::lock_guard<std::mutex> lock(state_->mutex);
        const auto found = state_->pending.find(presentId);
        if (found == state_->pending.end()) return;
        if (found->second.applyAttempted || found->second.callbackReceived ||
                (found->second.bufferTransferred && !found->second.transactionCancelled)) {
            recordDispatchFailureLocked(found->second, "rollback-after-buffer-handoff");
            return;
        }
        closeAndRelease(found->second);
        state_->pending.erase(found);
    }

    static void closeAndRelease(Pending& row) {
        if (row.presentFenceFd >= 0) ::close(row.presentFenceFd);
        if (row.releaseFenceFd >= 0) ::close(row.releaseFenceFd);
        if (row.acquireFenceFd >= 0) ::close(row.acquireFenceFd);
        if (row.buffer != nullptr) AHardwareBuffer_release(row.buffer);
        row.presentFenceFd = -1;
        row.releaseFenceFd = -1;
        row.acquireFenceFd = -1;
        row.buffer = nullptr;
    }

    void pollReleaseFencesLocked() {
        for (auto& entry : state_->pending) {
            Pending& row = entry.second;
            if (row.released || row.releaseFenceFd < 0) continue;
            pollfd descriptor{row.releaseFenceFd, POLLIN, 0};
            const int result = ::poll(&descriptor, 1, 0);
            if (result == 0) continue;
            if (result != 1 ||
                    (descriptor.revents & (POLLIN | POLLERR | POLLHUP)) == 0)
                throw std::runtime_error(
                        "SurfaceControl release fence poll failed");
            std::unique_ptr<struct sync_file_info,
                    decltype(&sync_file_info_free)> info(
                    sync_file_info(row.releaseFenceFd), &sync_file_info_free);
            if (!info || info->status != 1)
                throw std::runtime_error(
                        "SurfaceControl release fence status invalid");
            ::close(row.releaseFenceFd);
            row.releaseFenceFd = -1;
            row.released = true;
        }
    }

    std::shared_ptr<SharedState> state_;
    std::shared_ptr<TimelineState> timelineState_;
    using AcquireSurface = void (*)(ASurfaceControl*);
    using SetBackPressure = void (*)(
            ASurfaceTransaction*, ASurfaceControl*, bool);
    using SetFrameTimeline = void (*)(ASurfaceTransaction*, AVsyncId);
    using SetOnCommit = void (*)(ASurfaceTransaction*, void*,
            void (*)(void*, ASurfaceTransactionStats*));
    void* androidLibrary_ = nullptr;
    AcquireSurface acquireSurface_ = nullptr;
    SetBackPressure setBackPressure_ = nullptr;
    SetFrameTimeline setFrameTimeline_ = nullptr;
    SetOnCommit setOnCommit_ = nullptr;
    ASurfaceControl* surface_ = nullptr;
    std::thread timedApplyWorker_;
    std::atomic<bool> timedApplyStop_{false};
    std::mutex applyMutex_;
    uint64_t lastSubmittedPresentId_ = 0;
    ARect source_{};
    ARect destination_{};
};

OwnedSurfaceControlPresenter::OwnedSurfaceControlPresenter(
        ANativeWindow* parent, uint32_t bufferWidth, uint32_t bufferHeight)
        : impl_(std::make_unique<Impl>(parent, bufferWidth, bufferHeight)) {}

OwnedSurfaceControlPresenter::~OwnedSurfaceControlPresenter() = default;

bool OwnedSurfaceControlPresenter::present(
        AHardwareBuffer* buffer, int acquireFenceFd, uint64_t presentId,
        uint64_t desiredPresentTimeNs,
        uint64_t compositorFrameTimelineVsyncId,
        uint64_t compositorFrameTimelineExpectedNs,
        uint64_t compositorFrameTimelineDeadlineNs,
        uint64_t compositorRefreshDurationNs) {
    return impl_->present(buffer, acquireFenceFd, presentId, desiredPresentTimeNs,
            compositorFrameTimelineVsyncId,
            compositorFrameTimelineExpectedNs,
            compositorFrameTimelineDeadlineNs,
            compositorRefreshDurationNs);
}

std::optional<OwnedSurfaceControlPresenter::Completion>
OwnedSurfaceControlPresenter::pollCompletion() {
    return impl_->pollCompletion();
}

std::vector<uint64_t>
OwnedSurfaceControlPresenter::takeUnavailablePresentFences() {
    return impl_->takeUnavailablePresentFences();
}

void OwnedSurfaceControlPresenter::markDropped(uint64_t presentId) {
    impl_->markDropped(presentId);
}

bool OwnedSurfaceControlPresenter::isReleased(uint64_t presentId) {
    return impl_->isReleased(presentId);
}

void OwnedSurfaceControlPresenter::retire(uint64_t presentId) {
    impl_->retire(presentId);
}

std::string OwnedSurfaceControlPresenter::diagnosticJson() const {
    return impl_->diagnosticJson();
}

void OwnedSurfaceControlPresenter::enableNativeFrameTimelineSource() {
    impl_->enableNativeFrameTimelineSource();
}

std::vector<OwnedSurfaceControlPresenter::FrameTimeline>
OwnedSurfaceControlPresenter::nativeFrameTimelines(
        uint64_t* callbackSequence, uint64_t* frameTimeNs) const {
    return impl_->nativeFrameTimelines(callbackSequence, frameTimeNs);
}

bool OwnedSurfaceControlPresenter::canSubmitFrameTimeline(
        uint64_t vsyncId, uint64_t expectedNs, uint64_t deadlineNs,
        uint64_t refreshDurationNs) const {
    return impl_->canSubmitFrameTimeline(
            vsyncId, expectedNs, deadlineNs, refreshDurationNs);
}

bool OwnedSurfaceControlPresenter::supportsFrameTimeline() const {
    return impl_->supportsFrameTimeline();
}

}  // namespace emufusion::lsfg
