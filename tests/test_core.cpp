#include "nexus/analysis.hpp"
#include "nexus/checksum.hpp"
#include "nexus/coverage.hpp"
#include "nexus/engine.hpp"
#include "nexus/campaign.hpp"
#include "nexus/mutator.hpp"
#include "nexus/opcode_survey.hpp"
#include "nexus/spsc_queue.hpp"
#include "nexus/target_coverage_link.hpp"

#include <cstdio>
#include <string>
#include <cstdlib>
#include <cstdint>
#include <string_view>
#include <utility>

class MockByteStream {
public:
    explicit MockByteStream(std::string input = {}) : input_(std::move(input)) {}
    int available() const noexcept { return static_cast<int>(input_.size() - cursor_); }
    int read() noexcept { return cursor_ < input_.size() ? static_cast<unsigned char>(input_[cursor_++]) : -1; }
    void println(const char* value) { output_ += value; output_ += "\n"; }
    const std::string& output() const noexcept { return output_; }
private:
    std::string input_;
    std::size_t cursor_{0};
    std::string output_;
};

#define CHECK(condition) do { if (!(condition)) { \
    std::fprintf(stderr, "CHECK failed at %s:%d: %s\n", __FILE__, __LINE__, #condition); \
    std::exit(1); \
} } while (false)

class TestClock final : public nexus::IClock {
public:
    std::uint64_t now_us() const noexcept override { return now_; }
    void sleep_us(std::uint32_t value) noexcept override { now_ += value; }
private:
    std::uint64_t now_{1};
};

class TimeoutTransport final : public nexus::ITransport {
public:
    bool begin() noexcept override { began = true; return true; }
    void end() noexcept override { began = false; }
    nexus::IoStatus exchange(const nexus::Frame&, nexus::Frame&,
                             std::uint32_t) noexcept override {
        return nexus::IoStatus::Timeout;
    }
    nexus::LinkKind kind() const noexcept override { return nexus::LinkKind::Uart; }
    bool began{false};
};


class OversizedTransport final : public nexus::ITransport {
public:
    bool begin() noexcept override { began = true; return true; }
    void end() noexcept override { began = false; }
    nexus::IoStatus exchange(const nexus::Frame&, nexus::Frame& rx,
                             std::uint32_t) noexcept override {
        rx.size = static_cast<std::uint16_t>(nexus::kMaxFrameBytes + 1U);
        return nexus::IoStatus::Ok;
    }
    nexus::LinkKind kind() const noexcept override { return nexus::LinkKind::Uart; }
    bool began{false};
};

class LivenessTransport final : public nexus::ITransport {
public:
    explicit LivenessTransport(bool heartbeat_works) noexcept : heartbeat_works_(heartbeat_works) {}
    bool begin() noexcept override { began = true; return true; }
    void end() noexcept override { began = false; }
    nexus::IoStatus exchange(const nexus::Frame& tx, nexus::Frame& rx,
                             std::uint32_t) noexcept override {
        if (!began) return nexus::IoStatus::BusError;
        if (tx.bytes[0] == 0xB0) {
            if (!heartbeat_works_) return nexus::IoStatus::Timeout;
            rx.size = 1; rx.bytes[0] = 0x06;
            return nexus::IoStatus::Ok;
        }
        if (tx.bytes[0] == 0xA5 && tx.size > 1 && tx.bytes[1] == 0xFF)
            return nexus::IoStatus::Timeout;
        rx.size = 1; rx.bytes[0] = 0x06;
        return nexus::IoStatus::Ok;
    }
    nexus::LinkKind kind() const noexcept override { return nexus::LinkKind::Uart; }
    bool began{false};
private:
    bool heartbeat_works_{false};
};

class OpcodeTransport final : public nexus::ITransport {
public:
    bool begin() noexcept override { began = true; return true; }
    void end() noexcept override { began = false; }
    nexus::IoStatus exchange(const nexus::Frame& tx, nexus::Frame& rx,
                             std::uint32_t) noexcept override {
        if (!began) return nexus::IoStatus::BusError;
        rx.size = 1;
        rx.bytes[0] = tx.bytes[0] == 0x10 ? 0x06 : 0x15;
        return nexus::IoStatus::Ok;
    }
    nexus::LinkKind kind() const noexcept override { return nexus::LinkKind::Uart; }
    bool began{false};
};

