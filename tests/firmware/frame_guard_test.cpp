#include <cassert>
#include <cmath>
#include <cstddef>
#include "frame_guard.h"

struct ReadStep {
  bool ok;
  MagFrame frame;
};

class SequenceReader {
 public:
  SequenceReader(const ReadStep* steps, std::size_t count)
      : calls(0), steps_(steps), count_(count), index_(0) {}

  bool operator()(MagFrame& out) {
    ++calls;
    if (index_ >= count_) return false;
    const ReadStep& step = steps_[index_++];
    if (step.ok) out = step.frame;
    return step.ok;
  }

  int calls;

 private:
  const ReadStep* steps_;
  std::size_t count_;
  std::size_t index_;
};

struct RecoveryCounter {
  int calls = 0;
  bool operator()() {
    ++calls;
    return true;
  }
};

int main() {
  FrameGuard guard(1000.0f, 250.0f, 5.0f);
  const MagFrame baseline{30.0f, -1080.0f, -4480.0f};
  guard.commit(baseline);

  const MagFrame stable{32.0f, -1078.0f, -4482.0f};
  assert(!guard.requiresRetry(stable));

  const MagFrame zeroRead{0.0f, 0.0f, 0.0f};
  assert(guard.requiresRetry(zeroRead));
  MagFrame accepted{};
  assert(guard.resolveRetry(zeroRead, stable, accepted));
  assert(std::fabs(accepted.y - stable.y) < 0.001f);

  const MagFrame highStep{1800.0f, -2500.0f, -6100.0f};
  const MagFrame highRepeat{1810.0f, -2490.0f, -6090.0f};
  assert(guard.requiresRetry(highStep));
  assert(guard.resolveRetry(highStep, highRepeat, accepted));
  assert(std::fabs(accepted.x - highRepeat.x) < 0.001f);

  const MagFrame corrupt{76.65f, -0.15f, -0.242f};
  const MagFrame unrelated{-3000.0f, 1700.0f, 500.0f};
  assert(guard.requiresRetry(corrupt));
  assert(!guard.resolveRetry(corrupt, unrelated, accepted));

  const MagFrame nanRead{NAN, -1000.0f, -4000.0f};
  assert(guard.requiresRetry(nanRead));
  assert(!guard.resolveRetry(nanRead, nanRead, accepted));

  FrameGuard acquisitionGuard(1000.0f, 250.0f, 5.0f);
  acquisitionGuard.commit(baseline);
  AcquisitionStats stats{};
  RecoveryCounter recovery;

  const ReadStep cleanSteps[] = {{true, stable}};
  SequenceReader cleanReader(cleanSteps, 1);
  assert(acquireGuardedFrame(acquisitionGuard, cleanReader, recovery, stats,
                             accepted));
  assert(cleanReader.calls == 1);
  assert(stats.goodFrames == 1);

  const ReadStep glitchSteps[] = {{true, corrupt}, {true, stable}};
  SequenceReader glitchReader(glitchSteps, 2);
  assert(acquireGuardedFrame(acquisitionGuard, glitchReader, recovery, stats,
                             accepted));
  assert(glitchReader.calls == 2);
  assert(stats.suspectFrames == 1);
  assert(stats.retries == 1);

  const ReadStep failedSteps[] = {
      {false, {}}, {false, {}}, {false, {}},
      {false, {}}, {false, {}}, {false, {}},
  };
  SequenceReader failedReader(failedSteps, 6);
  for (int i = 0; i < 3; ++i) {
    assert(!acquireGuardedFrame(acquisitionGuard, failedReader, recovery,
                                stats, accepted));
  }
  assert(stats.readErrors == 6);
  assert(stats.droppedFrames == 3);
  assert(stats.recoveries == 1);
  assert(recovery.calls == 1);
  return 0;
}
