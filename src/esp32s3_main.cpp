#if defined(ARDUINO_ARCH_ESP32)
#include <Arduino.h>
#include <SPI.h>
#include <Wire.h>
#include <atomic>
#include <esp_timer.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <freertos/idf_additions.h>

#include "nexus/engine.hpp"
#include "nexus/campaign.hpp"
#include "nexus/target_coverage_link.hpp"
#include "nexus/mutator.hpp"
#include "nexus/opcode_survey.hpp"
#include "nexus/spsc_queue.hpp"
#include "../examples/lab_corpus.hpp"

// SAFETY: defaults intentionally disarmed. Set BOTH flags to 1 only for a
// physically isolated, owner-authorized lab target and after reviewing the corpus.
#ifndef NEXUS_AUTHORIZED_LAB_TARGET
#define NEXUS_AUTHORIZED_LAB_TARGET 0
#endif
#ifndef NEXUS_ACTIVE_FUZZ_ENABLED
#define NEXUS_ACTIVE_FUZZ_ENABLED 0
#endif
#ifndef NEXUS_ENABLE_SAFE_OPCODE_SURVEY
#define NEXUS_ENABLE_SAFE_OPCODE_SURVEY 0
#endif

// Select exactly one physical interface at build time.
// 1 = UART (default), 2 = SPI, 3 = I2C.
#ifndef NEXUS_LINK_MODE
#define NEXUS_LINK_MODE 1
#endif

// ESP32-S3 pin defaults are examples only. Verify the exact dev-board pinout.
#ifndef NEXUS_UART_RX_PIN
#define NEXUS_UART_RX_PIN 18
#endif
#ifndef NEXUS_UART_TX_PIN
#define NEXUS_UART_TX_PIN 17
#endif
#ifndef NEXUS_SPI_SCK_PIN
#define NEXUS_SPI_SCK_PIN 12
#endif
#ifndef NEXUS_SPI_MISO_PIN
#define NEXUS_SPI_MISO_PIN 13
#endif
#ifndef NEXUS_SPI_MOSI_PIN
#define NEXUS_SPI_MOSI_PIN 11
#endif
#ifndef NEXUS_SPI_CS_PIN
#define NEXUS_SPI_CS_PIN 10
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
#ifndef NEXUS_TARGET_DIAG_UART_ENABLED
#define NEXUS_TARGET_DIAG_UART_ENABLED 0
#endif
#ifndef NEXUS_TARGET_DIAG_RX_PIN
#define NEXUS_TARGET_DIAG_RX_PIN 16
#endif
#ifndef NEXUS_TARGET_DIAG_TX_PIN
#define NEXUS_TARGET_DIAG_TX_PIN 15
#endif
#ifndef NEXUS_TARGET_DIAG_BAUD
#define NEXUS_TARGET_DIAG_BAUD 115200
#endif
#ifndef NEXUS_TARGET_COV_SYNC_ENABLED
#define NEXUS_TARGET_COV_SYNC_ENABLED 0
#endif
#if NEXUS_TARGET_COV_SYNC_ENABLED && !NEXUS_TARGET_DIAG_UART_ENABLED
#error "NEXUS_TARGET_COV_SYNC_ENABLED requires NEXUS_TARGET_DIAG_UART_ENABLED=1"
#endif
#ifndef NEXUS_TARGET_COV_WAIT_MS
#define NEXUS_TARGET_COV_WAIT_MS 100
#endif
#ifndef NEXUS_TARGET_SYNC_WAIT_MS
#define NEXUS_TARGET_SYNC_WAIT_MS 25
#endif

