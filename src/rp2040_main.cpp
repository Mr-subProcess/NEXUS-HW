#if defined(ARDUINO_ARCH_RP2040)
#include <Arduino.h>
#include <SPI.h>
#include <Wire.h>
#include <pico/time.h>

#include "nexus/engine.hpp"
#include "nexus/campaign.hpp"
#include "nexus/mutator.hpp"
#include "nexus/coverage.hpp"
#include "../examples/lab_corpus.hpp"

#ifndef NEXUS_AUTHORIZED_LAB_TARGET
#define NEXUS_AUTHORIZED_LAB_TARGET 0
#endif
#ifndef NEXUS_ACTIVE_FUZZ_ENABLED
#define NEXUS_ACTIVE_FUZZ_ENABLED 0
#endif
#ifndef NEXUS_LINK_MODE
#define NEXUS_LINK_MODE 1
#endif
#ifndef NEXUS_UART_RX_PIN
#define NEXUS_UART_RX_PIN 5
#endif
#ifndef NEXUS_UART_TX_PIN
#define NEXUS_UART_TX_PIN 4
#endif
#ifndef NEXUS_SPI_SCK_PIN
#define NEXUS_SPI_SCK_PIN 18
#endif
#ifndef NEXUS_SPI_MISO_PIN
#define NEXUS_SPI_MISO_PIN 16
#endif
#ifndef NEXUS_SPI_MOSI_PIN
#define NEXUS_SPI_MOSI_PIN 19
#endif
#ifndef NEXUS_SPI_CS_PIN
#define NEXUS_SPI_CS_PIN 17
#endif
#ifndef NEXUS_I2C_SDA_PIN
#define NEXUS_I2C_SDA_PIN 8
#endif
#ifndef NEXUS_I2C_SCL_PIN
#define NEXUS_I2C_SCL_PIN 9
#endif
#ifndef NEXUS_I2C_ADDRESS
#define NEXUS_I2C_ADDRESS 0x42
#endif
#ifndef NEXUS_I2C_READ_LENGTH
#define NEXUS_I2C_READ_LENGTH 16
#endif

