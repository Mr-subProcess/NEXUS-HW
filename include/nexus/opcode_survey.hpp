#pragma once

#include "nexus/analysis.hpp"
#include "nexus/transport.hpp"

namespace nexus {

struct OpcodeSurveyConfig {
    bool authorized_lab_target{false};
    bool active_probe_enabled{false};
    std::uint8_t max_probes{0};
    std::uint32_t timeout_us{20'000};
    std::uint32_t minimum_interval_us{100'000};
};

struct OpcodeSurveyReport {
    std::array<OpcodeObservation, kMaxSafeOpcodes> observations{};
    std::uint8_t count{0};
    std::uint8_t accepted{0};
    std::uint8_t rejected{0};
    std::uint8_t no_response{0};
    std::uint8_t device_errors{0};
    std::uint8_t transport_faults{0};
};

// Physical-link opcode survey for an operator-reviewed manifest only.
// It deliberately refuses unknown/unreviewed opcodes; all candidates must be
// documented read-only requests. Full 0x00..0xFF sweeps exist only in the host
// simulator, never in the physical firmware path.
class SafeOpcodeSurvey {
public:
    [[nodiscard]] static bool run(ITransport& transport, IClock& clock,
                                  const SafeOpcodeManifest& manifest,
                                  const OpcodeSurveyConfig& config,
                                  const ProtocolProfile& profile,
                                  OpcodeSurveyReport& report) noexcept {
        report = {};
        if (!config.authorized_lab_target || !config.active_probe_enabled ||
            manifest.count == 0 || manifest.count > kMaxSafeOpcodes ||
            config.max_probes == 0 || config.timeout_us == 0 ||
            config.max_probes < manifest.count) return false;

        for (std::uint8_t i = 0; i < manifest.count; ++i) {
            const auto& candidate = manifest.candidates[i];
            if (!candidate.documented_read_only || !candidate.request.valid()) {
                report = {};
                return false;
            }
        }
        if (!transport.begin()) return false;

        std::uint64_t last_tx = 0;
        for (std::uint8_t i = 0; i < manifest.count; ++i) {
            const auto& candidate = manifest.candidates[i];
            if (last_tx != 0) {
                const auto now = clock.now_us();
                const auto elapsed = now - last_tx;
                if (elapsed < config.minimum_interval_us) {
                    clock.sleep_us(static_cast<std::uint32_t>(config.minimum_interval_us - elapsed));
                }
            }
            Frame response{};
            const auto start = clock.now_us();
            const auto status = transport.exchange(candidate.request, response, config.timeout_us);
            const auto finish = clock.now_us();
            last_tx = finish;
            const auto latency = static_cast<std::uint32_t>(finish - start);
            const auto response_kind = classify(response, status, profile);

            OpcodeDisposition disposition = OpcodeDisposition::Invalid;
            switch (response_kind) {
                case ResponseKind::Ack:
                case ResponseKind::Data: disposition = OpcodeDisposition::Accepted; ++report.accepted; break;
                case ResponseKind::Nack: disposition = OpcodeDisposition::Rejected; ++report.rejected; break;
                case ResponseKind::DeviceError: disposition = OpcodeDisposition::DeviceError; ++report.device_errors; break;
                case ResponseKind::Timeout: disposition = OpcodeDisposition::NoResponse; ++report.no_response; break;
                case ResponseKind::BusError:
                case ResponseKind::OversizedResponse:
                    disposition = OpcodeDisposition::TransportFault; ++report.transport_faults; break;
            }
            auto& observation = report.observations[report.count++];
            observation.command_tag = candidate.command_tag;
            observation.opcode = candidate.request.bytes[0];
            observation.disposition = disposition;
            observation.latency_us = latency;
            observation.response_fingerprint = fingerprint(response, response_kind);
            if (disposition == OpcodeDisposition::TransportFault) break;
        }
        transport.end();
        return true;
    }
};

} // namespace nexus