namespace {
using namespace nexus;

class EspClock final : public IClock {
public:
    std::uint64_t now_us() const noexcept override { return static_cast<std::uint64_t>(esp_timer_get_time()); }
    void sleep_us(std::uint32_t us) noexcept override {
        if (us >= 1000U) vTaskDelay(pdMS_TO_TICKS(us / 1000U));
        else delayMicroseconds(us);
    }
};

#if NEXUS_LINK_MODE == 1
class EspUart final : public ITransport {
public:
    bool begin() noexcept override {
        Serial1.begin(115200, SERIAL_8N1, NEXUS_UART_RX_PIN, NEXUS_UART_TX_PIN);
        return true;
    }
    void end() noexcept override { Serial1.end(); }
    LinkKind kind() const noexcept override { return LinkKind::Uart; }
    IoStatus exchange(const Frame& tx, Frame& rx, std::uint32_t timeout_us) noexcept override {
        if (!tx.valid()) return IoStatus::InvalidFrame;
        while (Serial1.available() > 0) (void)Serial1.read(); // discard stale bytes
        const std::size_t written = Serial1.write(tx.bytes.data(), tx.size);
        Serial1.flush();
        if (written != tx.size) return IoStatus::BusError;
        const std::uint32_t start = micros();
        std::uint32_t last_byte = start;
        bool received = false;
        while (static_cast<std::uint32_t>(micros() - start) < timeout_us) {
            while (Serial1.available() > 0 && rx.size < kMaxFrameBytes) {
                const int value = Serial1.read();
                if (value >= 0) {
                    rx.bytes[rx.size++] = static_cast<std::uint8_t>(value);
                    last_byte = micros();
                    received = true;
                }
            }
            if (rx.size >= kMaxFrameBytes && Serial1.available() > 0) return IoStatus::FrameOverflow;
            if (received && static_cast<std::uint32_t>(micros() - last_byte) >= 1500U) return IoStatus::Ok;
            taskYIELD();
        }
        return received ? IoStatus::Ok : IoStatus::Timeout;
    }
};
#elif NEXUS_LINK_MODE == 2
class EspSpi final : public ITransport {
public:
    bool begin() noexcept override {
        pinMode(NEXUS_SPI_CS_PIN, OUTPUT);
        digitalWrite(NEXUS_SPI_CS_PIN, HIGH);
        SPI.begin(NEXUS_SPI_SCK_PIN, NEXUS_SPI_MISO_PIN, NEXUS_SPI_MOSI_PIN, NEXUS_SPI_CS_PIN);
        return true;
    }
    void end() noexcept override { SPI.end(); }
    LinkKind kind() const noexcept override { return LinkKind::Spi; }
    IoStatus exchange(const Frame& tx, Frame& rx, std::uint32_t) noexcept override {
        if (!tx.valid()) return IoStatus::InvalidFrame;
        SPI.beginTransaction(SPISettings(100000, MSBFIRST, SPI_MODE0));
        digitalWrite(NEXUS_SPI_CS_PIN, LOW);
        for (std::uint16_t i = 0; i < tx.size; ++i) rx.bytes[rx.size++] = SPI.transfer(tx.bytes[i]);
        digitalWrite(NEXUS_SPI_CS_PIN, HIGH);
        SPI.endTransaction();
        return IoStatus::Ok;
    }
};
#elif NEXUS_LINK_MODE == 3
class EspI2c final : public ITransport {
public:
    bool begin() noexcept override { Wire.begin(NEXUS_I2C_SDA_PIN, NEXUS_I2C_SCL_PIN); return true; }
    void end() noexcept override { Wire.end(); }
    LinkKind kind() const noexcept override { return LinkKind::I2c; }
    IoStatus exchange(const Frame& tx, Frame& rx, std::uint32_t) noexcept override {
        if (!tx.valid()) return IoStatus::InvalidFrame;
        Wire.beginTransmission(NEXUS_I2C_ADDRESS); // fixed configured address; no bus scan
        const std::size_t written = Wire.write(tx.bytes.data(), tx.size);
        if (written != tx.size) return IoStatus::BusError;
        const std::uint8_t error = Wire.endTransmission(true);
        if (error != 0) return error == 2 ? IoStatus::BusError : IoStatus::Timeout;
        const std::uint8_t wanted = static_cast<std::uint8_t>(NEXUS_I2C_READ_LENGTH);
        const std::uint8_t received = static_cast<std::uint8_t>(Wire.requestFrom(
            static_cast<std::uint8_t>(NEXUS_I2C_ADDRESS), wanted));
        for (std::uint8_t i = 0; i < received && rx.size < kMaxFrameBytes; ++i) {
            const int value = Wire.read();
            if (value >= 0) rx.bytes[rx.size++] = static_cast<std::uint8_t>(value);
        }
        return rx.size > 0 ? IoStatus::Ok : IoStatus::Timeout;
    }
};
#endif

#if NEXUS_LINK_MODE == 1
EspUart transport;
#elif NEXUS_LINK_MODE == 2
EspSpi transport;
#else
EspI2c transport;
#endif
EspClock clock_source;
SeedSet corpus{};
EngineConfig cfg{};
ProtocolProfile profile{};
Engine* engine_ptr = nullptr;
Mutator mutator{0xABCD1234U};
CoverageGuidedScheduler campaign_scheduler{};

#if NEXUS_TARGET_DIAG_UART_ENABLED
// Optional bidirectional sideband for TARGET coverage correlation and panic logs.
// Wire both directions through voltage-compatible interfaces; never tie TX pins together.
char target_diag_line[640]{};
std::uint16_t target_diag_length = 0;
bool pump_target_diagnostics(FeedbackSnapshot* case_coverage = nullptr,
                             std::uint32_t expected_case = UINT32_MAX,
                             bool* ready_ack = nullptr) {
    bool matched_coverage = false;
    while (Serial2.available() > 0) {
        const int value = Serial2.read();
        if (value < 0) continue;
        const char ch = static_cast<char>(value);
        if (ch == '\r') continue;
        if (ch == '\n' || target_diag_length >= sizeof(target_diag_line) - 1U) {
            target_diag_line[target_diag_length] = '\0';
            const std::string_view line(target_diag_line, target_diag_length);
            if (ready_ack != nullptr && expected_case != UINT32_MAX) {
                char expected_ready[40]{};
                snprintf(expected_ready, sizeof(expected_ready), "NXCOV_READY,%lu",
                         static_cast<unsigned long>(expected_case));
                if (line == expected_ready) *ready_ack = true;
            }
            if (case_coverage != nullptr && expected_case != UINT32_MAX) {
                FeedbackSnapshot parsed{};
                if (parse_nxcov_record(line, expected_case, parsed)) {
                    merge_feedback(*case_coverage, parsed);
                    matched_coverage = true;
                }
            }
            Serial.print("TARGET_LOG ");
            Serial.println(target_diag_line);
            target_diag_length = 0;
        } else {
            target_diag_line[target_diag_length++] = ch;
        }
    }
    return matched_coverage;
}

#if NEXUS_TARGET_COV_SYNC_ENABLED
bool begin_target_coverage_case(std::uint32_t case_id) {
    Serial2.printf("NXCOV_BEGIN,%lu\n", static_cast<unsigned long>(case_id));
    Serial2.flush();
    const std::uint32_t started = millis();
    bool acknowledged = false;
    do {
        (void)pump_target_diagnostics(nullptr, case_id, &acknowledged);
        if (acknowledged) return true;
        vTaskDelay(pdMS_TO_TICKS(1));
    } while (static_cast<std::uint32_t>(millis() - started) < NEXUS_TARGET_SYNC_WAIT_MS);
    return false;
}

bool collect_target_coverage(std::uint32_t case_id, FeedbackSnapshot& coverage) {
    const std::uint32_t started = millis();
    bool matched = false;
    do {
        matched = pump_target_diagnostics(&coverage, case_id) || matched;
        if (matched) return true;
        vTaskDelay(pdMS_TO_TICKS(1));
    } while (static_cast<std::uint32_t>(millis() - started) < NEXUS_TARGET_COV_WAIT_MS);
    return matched;
}
#else
bool begin_target_coverage_case(std::uint32_t) { return true; }
bool collect_target_coverage(std::uint32_t, FeedbackSnapshot&) {
    (void)pump_target_diagnostics(); // capture panic/debug lines without blocking on coverage
    return false;
}
#endif
#else
bool pump_target_diagnostics(FeedbackSnapshot* = nullptr, std::uint32_t = UINT32_MAX, bool* = nullptr) { return false; }
bool begin_target_coverage_case(std::uint32_t) { return true; }
bool collect_target_coverage(std::uint32_t, FeedbackSnapshot&) { return false; }
#endif

struct WorkItem {
    Frame frame{};
    std::uint32_t case_id{0};
    std::uint16_t tag{0};
    MutationKind mutation{MutationKind::BitFlip};
};
struct FeedbackItem {
    FeedbackSnapshot coverage{};
    std::uint32_t case_id{0};
    ResponseKind outcome{ResponseKind::Data};
    bool target_instrumentation_seen{false};
};
SpscQueue<WorkItem, 2> work_queue{};
SpscQueue<FeedbackItem, 2> feedback_queue{};
StaticTask_t producer_tcb{};
StaticTask_t consumer_tcb{};
StackType_t producer_stack[4096]{};
StackType_t consumer_stack[6144]{};
std::atomic<bool> producer_done{false};
std::atomic<bool> stop_requested{false};
std::atomic<bool> run_done{false};
std::atomic<std::uint32_t> generated{0};
constexpr std::uint32_t kFirmwareCaseLimit = 64;

void producer_task(void*) {
    std::uint32_t count = 0;
    while (count < kFirmwareCaseLimit && !stop_requested.load(std::memory_order_acquire)) {
        const CampaignSeed* selected = campaign_scheduler.select();
        if (selected == nullptr) break;
        const CorpusEntry parent = selected->corpus;
        SeedSet one_seed{};
        one_seed.count = 1;
        one_seed.entries[0] = parent;
        WorkItem item{};
        if (!mutator.next(one_seed, item.frame, item.case_id, item.tag, item.mutation)) break;
        while (!work_queue.push(item) && !stop_requested.load(std::memory_order_acquire)) taskYIELD();
        if (stop_requested.load(std::memory_order_acquire)) break;

        // Strict producer/consumer feedback handshake: no next mutation is
        // generated until the preceding target response and coverage arrive.
        FeedbackItem feedback{};
        bool feedback_received = false;
        while (!feedback_received && !stop_requested.load(std::memory_order_acquire))
            feedback_received = feedback_queue.pop(feedback);
        if (!feedback_received || feedback.case_id != item.case_id) break;
        CorpusEntry candidate = parent;
        candidate.frame = item.frame;
        const CampaignObservation observation = campaign_scheduler.observe(
            candidate, feedback.coverage, feedback.outcome, item.case_id, false);
        Serial.printf("CAMPAIGN case=%lu corpus=%u novel_edges=%u new_outcome=%u admitted=%u target_cov=%u\n",
                      static_cast<unsigned long>(item.case_id),
                      static_cast<unsigned>(campaign_scheduler.seed_count()),
                      static_cast<unsigned>(observation.novel_edges),
                      observation.new_outcome ? 1U : 0U,
                      observation.new_seed ? 1U : 0U,
                      feedback.target_instrumentation_seen ? 1U : 0U);
        ++count;
        generated.store(count, std::memory_order_release);
    }
    producer_done.store(true, std::memory_order_release);
    vTaskDelete(nullptr);
}

void consumer_task(void*) {
    WorkItem item{};
    while (!producer_done.load(std::memory_order_acquire) || !work_queue.empty()) {
        if (work_queue.pop(item)) {
#if NEXUS_TARGET_COV_SYNC_ENABLED
            // Do not dispatch an input until the target confirms that its
            // per-case coverage epoch is synchronized to this exact case ID.
            if (!begin_target_coverage_case(item.case_id)) {
                Serial.printf("TARGET_COV_SYNC_FAILED case=%lu; campaign stopped before bus dispatch\n",
                              static_cast<unsigned long>(item.case_id));
                stop_requested.store(true, std::memory_order_release);
                continue;
            }
#endif
            const CaseResult r = engine_ptr->execute(item.frame, item.case_id, item.tag, item.mutation);
            FeedbackItem feedback{};
            feedback.case_id = r.case_id;
            feedback.outcome = r.response_kind;
            feedback.coverage = transition_feedback(r.state_before, r.state_after, r.response_kind);
            feedback.target_instrumentation_seen = collect_target_coverage(r.case_id, feedback.coverage);

            Serial.printf("NEXUS case=%lu tag=%04X state=%u>%u kind=%u us=%lu timing_candidate=%u\n",
                          static_cast<unsigned long>(r.case_id), static_cast<unsigned>(r.command_tag),
                          static_cast<unsigned>(r.state_before), static_cast<unsigned>(r.state_after),
                          static_cast<unsigned>(r.response_kind),
                          static_cast<unsigned long>(r.latency_us), r.timing_anomaly_candidate ? 1U : 0U);
            if (r.response_kind == ResponseKind::Timeout || r.response_kind == ResponseKind::BusError ||
                r.response_kind == ResponseKind::OversizedResponse) {
                Serial.printf("HEALTH case=%lu health=%u streak=%u checked=%u crash_suspected=%u\n",
                              static_cast<unsigned long>(r.case_id), static_cast<unsigned>(r.target_health),
                              static_cast<unsigned>(r.failure_streak), r.liveness_checked ? 1U : 0U,
                              r.crash_suspected ? 1U : 0U);
            }
            if (r.crash_suspected) {
                const auto& records = engine_ptr->crash_records();
                for (const auto& record : records) {
                    if (!record.used || record.case_id != r.case_id) continue;
                    Serial.printf("CRASH_SUSPECTED,case=%lu,tag=%04X,latency_us=%lu,failed_heartbeats=%u,trigger=",
                                  static_cast<unsigned long>(record.case_id),
                                  static_cast<unsigned>(record.command_tag),
                                  static_cast<unsigned long>(record.latency_us),
                                  static_cast<unsigned>(record.failed_heartbeats));
                    for (std::uint16_t i = 0; i < record.trigger.size; ++i)
                        Serial.printf("%02X", static_cast<unsigned>(record.trigger.bytes[i]));
                    Serial.println();
                    Serial.println("DIAG_REQUIRED: capture target panic/debug UART, reset cause, exact target ELF and map file.");
                    break;
                }
            }
            if (engine_ptr->halted()) stop_requested.store(true, std::memory_order_release);
            while (!feedback_queue.push(feedback)) taskYIELD();
        } else {
            taskYIELD();
        }
    }
    run_done.store(true, std::memory_order_release);
    vTaskDelete(nullptr);
}

} // namespace

