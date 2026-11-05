#pragma once

#include <cstdint>
#include <cmath>

struct MagFrame {
  float x;
  float y;
  float z;
};

class FrameGuard {
 public:
  FrameGuard(float jump_uT, float agreement_uT, float near_zero_uT)
      : jump_uT_(jump_uT),
        agreement_uT_(agreement_uT),
        near_zero_uT_(near_zero_uT),
        has_previous_(false),
        previous_{0.0f, 0.0f, 0.0f} {}

  bool requiresRetry(const MagFrame& sample) const {
    if (!finite(sample) || magnitude(sample) <= near_zero_uT_) {
      return true;
    }
    return has_previous_ && distance(sample, previous_) >= jump_uT_;
  }

  bool resolveRetry(const MagFrame& first, const MagFrame& second,
                    MagFrame& accepted) {
    if (!finite(second) || magnitude(second) <= near_zero_uT_) {
      return false;
    }
    const bool confirms_first = distance(first, second) <= agreement_uT_;
    const bool returns_to_previous =
        has_previous_ && distance(previous_, second) <= agreement_uT_;
    if (!confirms_first && !returns_to_previous) {
      return false;
    }
    accepted = second;
    commit(second);
    return true;
  }

  void commit(const MagFrame& sample) {
    previous_ = sample;
    has_previous_ = true;
  }

 private:
  static bool finite(const MagFrame& sample) {
    return std::isfinite(sample.x) && std::isfinite(sample.y) &&
           std::isfinite(sample.z);
  }

  static float magnitude(const MagFrame& sample) {
    return std::sqrt(sample.x * sample.x + sample.y * sample.y +
                     sample.z * sample.z);
  }

  static float distance(const MagFrame& a, const MagFrame& b) {
    const float dx = a.x - b.x;
    const float dy = a.y - b.y;
    const float dz = a.z - b.z;
    return std::sqrt(dx * dx + dy * dy + dz * dz);
  }

  float jump_uT_;
  float agreement_uT_;
  float near_zero_uT_;
  bool has_previous_;
  MagFrame previous_;
};

struct AcquisitionStats {
  uint32_t goodFrames = 0;
  uint32_t droppedFrames = 0;
  uint32_t readErrors = 0;
  uint32_t suspectFrames = 0;
  uint32_t retries = 0;
  uint32_t recoveryAttempts = 0;
  uint32_t recoveries = 0;
  uint8_t consecutiveFailures = 0;
};

template <typename Recoverer>
void recordAcquisitionFailure(Recoverer& recover, AcquisitionStats& stats) {
  ++stats.droppedFrames;
  ++stats.consecutiveFailures;
  if (stats.consecutiveFailures < 3) return;
  ++stats.recoveryAttempts;
  if (recover()) {
    ++stats.recoveries;
    stats.consecutiveFailures = 0;
  }
}

template <typename Reader, typename Recoverer>
bool acquireGuardedFrame(FrameGuard& guard, Reader& read, Recoverer& recover,
                         AcquisitionStats& stats, MagFrame& output) {
  MagFrame first{};
  if (!read(first)) {
    ++stats.readErrors;
    ++stats.retries;
    MagFrame retry{};
    if (!read(retry)) {
      ++stats.readErrors;
      recordAcquisitionFailure(recover, stats);
      return false;
    }
    if (guard.requiresRetry(retry)) {
      ++stats.suspectFrames;
      recordAcquisitionFailure(recover, stats);
      return false;
    }
    guard.commit(retry);
    output = retry;
    ++stats.goodFrames;
    stats.consecutiveFailures = 0;
    return true;
  }

  if (!guard.requiresRetry(first)) {
    guard.commit(first);
    output = first;
    ++stats.goodFrames;
    stats.consecutiveFailures = 0;
    return true;
  }

  ++stats.suspectFrames;
  ++stats.retries;
  MagFrame retry{};
  if (!read(retry)) {
    ++stats.readErrors;
    recordAcquisitionFailure(recover, stats);
    return false;
  }
  if (!guard.resolveRetry(first, retry, output)) {
    recordAcquisitionFailure(recover, stats);
    return false;
  }
  ++stats.goodFrames;
  stats.consecutiveFailures = 0;
  return true;
}