namespace {
using namespace nexus;
constexpr std::uint32_t kRunLimit = 128;

class PicoClock final : public IClock {
public:
    // Arduino micros() is typically a wrapping 32-bit counter on RP2040.
    // time_us_64() avoids ~71-minute wraparound in long fuzz campaigns.
    std::uint64_t now_us() const noexcept override { return time_us_64(); }
    void sleep_us(std::uint32_t us) noexcept override {
        if (us >= 1000U) delay(us / 1000U);
        else delayMicroseconds(us);
    }
};

#if NEXUS_LINK_MODE == 1
class PicoUart final : public ITransport {
public:
    bool begin() noexcept override {
        Serial1.setRX(NEXUS_UART_RX_PIN);
        Serial1.setTX(NEXUS_UART_TX_PIN);
        Serial1.begin(115200);
        return true;
    }
    void end() noexcept override { Serial1.end(); }
    LinkKind kind() const noexcept override { return LinkKind::Uart; }
    IoStatus exchange(const Frame& tx, Frame& rx, std::uint32_t timeout_us) noexcept override {
        if (!tx.valid()) return IoStatus::InvalidFrame;
        while (Serial1.available() > 0) (void)Serial1.read();
        if (Serial1.write(tx.bytes.data(), tx.size) != tx.size) return IoStatus::BusError;
        Serial1.flush();
        const std::uint32_t start = micros();
        std::uint32_t last_rx = start;
        bool received = false;
        while (static_cast<std::uint32_t>(micros() - start) < timeout_us) {
            while (Serial1.available() > 0 && rx.size < kMaxFrameBytes) {
                const int value = Serial1.read();
                if (value >= 0) {
                    rx.bytes[rx.size++] = static_cast<std::uint8_t>(value);
                    last_rx = micros(); received = true;
                }
            }
            if (rx.size >= kMaxFrameBytes && Serial1.available() > 0) return IoStatus::FrameOverflow;
            if (received && static_cast<std::uint32_t>(micros() - last_rx) >= 1500U)
                return IoStatus::Ok;
            yield();
        }
        return received ? IoStatus::Ok : IoStatus::Timeout;
    }
};
#elif NEXUS_LINK_MODE == 2
class PicoSpi final : public ITransport {
public:
    bool begin() noexcept override {
        SPI.setSCK(NEXUS_SPI_SCK_PIN); SPI.setRX(NEXUS_SPI_MISO_PIN);
        SPI.setTX(NEXUS_SPI_MOSI_PIN); SPI.begin();
        pinMode(NEXUS_SPI_CS_PIN, OUTPUT); digitalWrite(NEXUS_SPI_CS_PIN, HIGH);
        return true;
    }
    void end() noexcept override { SPI.end(); }
    LinkKind kind() const noexcept override { return LinkKind::Spi; }
    IoStatus exchange(const Frame& tx, Frame& rx, std::uint32_t) noexcept override {
        if (!tx.valid()) return IoStatus::InvalidFrame;
        SPI.beginTransaction(SPISettings(100000, MSBFIRST, SPI_MODE0));
        digitalWrite(NEXUS_SPI_CS_PIN, LOW);
        for (std::uint16_t i = 0; i < tx.size; ++i)
            rx.bytes[rx.size++] = SPI.transfer(tx.bytes[i]);
        digitalWrite(NEXUS_SPI_CS_PIN, HIGH); SPI.endTransaction();
        return IoStatus::Ok;
    }
};
#elif NEXUS_LINK_MODE == 3
class PicoI2c final : public ITransport {
public:
    bool begin() noexcept override {
        Wire.setSDA(NEXUS_I2C_SDA_PIN); Wire.setSCL(NEXUS_I2C_SCL_PIN);
        return Wire.begin();
    }
    void end() noexcept override { Wire.end(); }
    LinkKind kind() const noexcept override { return LinkKind::I2c; }
    IoStatus exchange(const Frame& tx, Frame& rx, std::uint32_t timeout_us) noexcept override {
        if (!tx.valid()) return IoStatus::InvalidFrame;
        Wire.beginTransmission(NEXUS_I2C_ADDRESS);
        if (Wire.write(tx.bytes.data(), tx.size) != tx.size) return IoStatus::BusError;
        const std::uint8_t rc = Wire.endTransmission(true);
        if (rc != 0U) return rc == 2U ? IoStatus::BusError : IoStatus::Timeout;
        // Issue exactly one read transaction; do not retry requestFrom() in a
        // polling loop because that would send repeated target transactions.
        const std::size_t requested = Wire.requestFrom(static_cast<int>(NEXUS_I2C_ADDRESS),
                                                        static_cast<int>(NEXUS_I2C_READ_LENGTH));
        if (requested == 0U) return IoStatus::Timeout;
        const std::uint32_t started = micros();
        while (Wire.available() == 0 && static_cast<std::uint32_t>(micros() - started) < timeout_us) yield();
        while (Wire.available() > 0 && rx.size < kMaxFrameBytes) {
            const int value = Wire.read();
            if (value >= 0) rx.bytes[rx.size++] = static_cast<std::uint8_t>(value);
        }
        return rx.size > 0 ? IoStatus::Ok : IoStatus::Timeout;
    }
};
#else
#error "NEXUS_LINK_MODE must be 1 (UART), 2 (SPI), or 3 (I2C)"
#endif

#if NEXUS_LINK_MODE == 1
PicoUart transport;
#elif NEXUS_LINK_MODE == 2
PicoSpi transport;
#else
PicoI2c transport;
#endif
PicoClock clock_source;
EngineConfig config{};
ProtocolProfile profile{};
SeedSet corpus{};
Mutator mutator(0x5049434FU);
CoverageGuidedScheduler campaign_scheduler{};
Engine* engine_ptr = nullptr;
bool active = false;
bool finished = false;
std::uint32_t case_count = 0;

void print_hex(const Frame& frame) {
    for (std::uint16_t i = 0; i < frame.size; ++i)
        Serial.printf("%02X", static_cast<unsigned>(frame.bytes[i]));
}

void finish_run() {
    if (finished || engine_ptr == nullptr) return;
    finished = true;
    engine_ptr->end();
    Serial.printf("DONE platform=RP2040 cases=%lu states=%u edges=%u halted=%u\n",
                  static_cast<unsigned long>(engine_ptr->executed_cases()),
                  static_cast<unsigned>(engine_ptr->graph().state_count()),
                  static_cast<unsigned>(engine_ptr->graph().edge_count()),
                  engine_ptr->halted() ? 1U : 0U);
    Serial.printf("CAMPAIGN_SUMMARY executions=%lu admissions=%lu novel_edges=%lu corpus=%u dropped=%lu target_binary_coverage=not_instrumented\n",
                  static_cast<unsigned long>(campaign_scheduler.total_executions()),
                  static_cast<unsigned long>(campaign_scheduler.total_admissions()),
                  static_cast<unsigned long>(campaign_scheduler.total_novel_edges()),
                  static_cast<unsigned>(campaign_scheduler.seed_count()),
                  static_cast<unsigned long>(campaign_scheduler.dropped_candidates()));
    for (const auto& crash : engine_ptr->crash_records()) {
        if (!crash.used) continue;
        Serial.printf("CRASH_SUSPECTED,case=%lu,tag=%04X,latency_us=%lu,failed_heartbeats=%u,trigger=",
                      static_cast<unsigned long>(crash.case_id), static_cast<unsigned>(crash.command_tag),
                      static_cast<unsigned long>(crash.latency_us), static_cast<unsigned>(crash.failed_heartbeats));
        print_hex(crash.trigger); Serial.println();
    }
    Serial.println("RP2040_DIAG_NOTE: capture target panic UART with a separate USB-UART adapter; attach exact target ELF and MAP.");
}
} // namespace