void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println("NEXUS-HW ESP32-S3 | v0.7.0 | coverage-guided lab campaign");
#if NEXUS_TARGET_DIAG_UART_ENABLED
    Serial2.begin(NEXUS_TARGET_DIAG_BAUD, SERIAL_8N1, NEXUS_TARGET_DIAG_RX_PIN, NEXUS_TARGET_DIAG_TX_PIN);
    Serial.printf("TARGET_DIAG_UART enabled rx_gpio=%d tx_gpio=%d baud=%lu\n",
                  NEXUS_TARGET_DIAG_RX_PIN, NEXUS_TARGET_DIAG_TX_PIN,
                  static_cast<unsigned long>(NEXUS_TARGET_DIAG_BAUD));
#endif
    if (!NEXUS_AUTHORIZED_LAB_TARGET || !NEXUS_ACTIVE_FUZZ_ENABLED) {
        Serial.println("DISARMED: set both authorization build flags only for an isolated lab fixture.");
        return;
    }

    corpus = nexus::example::make_lab_corpus();
    profile = nexus::example::make_lab_profile();
    if (!campaign_scheduler.initialize(corpus)) {
        Serial.println("ERROR: initial campaign corpus is invalid");
        return;
    }
    campaign_scheduler.set_seed(0x4E455855U);
    cfg.authorized_lab_target = true;
    cfg.active_fuzz_enabled = true;
    cfg.max_cases = kFirmwareCaseLimit;
    cfg.timeout_us = 20000;
    cfg.minimum_interval_us = 100000; // hard cap: 10 target transactions per second
    cfg.calibration_rounds = 4;
    cfg.anomaly_sigma = 4.0F;
    cfg.liveness.enabled = true;
    cfg.liveness.request = corpus.entries[0].frame; // documented read-only status request in this lab profile
    cfg.liveness.expected_response = profile.ack;
    cfg.liveness.retries = 2;
    cfg.liveness.retry_delay_us = 20000;