int main() {
    using namespace nexus;
    SeedSet corpus{};
    corpus.count = 1;
    auto& entry = corpus.entries[0];
    entry.frame.size = 4;
    entry.frame.bytes = {0xA5, 0x10, 0x20, 0x30};
    entry.immutable_prefix = 1;
    entry.minimum_mutable_bytes = 1;
    entry.command_tag = 7;

    Mutator mutator(1234);
    Frame out{};
    std::uint32_t id{};
    std::uint16_t tag{};
    MutationKind kind{};
    for (int i = 0; i < 100; ++i) {
        CHECK(mutator.next(corpus, out, id, tag, kind));
        CHECK(out.size == 4);
        CHECK(out.bytes[0] == 0xA5);
        CHECK(tag == 7);
    }

    ProtocolProfile profile{};
    profile.ack.size = 1;
    profile.ack.bytes[0] = 0x06;
    profile.nack.size = 1;
    profile.nack.bytes[0] = 0x15;
    profile.device_error.size = 1;
    profile.device_error.bytes[0] = 0x7F;
    Frame ack{};
    ack.size = 1;
    ack.bytes[0] = 0x06;
    CHECK(classify(ack, IoStatus::Ok, profile) == ResponseKind::Ack);

    StateGraph graph{};
    Frame state_a{}; state_a.size = 1; state_a.bytes[0] = 0x06;
    Frame state_b{}; state_b.size = 1; state_b.bytes[0] = 0x42;
    const auto a = graph.observe_state(state_a, ResponseKind::Ack);
    const auto b = graph.observe_state(state_b, ResponseKind::Data);
    CHECK(graph.observe_state(state_a, ResponseKind::Ack) == a);
    graph.observe_edge(a, b, 7, ResponseKind::Data);
    graph.observe_edge(a, b, 7, ResponseKind::Data);
    Frame state_c{}; state_c.size = 2; state_c.bytes[0] = 0x06; state_c.bytes[1] = 0x00;
    CHECK(graph.observe_state(state_c, ResponseKind::Ack) != a);
    CHECK(graph.state_count() == 3);
    CHECK(graph.edge_count() == 1);
    CHECK(graph.edges()[0].traversals == 2);

    SpscQueue<std::uint32_t, 4> q{};
    CHECK(q.push(42));
    std::uint32_t value{};
    CHECK(q.pop(value) && value == 42);
    CHECK(q.empty());

    // Standard checksum test vectors for ASCII "123456789".
    constexpr std::uint8_t check_data[] = {'1','2','3','4','5','6','7','8','9'};
    CHECK(checksum_compute(check_data, sizeof(check_data), ChecksumAlgorithm::Xor8) == 0x31U);
    CHECK(checksum_compute(check_data, sizeof(check_data), ChecksumAlgorithm::Sum8) == 0xDDU);
    CHECK(checksum_compute(check_data, sizeof(check_data), ChecksumAlgorithm::Crc8Maxim) == 0xA1U);
    CHECK(checksum_compute(check_data, sizeof(check_data), ChecksumAlgorithm::Crc16CcittFalse) == 0x29B1U);
    CHECK(checksum_compute(check_data, sizeof(check_data), ChecksumAlgorithm::Crc16Modbus) == 0x4B37U);
    CHECK(checksum_compute(check_data, sizeof(check_data), ChecksumAlgorithm::Crc32Ieee) == 0xCBF43926UL);
    ChecksumSpec custom_crc8{};
    custom_crc8.enabled = true; custom_crc8.algorithm = ChecksumAlgorithm::Crc8Custom;
    custom_crc8.polynomial = 0x07U; custom_crc8.initial = 0U; custom_crc8.xor_out = 0U;
    CHECK(checksum_compute(check_data, sizeof(check_data), custom_crc8) == 0xF4U);
    ChecksumSpec custom_crc16{};
    custom_crc16.enabled = true; custom_crc16.algorithm = ChecksumAlgorithm::Crc16Custom;
    custom_crc16.polynomial = 0x1021U; custom_crc16.initial = 0xFFFFU;
    custom_crc16.xor_out = 0xFFFFU; custom_crc16.reflect_input = true;
    custom_crc16.reflect_output = true;
    CHECK(checksum_compute(check_data, sizeof(check_data), custom_crc16) == 0x906EU);
    Frame invalid_custom_frame{}; invalid_custom_frame.size = 4;
    ChecksumSpec invalid_custom{}; invalid_custom.enabled = true;
    invalid_custom.algorithm = ChecksumAlgorithm::Crc8Custom;
    invalid_custom.polynomial = 0x107U; invalid_custom.data_offset = 0;
    invalid_custom.data_length = 2; invalid_custom.checksum_offset = 3;
    CHECK(!checksum_spec_valid(invalid_custom_frame, invalid_custom));

    Frame checksummed{};
    checksummed.size = 4;
    checksummed.bytes[0] = 0xA5; checksummed.bytes[1] = 0x11; checksummed.bytes[2] = 0x22;
    ChecksumSpec crc8_spec{};
    crc8_spec.enabled = true; crc8_spec.algorithm = ChecksumAlgorithm::Crc8Maxim;
    crc8_spec.data_offset = 1; crc8_spec.data_length = 2; crc8_spec.checksum_offset = 3;
    CHECK(apply_checksum(checksummed, crc8_spec));
    CHECK(verify_checksum(checksummed, crc8_spec));
    checksummed.bytes[1] ^= 1U;
    CHECK(!verify_checksum(checksummed, crc8_spec));

    // Fuzzer checksum is recomputed after payload mutation; trailing CRC is not mutated as payload.
    SeedSet crc_corpus{}; crc_corpus.count = 1;
    auto& crc_seed = crc_corpus.entries[0];
    crc_seed.frame.size = 4; crc_seed.frame.bytes = {0xA5, 0x10, 0x20, 0x00};
    crc_seed.immutable_prefix = 1; crc_seed.minimum_mutable_bytes = 1; crc_seed.command_tag = 9;
    crc_seed.checksum = crc8_spec;
    crc_seed.checksum.data_offset = 1; crc_seed.checksum.data_length = 2; crc_seed.checksum.checksum_offset = 3;
    Mutator crc_mutator(77); Frame crc_out{}; std::uint32_t crc_case{}; std::uint16_t crc_tag{}; MutationKind crc_kind{};
    CHECK(crc_mutator.next(crc_corpus, crc_out, crc_case, crc_tag, crc_kind));
    CHECK(verify_checksum(crc_out, crc_seed.checksum));

    SeedSet middle_crc_corpus{}; middle_crc_corpus.count = 1;
    auto& middle_seed = middle_crc_corpus.entries[0];
    middle_seed.frame.size = 5; middle_seed.frame.bytes = {0xA5, 0x10, 0x00, 0x20, 0x30};
    middle_seed.immutable_prefix = 1; middle_seed.minimum_mutable_bytes = 1; middle_seed.command_tag = 10;
    middle_seed.checksum.enabled = true; middle_seed.checksum.algorithm = ChecksumAlgorithm::Crc8Maxim;
    middle_seed.checksum.data_offset = 1; middle_seed.checksum.data_length = 1;
    middle_seed.checksum.checksum_offset = 2;
    CHECK(apply_checksum(middle_seed.frame, middle_seed.checksum));
    Mutator middle_mutator(78); Frame middle_out{};
    CHECK(middle_mutator.next(middle_crc_corpus, middle_out, crc_case, crc_tag, crc_kind));
    CHECK(middle_out.bytes[2] == middle_seed.frame.bytes[2]);
    CHECK(verify_checksum(middle_out, middle_seed.checksum));

    CoverageBitmap<64> coverage{};
    CHECK(coverage.hit(3));
    CHECK(!coverage.hit(3));
    CHECK(coverage.hit(17));
    CHECK(!coverage.hit(65536U)); // prevent integer narrowing from aliasing edge 0
    CHECK(coverage.unique_edges() == 2);
    char coverage_record[96]{};
    CHECK(coverage.format_record(coverage_record, sizeof(coverage_record), 7));
    CHECK(std::string_view(coverage_record).find("NXCOV1,run=7,bits=64,bitmap=") == 0);

    // Coverage-guided campaign scheduler: initialize, collect novel feedback,
    // reject duplicate coverage, admit a new path, and select a weighted seed.
    CoverageGuidedScheduler campaign{};
    CHECK(campaign.initialize(corpus));
    campaign.set_seed(0x12345678U);
    FeedbackSnapshot feedback{};
    CHECK(feedback.add(3));
    CHECK(feedback.add(7));
    CHECK(!feedback.add(3));
    CHECK(feedback.contains(3));
    CorpusEntry candidate = corpus.entries[0];
    candidate.frame.bytes[1] = 0x7FU;
    const auto first_observation = campaign.observe(candidate, feedback, ResponseKind::Ack, 1);
    CHECK(first_observation.admitted && first_observation.new_seed);
    CHECK(first_observation.new_coverage && first_observation.new_outcome);
    CHECK(first_observation.novel_edges == 2);
    CHECK(campaign.total_novel_edges() == 2);
    const auto duplicate_observation = campaign.observe(candidate, feedback, ResponseKind::Ack, 2);
    CHECK(!duplicate_observation.new_coverage);
    CHECK(!duplicate_observation.new_outcome);
    CHECK(!duplicate_observation.admitted);
    FeedbackSnapshot next_feedback{};
    CHECK(next_feedback.add(9));
    const auto same_seed_new_edge = campaign.observe(candidate, next_feedback, ResponseKind::Ack, 3);
    CHECK(same_seed_new_edge.admitted && !same_seed_new_edge.new_seed);
    CHECK(campaign.total_novel_edges() == 3);
    const auto* selected_seed = campaign.select();
    CHECK(selected_seed != nullptr);
    CHECK(campaign.total_executions() == 1);
    CHECK(campaign.seed_count() == 2);
    CHECK(campaign.edge_seen(9));
    CHECK(!campaign.edge_seen(kCampaignMapBits));

    // Target instrumentation telemetry parser: exact run ID, exact bitmap
    // width and strict hexadecimal validation.
    std::string coverage_line = "NXCOV1,run=7,bits=2048,bitmap=";
    for (std::size_t word = 0; word < kCampaignTargetMapWords; ++word) {
        const std::uint32_t value = word == 0 ? 0x00000040U : (word == 63 ? 0x80000000U : 0U);
        char hex_word[9]{};
        std::snprintf(hex_word, sizeof(hex_word), "%08X", static_cast<unsigned>(value));
        coverage_line += hex_word;
    }
    FeedbackSnapshot parsed_coverage{};
    CHECK(parse_nxcov_record(coverage_line, 7, parsed_coverage));
    CHECK(parsed_coverage.contains(6));
    CHECK(parsed_coverage.contains(2047));
    CHECK(parsed_coverage.count == 2);
    CHECK(!parse_nxcov_record(coverage_line, 8, parsed_coverage));
    coverage_line.back() = 'Z';
    CHECK(!parse_nxcov_record(coverage_line, 7, parsed_coverage));
    auto malformed_run = coverage_line;
    malformed_run.replace(malformed_run.find("run=7"), 5, "run=7x");
    CHECK(!parse_nxcov_record(malformed_run, 7, parsed_coverage));
    CHECK(!parse_nxcov_record("NXCOV1,extra=x,run=7,bits=2048,bitmap=", 7, parsed_coverage));

    // Bidirectional target-sideband session: case IDs are correlated out of
    // band, the per-case bitmap resets, and malformed control lines are ignored.
    MockByteStream target_control("NOPE\nNXCOV_BEGIN,41\n");
    nexus::TargetCoverageSession target_session{};
    CHECK(target_session.poll_begin(target_control));
    CHECK(target_session.active() && target_session.run_id() == 41U);
    CHECK(target_control.output() == "NXCOV_READY,41\n");
    CHECK(nexus::g_nexus_coverage.hit(123));
    MockByteStream target_report;
    CHECK(target_session.emit_after_case(target_report));
    CHECK(target_report.output().find("NXCOV1,run=41,bits=2048,bitmap=") == 0);
    CHECK(!target_session.active());
    MockByteStream invalid_control(std::string("NXCOV_BEGIN,") + std::string(80, '9') + "\n");
    CHECK(!target_session.poll_begin(invalid_control));
    MockByteStream recovery_control(std::string("NXCOV_BEGIN,") + std::string(80, '9') +
                                    "\nNXCOV_BEGIN,42\n");
    CHECK(target_session.poll_begin(recovery_control));
    CHECK(target_session.run_id() == 42U);

    OnlineStats stats{};
    stats.add(100); stats.add(101); stats.add(99); stats.add(100);
    CHECK(stats.count == 4);
    CHECK(stats.min_us == 99 && stats.max_us == 101);

    TestClock clock;
    TimeoutTransport timeout_transport;
    EngineConfig disarmed_config{};
    Engine disarmed_engine(timeout_transport, clock, disarmed_config, profile);
    CHECK(!disarmed_engine.begin());
    CHECK(!timeout_transport.began);

    // Repeated failures without a heartbeat remain fail-closed, but are not
    // falsely reported as a confirmed target crash.
    EngineConfig armed_config{};
    armed_config.authorized_lab_target = true;
    armed_config.active_fuzz_enabled = true;
    armed_config.calibration_rounds = 4;
    armed_config.max_consecutive_io_errors = 3;
    Engine timeout_engine(timeout_transport, clock, armed_config, profile);
    CHECK(timeout_engine.begin());
    SeedSet timeout_corpus{};
    timeout_corpus.count = 1;
    timeout_corpus.entries[0].frame.size = 2;
    timeout_corpus.entries[0].frame.bytes[0] = 0x10;
    timeout_corpus.entries[0].frame.bytes[1] = 0x00;
    timeout_corpus.entries[0].immutable_prefix = 1;
    timeout_corpus.entries[0].minimum_mutable_bytes = 1;
    CHECK(!timeout_engine.calibrate(timeout_corpus));
    CHECK(timeout_engine.halted());
    CHECK(timeout_engine.crash_suspicions() == 0);
    timeout_engine.end();

    // Heartbeat distinguishes a protocol-level timeout from a target that is
    // still responding after a fuzz case.
    LivenessTransport alive_transport(true);
    TestClock alive_clock;
    EngineConfig alive_cfg{};
    alive_cfg.authorized_lab_target = true;
    alive_cfg.active_fuzz_enabled = true;
    alive_cfg.max_cases = 8;
    alive_cfg.calibration_rounds = 1;
    alive_cfg.max_consecutive_io_errors = 1;
    alive_cfg.minimum_interval_us = 1;
    alive_cfg.liveness.enabled = true;
    alive_cfg.liveness.request.size = 1;
    alive_cfg.liveness.request.bytes[0] = 0xB0;
    alive_cfg.liveness.expected_response = profile.ack;
    alive_cfg.liveness.retries = 2;

    // Invalid engine configuration and malformed corpus are rejected before any target I/O.
    EngineConfig invalid_cfg = alive_cfg;
    invalid_cfg.max_consecutive_io_errors = 0;
    LivenessTransport invalid_config_transport(true);
    Engine invalid_config_engine(invalid_config_transport, alive_clock, invalid_cfg, profile);
    CHECK(!invalid_config_engine.begin());
    CHECK(!invalid_config_transport.began);

    LivenessTransport preflight_transport(true);
    Engine preflight_engine(preflight_transport, alive_clock, alive_cfg, profile);
    CHECK(preflight_engine.begin());
    SeedSet malformed_corpus{};
    malformed_corpus.count = 2;
    malformed_corpus.entries[0] = corpus.entries[0];
    malformed_corpus.entries[1] = corpus.entries[0];
    malformed_corpus.entries[1].immutable_prefix = 4; // invalid; must reject entire set before exchange
    CHECK(!preflight_engine.calibrate(malformed_corpus));
    CHECK(preflight_engine.executed_cases() == 0);
    preflight_engine.end();

    // A transport that returns a size beyond the fixed frame capacity is converted
    // into a bounded oversized-response event instead of allowing an out-of-bounds read.
    OversizedTransport oversized_transport;
    TestClock oversized_clock;
    EngineConfig oversized_cfg = alive_cfg;
    oversized_cfg.liveness.enabled = false;
    oversized_cfg.calibration_rounds = 1;
    oversized_cfg.max_consecutive_io_errors = 3;
    Engine oversized_engine(oversized_transport, oversized_clock, oversized_cfg, profile);
    CHECK(oversized_engine.begin());
    CHECK(oversized_engine.calibrate(corpus));
    Frame oversized_case{}; oversized_case.size = 2; oversized_case.bytes[0] = 0xA5; oversized_case.bytes[1] = 0x01;
    const auto oversized_result = oversized_engine.execute(oversized_case, 3, 7, MutationKind::BitFlip);
    CHECK(oversized_result.response_kind == ResponseKind::OversizedResponse);
    oversized_engine.end();

    Engine alive_engine(alive_transport, alive_clock, alive_cfg, profile);
    CHECK(alive_engine.begin());
    CHECK(alive_engine.calibrate(corpus));
    Frame timeout_case{};
    timeout_case.size = 2;
    timeout_case.bytes[0] = 0xA5;
    timeout_case.bytes[1] = 0xFF;
    const auto alive_result = alive_engine.execute(timeout_case, 1, 7, MutationKind::BitFlip);
    CHECK(alive_result.response_kind == ResponseKind::Timeout);
    CHECK(alive_result.liveness_checked);
    CHECK(alive_result.target_health == TargetHealth::Alive);
    CHECK(!alive_result.crash_suspected);
    CHECK(!alive_engine.halted());
    CHECK(alive_engine.crash_suspicions() == 0);
    alive_engine.end();

    // A failed heartbeat marks the target as unresponsive/crash-suspected and
    // preserves the triggering frame for deterministic reproduction.
    LivenessTransport dead_transport(false);
    TestClock dead_clock;
    EngineConfig dead_cfg = alive_cfg;
    Engine dead_engine(dead_transport, dead_clock, dead_cfg, profile);
    CHECK(dead_engine.begin());
    CHECK(dead_engine.calibrate(corpus));
    const auto dead_result = dead_engine.execute(timeout_case, 2, 7, MutationKind::BitFlip);
    CHECK(dead_result.liveness_checked);
    CHECK(dead_result.target_health == TargetHealth::Unresponsive);
    CHECK(dead_result.crash_suspected);
    CHECK(dead_engine.halted());
    CHECK(dead_engine.crash_suspicions() == 1);
    CHECK(dead_engine.crash_record_count() == 1);
    CHECK(dead_engine.crash_records()[0].trigger.bytes[1] == 0xFF);
    dead_engine.end();

    // Physical opcode survey accepts only operator-reviewed read-only entries.
    SafeOpcodeManifest manifest{};
    manifest.count = 1;
    manifest.candidates[0].request.size = 1;
    manifest.candidates[0].request.bytes[0] = 0x10;
    manifest.candidates[0].command_tag = 0x10;
    manifest.candidates[0].documented_read_only = true;
    OpcodeSurveyConfig survey_cfg{};
    survey_cfg.authorized_lab_target = true;
    survey_cfg.active_probe_enabled = true;
    survey_cfg.max_probes = 1;
    survey_cfg.timeout_us = 20'000;
    survey_cfg.minimum_interval_us = 0;
    OpcodeSurveyReport report{};
    OpcodeTransport opcode_transport;
    TestClock opcode_clock;
    CHECK(SafeOpcodeSurvey::run(opcode_transport, opcode_clock, manifest,
                                survey_cfg, profile, report));
    CHECK(report.count == 1 && report.accepted == 1);

    manifest.candidates[0].documented_read_only = false;
    OpcodeSurveyReport rejected_report{};
    OpcodeTransport rejected_transport;
    CHECK(!SafeOpcodeSurvey::run(rejected_transport, opcode_clock, manifest,
                                 survey_cfg, profile, rejected_report));
    CHECK(!rejected_transport.began);

    std::puts("NEXUS-HW core tests: PASS");
    return 0;
}
