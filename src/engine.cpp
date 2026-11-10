#include "nexus/engine.hpp"
#include "nexus/checksum.hpp"

#include <cmath>
#include <limits>

namespace nexus {

bool Engine::configuration_valid() const noexcept {
    if (!armed() || config_.timeout_us < 100U || config_.timeout_us > 60'000'000U ||
        config_.max_cases > 1'000'000U || config_.minimum_interval_us > 60'000'000U ||
        config_.calibration_rounds == 0U || config_.calibration_rounds > 32U ||
        config_.max_consecutive_io_errors == 0U || config_.max_consecutive_io_errors > 32U ||
        !std::isfinite(config_.anomaly_sigma) || config_.anomaly_sigma < 0.5F ||
        config_.anomaly_sigma > 12.0F) return false;
    if (config_.liveness.enabled) {
        if (!config_.liveness.request.valid() || config_.liveness.expected_response.size == 0U ||
            config_.liveness.expected_response.size > config_.liveness.expected_response.bytes.size() ||
            config_.liveness.retries == 0U || config_.liveness.retries > 8U ||
            config_.liveness.retry_delay_us > 60'000'000U) return false;
    }
    return true;
}

bool Engine::corpus_valid(const SeedSet& corpus) const noexcept {
    if (corpus.count == 0U || corpus.count > kMaxCorpusEntries) return false;
    for (std::uint8_t i = 0; i < corpus.count; ++i) {
        const auto& entry = corpus.entries[i];
        if (!entry.frame.valid() || entry.immutable_prefix >= entry.frame.size ||
            entry.minimum_mutable_bytes == 0U) return false;
        std::uint16_t mutable_bytes = static_cast<std::uint16_t>(entry.frame.size - entry.immutable_prefix);
        if (entry.checksum.enabled) {
            if (!checksum_spec_valid(entry.frame, entry.checksum) ||
                entry.checksum.checksum_offset < entry.immutable_prefix) return false;
            const auto width = checksum_width(entry.checksum.algorithm);
            const auto checksum_end = static_cast<std::uint16_t>(entry.checksum.checksum_offset + width);
            mutable_bytes = static_cast<std::uint16_t>(mutable_bytes - width);
            (void)checksum_end;
        }
        if (mutable_bytes < entry.minimum_mutable_bytes) return false;
    }
    return true;
}

bool Engine::begin() noexcept {
    if (!configuration_valid()) return false;
    begun_ = transport_.begin();
    return begun_;
}

void Engine::end() noexcept {
    if (begun_) transport_.end();
    begun_ = false;
}

ExchangeResult Engine::transact(const Frame& tx) noexcept {
    ExchangeResult result{};
    if (!tx.valid()) {
        result.status = IoStatus::InvalidFrame;
        return result;
    }
    Frame rx{};
    const std::uint64_t start = clock_.now_us();
    result.status = transport_.exchange(tx, rx, config_.timeout_us);
    if (rx.size > kMaxFrameBytes) {
        rx.size = static_cast<std::uint16_t>(kMaxFrameBytes);
        result.status = IoStatus::FrameOverflow;
    }
    const std::uint64_t finish = clock_.now_us();
    result.elapsed_us = static_cast<std::uint32_t>(finish - start);
    result.response = rx;
    return result;
}

void Engine::throttle() noexcept {
    if (!has_last_tx_time_) return;
    const std::uint64_t now = clock_.now_us();
    const std::uint64_t elapsed = now - last_tx_us_;
    if (elapsed < config_.minimum_interval_us) {
        clock_.sleep_us(static_cast<std::uint32_t>(config_.minimum_interval_us - elapsed));
    }
}

TargetHealth Engine::probe_liveness(std::uint8_t& failed_probes) noexcept {
    failed_probes = 0;
    if (!config_.liveness.enabled || !config_.liveness.request.valid()) {
        return TargetHealth::Unknown;
    }

    bool saw_bus_error = false;
    const std::uint8_t attempts = config_.liveness.retries == 0 ? 1 : config_.liveness.retries;
    for (std::uint8_t attempt = 0; attempt < attempts; ++attempt) {
        if (attempt > 0 && config_.liveness.retry_delay_us > 0) {
            clock_.sleep_us(config_.liveness.retry_delay_us);
        }
        throttle();
        const auto probe = transact(config_.liveness.request);
        last_tx_us_ = clock_.now_us();
        has_last_tx_time_ = true;
        if (probe.status == IoStatus::BusError || probe.status == IoStatus::InvalidFrame) {
            saw_bus_error = true;
            ++failed_probes;
            continue;
        }
        if (probe.status == IoStatus::Timeout || probe.response.size == 0) {
            ++failed_probes;
            continue;
        }
        if (probe.status == IoStatus::FrameOverflow) return TargetHealth::Degraded;
        // A matching signature is a positive heartbeat. Any other non-empty
        // response still proves that the target is responding, but is degraded.
        if (config_.liveness.expected_response.size == 0 ||
            config_.liveness.expected_response.matches(probe.response)) {
            return TargetHealth::Alive;
        }
        return TargetHealth::Degraded;
    }
    return saw_bus_error ? TargetHealth::LinkFault : TargetHealth::Unresponsive;
}

void Engine::record_failure(const CaseResult& result) noexcept {
    auto& event = failure_events_[failure_event_cursor_];
    event = FailureEvent{result.case_id, clock_.now_us(), result.latency_us,
                         result.command_tag, result.failure_streak,
                         result.response_kind, result.target_health,
                         result.liveness_checked, true};
    failure_event_cursor_ = static_cast<std::uint8_t>(
        (failure_event_cursor_ + 1U) % kMaxFailureEvents);
}

void Engine::record_crash(const CaseResult& result, const Frame& trigger) noexcept {
    auto& record = crash_records_[crash_record_cursor_];
    std::uint8_t failed_probes = config_.liveness.retries == 0 ? 1 : config_.liveness.retries;
    record = CrashRecord{result.case_id, clock_.now_us(), result.command_tag,
                         result.latency_us, failed_probes, trigger, true};
    crash_record_cursor_ = static_cast<std::uint8_t>(
        (crash_record_cursor_ + 1U) % kMaxCrashRecords);
    if (crash_record_count_ < kMaxCrashRecords) ++crash_record_count_;
    if (crash_suspicions_ != UINT32_MAX) ++crash_suspicions_;
}

bool Engine::calibrate(const SeedSet& corpus) noexcept {
    // Validate the entire corpus before transmitting even one frame. This avoids
    // partially exercising a target when a later seed is malformed.
    if (!begun_ || !corpus_valid(corpus)) return false;
    for (std::uint8_t round = 0; round < config_.calibration_rounds; ++round) {
        for (std::uint8_t i = 0; i < corpus.count; ++i) {
            if (!corpus.entries[i].frame.valid()) return false;
            throttle();
            const auto result = transact(corpus.entries[i].frame);
            last_tx_us_ = clock_.now_us();
            has_last_tx_time_ = true;
            const auto kind = classify(result.response, result.status, profile_);
            if (kind == ResponseKind::Timeout || kind == ResponseKind::BusError ||
                kind == ResponseKind::OversizedResponse) {
                if (++consecutive_io_errors_ >= config_.max_consecutive_io_errors) {
                    halted_ = true;
                    target_health_ = (kind == ResponseKind::BusError)
                        ? TargetHealth::LinkFault : TargetHealth::Suspect;
                    return false;
                }
            } else {
                consecutive_io_errors_ = 0;
                target_health_ = TargetHealth::Alive;
            }
            timing_.add_baseline(kind, result.elapsed_us);
            const auto state = graph_.observe_state(result.response, kind);
            if (last_state_ != 0xFFFFU && state != 0xFFFFU) {
                graph_.observe_edge(last_state_, state, corpus.entries[i].command_tag, kind);
            }
            last_state_ = state;
        }
    }
    return true;
}

CaseResult Engine::execute(const Frame& tx, std::uint32_t case_id,
                           std::uint16_t command_tag,
                           MutationKind mutation_kind) noexcept {
    CaseResult out{};
    out.case_id = case_id;
    out.command_tag = command_tag;
    out.state_before = last_state_;
    out.mutation_kind = mutation_kind;
    if (!begun_ || !armed() || halted_ || case_budget_exhausted() || !tx.valid()) {
        out.response_kind = ResponseKind::BusError;
        out.target_health = target_health_;
        return out;
    }

    throttle();
    const auto result = transact(tx);
    last_tx_us_ = clock_.now_us();
    has_last_tx_time_ = true;
    ++executed_cases_;
    out.latency_us = result.elapsed_us;
    out.response_kind = classify(result.response, result.status, profile_);

    if (out.response_kind == ResponseKind::Timeout || out.response_kind == ResponseKind::BusError ||
        out.response_kind == ResponseKind::OversizedResponse) {
        if (consecutive_io_errors_ < 255U) ++consecutive_io_errors_;
        target_health_ = TargetHealth::Suspect;
        if (consecutive_io_errors_ >= config_.max_consecutive_io_errors) {
            out.liveness_checked = config_.liveness.enabled;
            std::uint8_t failed_probes = 0;
            target_health_ = probe_liveness(failed_probes);
            if (target_health_ == TargetHealth::Alive || target_health_ == TargetHealth::Degraded) {
                // The target is alive: the fuzz case was rejected, ignored, or
                // timed out at the protocol layer; do not mislabel it a crash.
                consecutive_io_errors_ = 0;
            } else if (target_health_ == TargetHealth::Unresponsive) {
                out.crash_suspected = true;
                halted_ = true;
            } else if (target_health_ == TargetHealth::LinkFault) {
                if (link_faults_ != UINT32_MAX) ++link_faults_;
                halted_ = true;
            } else {
                // No heartbeat configured: preserve fail-closed behavior without
                // claiming that an MCU crash was proven.
                halted_ = true;
            }
            out.failure_streak = consecutive_io_errors_;
            out.target_health = target_health_;
            record_failure(out);
            if (out.crash_suspected) record_crash(out, tx);
        } else {
            out.failure_streak = consecutive_io_errors_;
            out.target_health = target_health_;
            record_failure(out);
        }
    } else {
        consecutive_io_errors_ = 0;
        target_health_ = TargetHealth::Alive;
        out.failure_streak = 0;
        out.target_health = target_health_;
    }

    out.response_fingerprint = fingerprint(result.response, out.response_kind);
    out.state_after = graph_.observe_state(result.response, out.response_kind);
    graph_.observe_edge(out.state_before, out.state_after, command_tag, out.response_kind);
    out.timing_anomaly_candidate = timing_.is_anomaly_candidate(
        out.response_kind, out.latency_us, config_.anomaly_sigma);
    last_state_ = out.state_after;
    return out;
}

} // namespace nexus
