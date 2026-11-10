// Example integration for a target firmware you own or are authorized to test.
// Wire the NEXUS sideband TX -> target sideband RX and target sideband TX ->
// NEXUS sideband RX through voltage-compatible interfaces.
#include <Arduino.h>
#include <cstdint>
#include "nexus/coverage.hpp"
#include "nexus/target_coverage_link.hpp"

static nexus::TargetCoverageSession g_coverage_session{};

static bool parse_lab_status(const std::uint8_t* data, std::size_t length) {
    NEXUS_COV_HIT(1); // parser entry
    if (data == nullptr || length == 0) {
        NEXUS_COV_HIT(2); // invalid input branch
        return false;
    }
    NEXUS_COV_HIT(3); // non-empty input
    if (data[0] == 0x10) {
        NEXUS_COV_HIT(4); // documented read-only status command
        return length >= 2;
    }
    NEXUS_COV_HIT(5); // unknown command branch
    return false;
}

void setup() {
    Serial1.begin(115200); // dedicated bidirectional sideband UART
}

// Call this frequently from the target main loop. It accepts only
// NXCOV_BEGIN,<decimal-case-id>, resets the per-case bitmap, and replies NXCOV_READY,<id>.
void nexus_poll_coverage_control() {
    (void)g_coverage_session.poll_begin(Serial1);
}

// Call after the target has received and dispatched one fuzz request. The
// report ID is now guaranteed to match the NEXUS case ID sent out-of-band.
void nexus_emit_coverage_after_request() {
    (void)g_coverage_session.emit_after_case(Serial1);
}

// Example only: integrate parse_lab_status() into the target's actual request
// handler and call nexus_emit_coverage_after_request() after parser dispatch.
