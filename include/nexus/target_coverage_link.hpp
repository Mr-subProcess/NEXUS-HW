#pragma once

#include "nexus/coverage.hpp"

#include <cstddef>
#include <cstdio>
#include <cstdint>

namespace nexus {

// Small, allocation-free sideband protocol for correlating a host/fuzzer case
// with coverage emitted by an instrumented target firmware. The target sketch
// calls poll_begin() before dispatching a request and emit_after_case() after
// the instrumented parser/state machine returns.
class TargetCoverageSession {
public:
    static constexpr std::size_t kControlLineCapacity = 40;

    template <typename Stream>
    bool poll_begin(Stream& stream) noexcept {
        bool accepted = false;
        while (stream.available() > 0) {
            const int value = stream.read();
            if (value < 0) continue;
            const char ch = static_cast<char>(value);
            if (discard_until_newline_) {
                if (ch == '\n') {
                    discard_until_newline_ = false;
                    length_ = 0;
                }
                continue;
            }
            if (ch == '\r') continue;
            if (ch == '\n') {
                line_[length_] = '\0';
                std::uint32_t parsed = 0;
                if (parse_begin(line_, length_, parsed)) {
                    active_run_ = parsed;
                    active_ = true;
                    g_nexus_coverage.reset();
                    char ready[40]{};
                    (void)std::snprintf(ready, sizeof(ready), "NXCOV_READY,%lu",
                                        static_cast<unsigned long>(active_run_));
                    stream.println(ready);
                    accepted = true;
                }
                length_ = 0;
            } else if (length_ < kControlLineCapacity - 1U) {
                line_[length_++] = ch;
            } else {
                // Oversized/malformed control messages are discarded to the
                // next delimiter rather than truncated into a valid command.
                length_ = 0;
                discard_until_newline_ = true;
            }
        }
        return accepted;
    }

    template <typename Stream>
    bool emit_after_case(Stream& stream) noexcept {
        if (!active_) return false;
        char record[600]{};
        if (!g_nexus_coverage.format_record(record, sizeof(record), active_run_)) return false;
        stream.println(record);
        active_ = false;
        return true;
    }

    [[nodiscard]] bool active() const noexcept { return active_; }
    [[nodiscard]] std::uint32_t run_id() const noexcept { return active_run_; }

private:
    static bool parse_begin(const char* line, std::size_t length,
                            std::uint32_t& run_id) noexcept {
        constexpr char prefix[] = "NXCOV_BEGIN,";
        constexpr std::size_t prefix_size = sizeof(prefix) - 1U;
        if (length <= prefix_size) return false;
        for (std::size_t i = 0; i < prefix_size; ++i) {
            if (line[i] != prefix[i]) return false;
        }
        std::uint32_t value = 0;
        for (std::size_t i = prefix_size; i < length; ++i) {
            const char ch = line[i];
            if (ch < '0' || ch > '9') return false;
            const std::uint32_t digit = static_cast<std::uint32_t>(ch - '0');
            if (value > (UINT32_MAX - digit) / 10U) return false;
            value = value * 10U + digit;
        }
        run_id = value;
        return true;
    }

    char line_[kControlLineCapacity]{};
    std::size_t length_{0};
    std::uint32_t active_run_{0};
    bool active_{false};
    bool discard_until_newline_{false};
};

} // namespace nexus
