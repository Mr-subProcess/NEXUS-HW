#pragma once

#include "nexus/types.hpp"

#include <cmath>

namespace nexus {

[[nodiscard]] inline std::uint32_t fingerprint(const Frame& frame,
                                                ResponseKind kind) noexcept {
    std::uint32_t hash = 2166136261U;
    hash ^= static_cast<std::uint8_t>(kind);
    hash *= 16777619U;
    const std::uint16_t safe_size = frame.size <= kMaxFrameBytes ? frame.size
                                                                  : static_cast<std::uint16_t>(kMaxFrameBytes);
    for (std::uint16_t i = 0; i < safe_size; ++i) {
        hash ^= frame.bytes[i];
        hash *= 16777619U;
    }
    hash ^= frame.size;
    hash *= 16777619U;
    return hash;
}

[[nodiscard]] inline ResponseKind classify(const Frame& response, IoStatus status,
                                            const ProtocolProfile& profile) noexcept {
    if (status == IoStatus::Timeout) return ResponseKind::Timeout;
    if (status == IoStatus::FrameOverflow) return ResponseKind::OversizedResponse;
    if (status != IoStatus::Ok) return ResponseKind::BusError;
    if (response.size == 0) return ResponseKind::Timeout;
    if (profile.ack.matches(response)) return ResponseKind::Ack;
    if (profile.nack.matches(response)) return ResponseKind::Nack;
    if (profile.device_error.matches(response)) return ResponseKind::DeviceError;
    return ResponseKind::Data;
}

struct StateNode {
    std::uint32_t fingerprint{0};
    std::uint32_t visits{0};
    ResponseKind kind{ResponseKind::Data};
    Frame response_key{};
    bool used{false};
};

struct StateEdge {
    std::uint16_t from{0};
    std::uint16_t to{0};
    std::uint16_t command_tag{0};
    ResponseKind outcome{ResponseKind::Data};
    std::uint32_t traversals{0};
    bool used{false};
};

class StateGraph {
public:
    // State identity uses the full observable response, not just its 32-bit
    // fingerprint. The fingerprint is an index/visualization aid; it is never
    // treated as collision-free identity.
    [[nodiscard]] std::uint16_t observe_state(const Frame& response,
                                              ResponseKind kind) noexcept {
        if (response.size > kMaxFrameBytes) {
            if (dropped_states_ != UINT32_MAX) ++dropped_states_;
            return 0xFFFFU;
        }
        const std::uint32_t fp = fingerprint(response, kind);
        for (std::uint16_t i = 0; i < states_.size(); ++i) {
            const auto& state = states_[i];
            if (!state.used || state.fingerprint != fp || state.kind != kind ||
                state.response_key.size != response.size) continue;
            bool equal = true;
            for (std::uint16_t j = 0; j < response.size; ++j) {
                if (state.response_key.bytes[j] != response.bytes[j]) {
                    equal = false;
                    break;
                }
            }
            if (equal) {
                if (states_[i].visits != UINT32_MAX) ++states_[i].visits;
                return i;
            }
        }
        for (std::uint16_t i = 0; i < states_.size(); ++i) {
            if (!states_[i].used) {
                states_[i] = StateNode{fp, 1, kind, response, true};
                ++state_count_;
                return i;
            }
        }
        if (dropped_states_ != UINT32_MAX) ++dropped_states_;
        return 0xFFFFU;
    }

    void observe_edge(std::uint16_t from, std::uint16_t to,
                      std::uint16_t command_tag, ResponseKind outcome) noexcept {
        if (from == 0xFFFFU || to == 0xFFFFU) return;
        for (auto& edge : edges_) {
            if (edge.used && edge.from == from && edge.to == to &&
                edge.command_tag == command_tag && edge.outcome == outcome) {
                if (edge.traversals != UINT32_MAX) ++edge.traversals;
                return;
            }
        }
        for (auto& edge : edges_) {
            if (!edge.used) {
                edge = StateEdge{from, to, command_tag, outcome, 1, true};
                ++edge_count_;
                return;
            }
        }
        if (dropped_edges_ != UINT32_MAX) ++dropped_edges_;
    }

    [[nodiscard]] const auto& states() const noexcept { return states_; }
    [[nodiscard]] const auto& edges() const noexcept { return edges_; }
    [[nodiscard]] std::uint16_t state_count() const noexcept { return state_count_; }
    [[nodiscard]] std::uint16_t edge_count() const noexcept { return edge_count_; }
    [[nodiscard]] std::uint32_t dropped_states() const noexcept { return dropped_states_; }
    [[nodiscard]] std::uint32_t dropped_edges() const noexcept { return dropped_edges_; }

private:
    std::array<StateNode, kMaxStates> states_{};
    std::array<StateEdge, kMaxEdges> edges_{};
    std::uint16_t state_count_{0};
    std::uint16_t edge_count_{0};
    std::uint32_t dropped_states_{0};
    std::uint32_t dropped_edges_{0};
};

struct OnlineStats {
    std::uint32_t count{0};
    double mean{0.0};
    double m2{0.0};
    std::uint32_t min_us{0xFFFFFFFFU};
    std::uint32_t max_us{0};

    void add(std::uint32_t sample) noexcept {
        if (count == UINT32_MAX) return;
        ++count;
        if (sample < min_us) min_us = sample;
        if (sample > max_us) max_us = sample;
        const double x = static_cast<double>(sample);
        const double delta = x - mean;
        mean += delta / static_cast<double>(count);
        const double delta2 = x - mean;
        m2 += delta * delta2;
    }

    [[nodiscard]] double variance() const noexcept {
        return count > 1 ? m2 / static_cast<double>(count - 1U) : 0.0;
    }
    [[nodiscard]] double stddev() const noexcept {
        const double v = variance();
        return v > 0.0 ? std::sqrt(v) : 0.0;
    }
};

class TimingAnalyzer {
public:
    static constexpr std::size_t kKinds = 7;

    void add_baseline(ResponseKind kind, std::uint32_t latency_us) noexcept {
        baseline_[static_cast<std::size_t>(kind)].add(latency_us);
    }

    [[nodiscard]] bool is_anomaly_candidate(ResponseKind kind,
                                             std::uint32_t latency_us,
                                             float sigma) const noexcept {
        const auto& s = baseline_[static_cast<std::size_t>(kind)];
        if (s.count < 4U) return false;
        const double margin = static_cast<double>(sigma) * (s.stddev() + 1.0);
        const double delta = static_cast<double>(latency_us) - s.mean;
        return delta > margin || delta < -margin;
    }

    [[nodiscard]] const OnlineStats& stats(ResponseKind kind) const noexcept {
        return baseline_[static_cast<std::size_t>(kind)];
    }

private:
    std::array<OnlineStats, kKinds> baseline_{};
};

} // namespace nexus