#if NEXUS_ENABLE_SAFE_OPCODE_SURVEY
    // This optional physical-link survey is restricted to read-only command
    // frames supplied in the operator-reviewed corpus. It does NOT sweep
    // unknown opcodes or attempt service-mode/backdoor unlock sequences.
    SafeOpcodeManifest safe_manifest{};
    safe_manifest.count = corpus.count;
    for (std::uint8_t i = 0; i < corpus.count; ++i) {
        safe_manifest.candidates[i].request = corpus.entries[i].frame;
        safe_manifest.candidates[i].command_tag = corpus.entries[i].command_tag;
        safe_manifest.candidates[i].documented_read_only = true;
    }
    OpcodeSurveyConfig survey_cfg{};
    survey_cfg.authorized_lab_target = true;
    survey_cfg.active_probe_enabled = true;
    survey_cfg.max_probes = safe_manifest.count;
    survey_cfg.timeout_us = cfg.timeout_us;
    survey_cfg.minimum_interval_us = cfg.minimum_interval_us;
    OpcodeSurveyReport survey_report{};
    if (!SafeOpcodeSurvey::run(transport, clock_source, safe_manifest, survey_cfg,
                               profile, survey_report)) {
        Serial.println("SAFE_OPCODE_SURVEY rejected/failed; verify manifest and target fixture.");
        return;
    }
    for (std::uint8_t i = 0; i < survey_report.count; ++i) {
        const auto& obs = survey_report.observations[i];
        Serial.printf("SAFE_OPCODE,tag=%04X,opcode=%02X,disposition=%u,latency_us=%lu,fp=%08lX\n",
                      static_cast<unsigned>(obs.command_tag), static_cast<unsigned>(obs.opcode),
                      static_cast<unsigned>(obs.disposition),
                      static_cast<unsigned long>(obs.latency_us),
                      static_cast<unsigned long>(obs.response_fingerprint));
    }