void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println("NEXUS-HW RP2040 / Pico | v0.7.0 | response-transition-guided runner");
    if (!NEXUS_AUTHORIZED_LAB_TARGET || !NEXUS_ACTIVE_FUZZ_ENABLED) {
        Serial.println("DISARMED: enable both build flags only for an isolated, owner-authorized lab fixture.");
        return;
    }
    corpus = nexus::example::make_lab_corpus();
    profile = nexus::example::make_lab_profile();
    config.authorized_lab_target = true;
    config.active_fuzz_enabled = true;
    config.max_cases = kRunLimit;
    config.timeout_us = 20000;
    config.minimum_interval_us = 100000;
    config.calibration_rounds = 4;
    config.max_consecutive_io_errors = 3;
    config.liveness.enabled = true;
    config.liveness.request = corpus.entries[0].frame;
    config.liveness.expected_response = profile.ack;
    config.liveness.retries = 2;
    config.liveness.retry_delay_us = 20000;

    static Engine engine(transport, clock_source, config, profile);
    engine_ptr = &engine;
    if (!campaign_scheduler.initialize(corpus)) {
        Serial.println("ERROR: initial campaign corpus is invalid");
        return;
    }
    campaign_scheduler.set_seed(0x5049434FU);
    if (!engine.begin()) { Serial.println("ERROR: transport initialization failed"); return; }
    if (!engine.calibrate(corpus)) { Serial.println("ERROR: calibration failed"); engine.end(); return; }
    active = true;
    Serial.println("CALIBRATION complete; bounded fuzz run starting.");
}

void loop() {
    if (!active || finished || engine_ptr == nullptr) { delay(20); return; }
    const CampaignSeed* selected = campaign_scheduler.select();
    if (selected == nullptr) { active = false; finish_run(); return; }
    const CorpusEntry parent = selected->corpus;
    SeedSet one_seed{}; one_seed.count = 1; one_seed.entries[0] = parent;
    Frame input{}; std::uint32_t generated_id = 0; std::uint16_t tag = 0; MutationKind mutation{};
    if (!mutator.next(one_seed, input, generated_id, tag, mutation)) { active = false; finish_run(); return; }
    const CaseResult result = engine_ptr->execute(input, generated_id, tag, mutation);
    FeedbackSnapshot feedback = transition_feedback(result.state_before, result.state_after, result.response_kind);
    CorpusEntry candidate = parent; candidate.frame = input;
    const CampaignObservation observation = campaign_scheduler.observe(
        candidate, feedback, result.response_kind, result.case_id, false);
    Serial.printf("CAMPAIGN case=%lu corpus=%u novel_edges=%u new_outcome=%u admitted=%u target_cov=0\n",
                  static_cast<unsigned long>(result.case_id),
                  static_cast<unsigned>(campaign_scheduler.seed_count()),
                  static_cast<unsigned>(observation.novel_edges),
                  observation.new_outcome ? 1U : 0U,
                  observation.new_seed ? 1U : 0U);
    ++case_count;
    Serial.printf("NEXUS,case=%lu,tag=%04X,kind=%u,state_before=%u,state_after=%u,latency_us=%lu,timing_candidate=%u,health=%u,crash_suspected=%u,input=",
                  static_cast<unsigned long>(result.case_id), static_cast<unsigned>(result.command_tag),
                  static_cast<unsigned>(result.response_kind), static_cast<unsigned>(result.state_before),
                  static_cast<unsigned>(result.state_after), static_cast<unsigned long>(result.latency_us),
                  result.timing_anomaly_candidate ? 1U : 0U, static_cast<unsigned>(result.target_health),
                  result.crash_suspected ? 1U : 0U);
    print_hex(input); Serial.println();
    if (engine_ptr->halted() || case_count >= kRunLimit || engine_ptr->case_budget_exhausted()) {
        active = false; finish_run();
    }
    yield();
}
#endif
