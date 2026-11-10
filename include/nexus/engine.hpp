#pragma once

#include "nexus/analysis.hpp"
#include "nexus/transport.hpp"

namespace nexus {

class Engine {
public:
    Engine(ITransport& transport, IClock& clock, EngineConfig config,
           ProtocolProfile profile) noexcept
        : transport_(transport), clock_(clock), config_(config), profile_(profile) {}

    [[nodiscard]] bool armed() const noexcept {
        return config_.authorized_lab_target && config_.active_fuzz_enabled &&
               config_.max_cases > 0 && config_.timeout_us > 0;
    }
    [[nodiscard]] bool configuration_valid() const noexcept;
    [[nodiscard]] bool corpus_valid(const SeedSet& corpus) const noexcept;

    [[nodiscard]] bool begin() noexcept;
    void end() noexcept;
    [[nodiscard]] bool calibrate(const SeedSet& corpus) noexcept;
    [[nodiscard]] CaseResult execute(const Frame& tx, std::uint32_t case_id,
                                     std::uint16_t command_tag,
                                     MutationKind mutation_kind) noexcept;

    [[nodiscard]] const StateGraph& graph() const noexcept { return graph_; }
    [[nodiscard]] const TimingAnalyzer& timing() const noexcept { return timing_; }
    [[nodiscard]] std::uint32_t executed_cases() const noexcept { return executed_cases_; }
    [[nodiscard]] bool halted() const noexcept { return halted_; }
    [[nodiscard]] TargetHealth target_health() const noexcept { return target_health_; }
    [[nodiscard]] std::uint32_t crash_suspicions() const noexcept { return crash_suspicions_; }
    [[nodiscard]] std::uint32_t link_faults() const noexcept { return link_faults_; }
    [[nodiscard]] const std::array<FailureEvent, kMaxFailureEvents>& failure_events() const noexcept {
        return failure_events_;
    }
    [[nodiscard]] const std::array<CrashRecord, kMaxCrashRecords>& crash_records() const noexcept {
        return crash_records_;
    }
    [[nodiscard]] std::uint8_t crash_record_count() const noexcept { return crash_record_count_; }
    [[nodiscard]] bool case_budget_exhausted() const noexcept {
        return executed_cases_ >= config_.max_cases;
    }
    [[nodiscard]] const EngineConfig& config() const noexcept { return config_; }

private:
    [[nodiscard]] ExchangeResult transact(const Frame& tx) noexcept;
    [[nodiscard]] TargetHealth probe_liveness(std::uint8_t& failed_probes) noexcept;
    void record_failure(const CaseResult& result) noexcept;
    void record_crash(const CaseResult& result, const Frame& trigger) noexcept;
    void throttle() noexcept;

    ITransport& transport_;
    IClock& clock_;
    EngineConfig config_;
    ProtocolProfile profile_;
    StateGraph graph_{};
    TimingAnalyzer timing_{};
    std::array<FailureEvent, kMaxFailureEvents> failure_events_{};
    std::array<CrashRecord, kMaxCrashRecords> crash_records_{};
    std::uint64_t last_tx_us_{0};
    bool has_last_tx_time_{false};
    std::uint16_t last_state_{0xFFFFU};
    std::uint32_t executed_cases_{0};
    std::uint32_t crash_suspicions_{0};
    std::uint32_t link_faults_{0};
    std::uint8_t consecutive_io_errors_{0};
    std::uint8_t failure_event_cursor_{0};
    std::uint8_t crash_record_cursor_{0};
    std::uint8_t crash_record_count_{0};
    TargetHealth target_health_{TargetHealth::Unknown};
    bool halted_{false};
    bool begun_{false};
};

} // namespace nexus