#endif

    static Engine engine(transport, clock_source, cfg, profile);
    engine_ptr = &engine;
    if (!engine.begin()) {
        Serial.println("ERROR: transport initialization failed");
        return;
    }
    if (!engine.calibrate(corpus)) {
        Serial.println("ERROR: calibration failed");
        engine.end();
        return;
    }
    Serial.printf("Calibration complete; link=%u. Starting bounded run (%lu cases).\n",
                  static_cast<unsigned>(transport.kind()), static_cast<unsigned long>(kFirmwareCaseLimit));

    // Start the consumer first so the bounded queue cannot fill before a reader exists.
    const TaskHandle_t consumer_handle = xTaskCreateStaticPinnedToCore(
        consumer_task, "nexus-io", 6144, nullptr, 3,
        consumer_stack, &consumer_tcb, 0);
    if (consumer_handle == nullptr) {
        Serial.println("ERROR: could not create static I/O task");
        engine.end();
        return;
    }
    const TaskHandle_t producer_handle = xTaskCreateStaticPinnedToCore(
        producer_task, "nexus-mutator", 4096, nullptr, 2,
        producer_stack, &producer_tcb, 1);
    if (producer_handle == nullptr) {
        Serial.println("ERROR: could not create static mutation task");
        producer_done.store(true, std::memory_order_release);
        return;
    }
}

