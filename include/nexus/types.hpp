#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

namespace nexus {

inline constexpr std::size_t kMaxFrameBytes = 128;
inline constexpr std::size_t kMaxCorpusEntries = 16;
inline constexpr std::size_t kMaxStates = 32;
inline constexpr std::size_t kMaxEdges = 96;
inline constexpr std::size_t kMaxFailureEvents = 8;
inline constexpr std::size_t kMaxCrashRecords = 4;
inline constexpr std::size_t kMaxSafeOpcodes = 32;
inline constexpr std::size_t kTimingBuckets = 32;

struct Frame {
    std::array<std::uint8_t, kMaxFrameBytes> bytes{};
    std::uint16_t size{0};

    [[nodiscard]] bool valid() const noexcept {
        return size > 0 && size <= kMaxFrameBytes;
    }
};

enum class ChecksumAlgorithm : std::uint8_t {
    None = 0, Xor8, Sum8, Crc8Maxim, Crc16CcittFalse, Crc16Modbus, Crc32Ieee,
    Crc8Custom, Crc16Custom, Crc32Custom
};

struct ChecksumSpec {
    bool enabled{false};
    ChecksumAlgorithm algorithm{ChecksumAlgorithm::None};
    std::uint8_t data_offset{0};
    std::uint16_t data_length{0};
    std::uint8_t checksum_offset{0};
    bool big_endian{true};
    // Used by Custom CRC variants. Polynomial is expressed in normal MSB-first
    // notation (e.g. CRC-16/X25: 0x1021); reflection is selected separately.
    std::uint32_t polynomial{0};
    std::uint32_t initial{0};
    std::uint32_t xor_out{0};
    bool reflect_input{false};
    bool reflect_output{false};
};

struct CorpusEntry {
    Frame frame{};
    ChecksumSpec checksum{};
    // Bytes [0, immutable_prefix) are never changed. Keep command/opcode/address
    // bytes here; fuzz only the explicitly designated payload suffix.
    std::uint8_t immutable_prefix{1};
    std::uint8_t minimum_mutable_bytes{1};
    std::uint16_t command_tag{0};
};

enum class LinkKind : std::uint8_t { Uart, Spi, I2c };
enum class IoStatus : std::uint8_t { Ok, Timeout, BusError, InvalidFrame, FrameOverflow };
enum class ResponseKind : std::uint8_t { Ack, Nack, DeviceError, Timeout, Data, BusError, OversizedResponse };
enum class MutationKind : std::uint8_t { BitFlip, Arithmetic, InterestingByte, BlockFill };
enum class TargetHealth : std::uint8_t {
    Unknown, Alive, Suspect, Degraded, Unresponsive, LinkFault
};
enum class OpcodeDisposition : std::uint8_t {
    Accepted, Rejected, DeviceError, NoResponse, TransportFault, Invalid
};

struct ExchangeResult {
    IoStatus status{IoStatus::Timeout};
    Frame response{};
    std::uint32_t elapsed_us{0};
};

struct BytePattern {
    std::array<std::uint8_t, 8> bytes{};
    std::uint8_t size{0};

    [[nodiscard]] bool matches(const Frame& frame) const noexcept {
        if (size == 0 || size > bytes.size() || frame.size < size) return false;
        for (std::uint8_t i = 0; i < size; ++i) {
            if (frame.bytes[i] != bytes[i]) return false;
        }
        return true;
    }
};

struct ProtocolProfile {
    BytePattern ack{};
    BytePattern nack{};
    BytePattern device_error{};
};

struct LivenessConfig {
    // Use a documented, read-only status/identity request. Never use a reset,
    // unlock, erase, actuator, or configuration-changing command as a heartbeat.
    bool enabled{false};
    Frame request{};
    BytePattern expected_response{};
    std::uint8_t retries{2};
    std::uint32_t retry_delay_us{20'000};
};

struct CaseResult {
    std::uint32_t case_id{0};
    std::uint16_t command_tag{0};
    std::uint16_t state_before{0xFFFFU};
    std::uint16_t state_after{0xFFFFU};
    std::uint32_t response_fingerprint{0};
    std::uint32_t latency_us{0};
    ResponseKind response_kind{ResponseKind::Timeout};
    MutationKind mutation_kind{MutationKind::BitFlip};
    TargetHealth target_health{TargetHealth::Unknown};
    std::uint8_t failure_streak{0};
    bool timing_anomaly_candidate{false};
    bool liveness_checked{false};
    bool crash_suspected{false};
};

struct FailureEvent {
    std::uint32_t case_id{0};
    std::uint64_t timestamp_us{0};
    std::uint32_t latency_us{0};
    std::uint16_t command_tag{0};
    std::uint8_t consecutive_failures{0};
    ResponseKind response_kind{ResponseKind::Timeout};
    TargetHealth health{TargetHealth::Unknown};
    bool liveness_checked{false};
    bool used{false};
};

struct CrashRecord {
    // A "crash" is intentionally reported as suspected: an external heartbeat
    // cannot distinguish a crashed MCU from a disconnected/stuck bus by itself.
    std::uint32_t case_id{0};
    std::uint64_t timestamp_us{0};
    std::uint16_t command_tag{0};
    std::uint32_t latency_us{0};
    std::uint8_t failed_heartbeats{0};
    Frame trigger{};
    bool used{false};
};


struct EngineConfig {
    // Both flags must be explicitly enabled by the operator for an authorized
    // lab fixture. Defaults are deliberately disarmed.
    bool authorized_lab_target{false};
    bool active_fuzz_enabled{false};
    std::uint32_t max_cases{128};
    std::uint32_t timeout_us{20'000};
    std::uint32_t minimum_interval_us{100'000}; // 10 transactions/second max
    std::uint8_t calibration_rounds{4};
    std::uint8_t max_consecutive_io_errors{3};
    float anomaly_sigma{4.0F};
    LivenessConfig liveness{};
};

struct SeedSet {
    std::array<CorpusEntry, kMaxCorpusEntries> entries{};
    std::uint8_t count{0};
};

// Physical opcode probing is intentionally limited to operator-reviewed,
// documented, read-only command frames. This is not a hidden-backdoor scanner.
struct SafeOpcodeCandidate {
    Frame request{};
    std::uint16_t command_tag{0};
    bool documented_read_only{false};
};

struct SafeOpcodeManifest {
    std::array<SafeOpcodeCandidate, kMaxSafeOpcodes> candidates{};
    std::uint8_t count{0};
};

struct OpcodeObservation {
    std::uint16_t command_tag{0};
    std::uint8_t opcode{0};
    OpcodeDisposition disposition{OpcodeDisposition::Invalid};
    std::uint32_t latency_us{0};
    std::uint32_t response_fingerprint{0};
};

} // namespace nexus