void loop() {
    if (run_done.load(std::memory_order_acquire) && engine_ptr != nullptr) {
        // The consumer task owns Serial2 during the campaign; after it exits,
        // the main loop keeps draining late panic/reset diagnostics.
        pump_target_diagnostics();
        Serial.printf("DONE cases=%lu states=%u edges=%u halted=%u\n",
                      static_cast<unsigned long>(engine_ptr->executed_cases()),
                      static_cast<unsigned>(engine_ptr->graph().state_count()),
                      static_cast<unsigned>(engine_ptr->graph().edge_count()),
                      engine_ptr->halted() ? 1U : 0U);
        Serial.printf("CAMPAIGN_SUMMARY executions=%lu admissions=%lu novel_edges=%lu corpus=%u dropped=%lu\n",
                      static_cast<unsigned long>(campaign_scheduler.total_executions()),
                      static_cast<unsigned long>(campaign_scheduler.total_admissions()),
                      static_cast<unsigned long>(campaign_scheduler.total_novel_edges()),
                      static_cast<unsigned>(campaign_scheduler.seed_count()),
                      static_cast<unsigned long>(campaign_scheduler.dropped_candidates()));
        const auto& graph = engine_ptr->graph();
        for (std::uint16_t i = 0; i < kMaxStates; ++i) {
            const auto& state = graph.states()[i];
            if (state.used) {
                Serial.printf("STATE,%u,0x%08lX,%u,%lu\n", static_cast<unsigned>(i),
                              static_cast<unsigned long>(state.fingerprint),
                              static_cast<unsigned>(state.kind),
                              static_cast<unsigned long>(state.visits));
            }
        }
        for (std::uint16_t i = 0; i < kMaxEdges; ++i) {
            const auto& edge = graph.edges()[i];
            if (edge.used) {
                Serial.printf("EDGE,%u,%u,%u,%u,%lu\n", static_cast<unsigned>(edge.from),
                              static_cast<unsigned>(edge.to), static_cast<unsigned>(edge.command_tag),
                              static_cast<unsigned>(edge.outcome),
                              static_cast<unsigned long>(edge.traversals));
            }
        }
        for (std::uint8_t k = 0; k < 6; ++k) {
            const auto kind = static_cast<ResponseKind>(k);
            const auto& stats = engine_ptr->timing().stats(kind);
            if (stats.count > 0) {
                Serial.printf("TIMING,%u,%lu,%lu,%lu,%lu\n", static_cast<unsigned>(k),
                              static_cast<unsigned long>(stats.count),
                              static_cast<unsigned long>(stats.mean + 0.5),
                              static_cast<unsigned long>(stats.min_us),
                              static_cast<unsigned long>(stats.max_us));
            }
        }
        for (std::uint8_t i = 0; i < kMaxCrashRecords; ++i) {
            const auto& crash = engine_ptr->crash_records()[i];
            if (crash.used) {
                Serial.printf("CRASH_SUSPECTED,case=%lu,tag=%04X,latency_us=%lu,failed_heartbeats=%u,trigger=",
                              static_cast<unsigned long>(crash.case_id),
                              static_cast<unsigned>(crash.command_tag),
                              static_cast<unsigned long>(crash.latency_us),
                              static_cast<unsigned>(crash.failed_heartbeats));
                for (std::uint16_t b = 0; b < crash.trigger.size; ++b)
                    Serial.printf("%02X", static_cast<unsigned>(crash.trigger.bytes[b]));
                Serial.println();
            }
        }
        Serial.printf("HEALTH_SUMMARY,health=%u,crash_suspicions=%lu,link_faults=%lu\n",
                      static_cast<unsigned>(engine_ptr->target_health()),
                      static_cast<unsigned long>(engine_ptr->crash_suspicions()),
                      static_cast<unsigned long>(engine_ptr->link_faults()));
        engine_ptr->end();
        run_done.store(false, std::memory_order_release);
        Serial.println("Run stopped. Reset board to run again; target diagnostics remain active.");
        while (true) {
            pump_target_diagnostics();
            delay(10);
        }
    }
    delay(20);
}
#endif
