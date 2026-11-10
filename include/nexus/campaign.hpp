#pragma once

#include "nexus/mutator.hpp"

#include <array>
#include <cstdint>
#include <limits>
#include <string_view>

namespace nexus {

inline constexpr std::size_t kCampaignTargetMapBits = 2048;
inline constexpr std::size_t kCampaignTargetMapWords = kCampaignTargetMapBits / 32U;
inline constexpr std::size_t kCampaignTransitionBase = kCampaignTargetMapBits;
inline constexpr std::size_t kCampaignMapBits = kCampaignTargetMapBits + (kMaxStates * kMaxStates);
inline constexpr std::size_t kCampaignMapWords = (kCampaignMapBits + 31U) / 32U;
inline constexpr std::size_t kMaxCampaignSeeds = kMaxCorpusEntries;
inline constexpr std::size_t kMaxOutcomeKeys = 64;

enum class NoveltyKind : std::uint8_t { None, NewOutcome, NewCoverage, NewCoverageAndOutcome, Crash };

struct FeedbackSnapshot {
    std::array<std::uint32_t, kCampaignMapWords> words{};
    std::uint16_t count{0};

    [[nodiscard]] bool add(std::uint32_t edge_id) noexcept {
        if (edge_id >= kCampaignMapBits) return false;
        const std::size_t word = edge_id / 32U;
        const std::uint32_t mask = 1UL << (edge_id % 32U);
        const bool fresh = (words[word] & mask) == 0U;
        words[word] |= mask;
        if (fresh && count != UINT16_MAX) ++count;
        return fresh;
    }

    [[nodiscard]] bool contains(std::uint32_t edge_id) const noexcept {
        if (edge_id >= kCampaignMapBits) return false;
        return (words[edge_id / 32U] & (1UL << (edge_id % 32U))) != 0U;
    }
};

// Protocol-transition feedback is distinct from target binary coverage. It
// guides black/grey-box campaigns when the target cannot expose instrumentation.
[[nodiscard]] inline FeedbackSnapshot transition_feedback(std::uint16_t before,
                                                            std::uint16_t after,
                                                            ResponseKind outcome) noexcept {
    FeedbackSnapshot snapshot{};
    if (before < kMaxStates && after < kMaxStates) {
        (void)snapshot.add(static_cast<std::uint32_t>(kCampaignTransitionBase) +
                           static_cast<std::uint32_t>(before) * kMaxStates + after);
    }
    (void)outcome; // outcome novelty is tracked by the scheduler's independent response key table.
    return snapshot;
}

[[nodiscard]] inline bool parse_nxcov_record(std::string_view line,
                                              std::uint32_t expected_run,
                                              FeedbackSnapshot& output) noexcept {
    constexpr std::string_view prefix = "NXCOV1,run=";
    constexpr std::string_view bits_key = ",bits=";
    constexpr std::string_view bitmap_key = ",bitmap=";
    if (!line.starts_with(prefix)) return false;
    const std::size_t bits_pos = line.find(bits_key, prefix.size());
    if (bits_pos == std::string_view::npos) return false;
    const auto run_value = line.substr(prefix.size(), bits_pos - prefix.size());
    const std::size_t bitmap_pos = line.find(bitmap_key, bits_pos + bits_key.size());
    if (bitmap_pos == std::string_view::npos) return false;
    const auto bits_value = line.substr(bits_pos + bits_key.size(),
                                        bitmap_pos - (bits_pos + bits_key.size()));
    auto parse_decimal = [](std::string_view value, std::uint32_t& result) noexcept {
        if (value.empty()) return false;
        std::uint32_t parsed = 0;
        for (const char ch : value) {
            if (ch < '0' || ch > '9') return false;
            const std::uint32_t digit = static_cast<std::uint32_t>(ch - '0');
            if (parsed > (UINT32_MAX - digit) / 10U) return false;
            parsed = parsed * 10U + digit;
        }
        result = parsed;
        return true;
    };
    std::uint32_t run_id = 0;
    std::uint32_t bit_count = 0;
    if (!parse_decimal(run_value, run_id) || !parse_decimal(bits_value, bit_count) ||
        run_id != expected_run || bit_count != kCampaignTargetMapBits) return false;
    const auto bitmap = line.substr(bitmap_pos + bitmap_key.size());
    if (bitmap.size() != kCampaignTargetMapWords * 8U) return false;
    auto hex_value = [](char ch) noexcept -> int {
        if (ch >= '0' && ch <= '9') return ch - '0';
        if (ch >= 'a' && ch <= 'f') return 10 + ch - 'a';
        if (ch >= 'A' && ch <= 'F') return 10 + ch - 'A';
        return -1;
    };
    FeedbackSnapshot parsed{};
    for (std::size_t word_index = 0; word_index < kCampaignTargetMapWords; ++word_index) {
        std::uint32_t word = 0;
        for (std::size_t nibble = 0; nibble < 8U; ++nibble) {
            const int value = hex_value(bitmap[word_index * 8U + nibble]);
            if (value < 0) return false;
            word = (word << 4U) | static_cast<std::uint32_t>(value);
        }
        for (std::uint32_t bit = 0; bit < 32U; ++bit) {
            if ((word & (1UL << bit)) != 0U)
                (void)parsed.add(static_cast<std::uint32_t>(word_index * 32U + bit));
        }
    }
    output = parsed;
    return true;
}

inline void merge_feedback(FeedbackSnapshot& destination,
                           const FeedbackSnapshot& source) noexcept {
    for (std::uint32_t edge = 0; edge < kCampaignMapBits; ++edge) {
        if (source.contains(edge)) (void)destination.add(edge);
    }
}

struct CampaignSeed {
    CorpusEntry corpus{};
    std::uint32_t executions{0};
    std::uint32_t discoveries{0};
    std::uint32_t last_discovery_case{0};
    std::uint16_t energy{1};
    bool favored{false};
    bool used{false};
};

struct CampaignObservation {
    bool admitted{false};
    bool new_coverage{false};
    bool new_outcome{false};
    bool new_seed{false};
    std::uint16_t novel_edges{0};
    NoveltyKind novelty{NoveltyKind::None};
};

// Fixed-memory, coverage-guided corpus scheduler. It is suitable for embedded
// targets: no heap, no filesystem, deterministic seed selection, bounded work.
class CoverageGuidedScheduler {
public:
    [[nodiscard]] bool initialize(const SeedSet& initial) noexcept {
        reset();
        if (initial.count == 0U || initial.count > kMaxCorpusEntries) return false;
        for (std::uint8_t i = 0; i < initial.count; ++i) {
            const auto& entry = initial.entries[i];
            if (!entry.frame.valid() || entry.immutable_prefix >= entry.frame.size ||
                entry.minimum_mutable_bytes == 0U) {
                reset();
                return false;
            }
            seeds_[seed_count_].corpus = entry;
            seeds_[seed_count_].energy = 4U;
            seeds_[seed_count_].favored = true;
            seeds_[seed_count_].used = true;
            ++seed_count_;
        }
        return true;
    }

    void reset() noexcept {
        seeds_ = {};
        seen_edges_ = {};
        outcomes_ = {};
        seed_count_ = 0;
        outcome_count_ = 0;
        rng_state_ = 0x4E455855U;
        total_executions_ = 0;
        total_admissions_ = 0;
        total_novel_edges_ = 0;
        dropped_candidates_ = 0;
    }

    void set_seed(std::uint32_t seed) noexcept {
        rng_state_ = seed == 0U ? 0xA341316CU : seed;
    }

    [[nodiscard]] const CampaignSeed* select() noexcept {
        if (seed_count_ == 0U) return nullptr;
        std::uint32_t total_weight = 0;
        for (const auto& item : seeds_) {
            if (item.used) total_weight += item.energy;
        }
        if (total_weight == 0U) return nullptr;
        std::uint32_t ticket = next_random() % total_weight;
        for (auto& item : seeds_) {
            if (!item.used) continue;
            if (ticket < item.energy) {
                if (item.executions != UINT32_MAX) ++item.executions;
                if (total_executions_ != UINT32_MAX) ++total_executions_;
                // Mild deterministic power-schedule decay prevents one seed
                // from monopolizing the campaign while retaining discoveries.
                if (item.energy > 1U && (item.executions % 8U) == 0U) --item.energy;
                return &item;
            }
            ticket -= item.energy;
        }
        return nullptr;
    }

    [[nodiscard]] CampaignObservation observe(const CorpusEntry& candidate,
                                               const FeedbackSnapshot& feedback,
                                               ResponseKind outcome,
                                               std::uint32_t case_id,
                                               bool crash_confirmed = false) noexcept {
        CampaignObservation result{};
        if (!candidate.frame.valid() || candidate.immutable_prefix >= candidate.frame.size ||
            candidate.minimum_mutable_bytes == 0U) {
            return result;
        }

        for (std::size_t word = 0; word < kCampaignMapWords; ++word) {
            const std::uint32_t fresh = feedback.words[word] & ~seen_edges_[word];
            seen_edges_[word] |= feedback.words[word];
            std::uint32_t pending = fresh;
            while (pending != 0U) {
                pending &= pending - 1U;
                if (result.novel_edges != UINT16_MAX) ++result.novel_edges;
                if (total_novel_edges_ != UINT32_MAX) ++total_novel_edges_;
            }
        }
        result.new_coverage = result.novel_edges > 0U;
        result.new_outcome = observe_outcome(candidate.command_tag, outcome);
        if (crash_confirmed) result.novelty = NoveltyKind::Crash;
        else if (result.new_coverage && result.new_outcome) result.novelty = NoveltyKind::NewCoverageAndOutcome;
        else if (result.new_coverage) result.novelty = NoveltyKind::NewCoverage;
        else if (result.new_outcome) result.novelty = NoveltyKind::NewOutcome;
        else result.novelty = NoveltyKind::None;

        if (!result.new_coverage && !result.new_outcome && !crash_confirmed) return result;

        const int existing = find_exact(candidate);
        if (existing >= 0) {
            auto& item = seeds_[static_cast<std::size_t>(existing)];
            item.favored = item.favored || result.new_coverage;
            item.energy = saturating_energy(item.energy, score_delta(result, crash_confirmed));
            if (item.discoveries != UINT32_MAX) ++item.discoveries;
            item.last_discovery_case = case_id;
            result.admitted = true;
            result.new_seed = false;
            return result;
        }

        const int slot = choose_slot(score_delta(result, crash_confirmed));
        if (slot < 0) {
            if (dropped_candidates_ != UINT32_MAX) ++dropped_candidates_;
            return result;
        }
        CampaignSeed fresh{};
        fresh.corpus = candidate;
        fresh.energy = saturating_energy(1U, score_delta(result, crash_confirmed));
        fresh.discoveries = 1U;
        fresh.last_discovery_case = case_id;
        fresh.favored = result.novel_edges >= 2U || crash_confirmed;
        fresh.used = true;
        if (seeds_[static_cast<std::size_t>(slot)].used == false) ++seed_count_;
        seeds_[static_cast<std::size_t>(slot)] = fresh;
        if (total_admissions_ != UINT32_MAX) ++total_admissions_;
        result.admitted = true;
        result.new_seed = true;
        return result;
    }

    [[nodiscard]] SeedSet snapshot() const noexcept {
        SeedSet out{};
        for (const auto& item : seeds_) {
            if (item.used && out.count < kMaxCorpusEntries) {
                out.entries[out.count++] = item.corpus;
            }
        }
        return out;
    }

    [[nodiscard]] std::uint16_t seed_count() const noexcept { return seed_count_; }
    [[nodiscard]] std::uint32_t total_executions() const noexcept { return total_executions_; }
    [[nodiscard]] std::uint32_t total_admissions() const noexcept { return total_admissions_; }
    [[nodiscard]] std::uint32_t total_novel_edges() const noexcept { return total_novel_edges_; }
    [[nodiscard]] std::uint32_t dropped_candidates() const noexcept { return dropped_candidates_; }

    [[nodiscard]] bool edge_seen(std::uint32_t edge_id) const noexcept {
        if (edge_id >= kCampaignMapBits) return false;
        return (seen_edges_[edge_id / 32U] & (1UL << (edge_id % 32U))) != 0U;
    }

private:
    struct OutcomeKey {
        std::uint16_t command_tag{0};
        ResponseKind outcome{ResponseKind::Data};
        bool used{false};
    };

    [[nodiscard]] std::uint32_t next_random() noexcept {
        std::uint32_t x = rng_state_;
        x ^= x << 13U;
        x ^= x >> 17U;
        x ^= x << 5U;
        rng_state_ = x;
        return x;
    }

    [[nodiscard]] bool observe_outcome(std::uint16_t tag, ResponseKind kind) noexcept {
        for (const auto& key : outcomes_) {
            if (key.used && key.command_tag == tag && key.outcome == kind) return false;
        }
        for (auto& key : outcomes_) {
            if (!key.used) {
                key = OutcomeKey{tag, kind, true};
                ++outcome_count_;
                return true;
            }
        }
        return false;
    }

    [[nodiscard]] int find_exact(const CorpusEntry& candidate) const noexcept {
        for (std::size_t i = 0; i < seeds_.size(); ++i) {
            const auto& item = seeds_[i];
            if (!item.used || item.corpus.command_tag != candidate.command_tag ||
                item.corpus.frame.size != candidate.frame.size ||
                item.corpus.immutable_prefix != candidate.immutable_prefix) continue;
            bool equal = true;
            for (std::uint16_t j = 0; j < candidate.frame.size; ++j) {
                if (item.corpus.frame.bytes[j] != candidate.frame.bytes[j]) {
                    equal = false;
                    break;
                }
            }
            if (equal) return static_cast<int>(i);
        }
        return -1;
    }

    [[nodiscard]] static std::uint16_t score_delta(const CampaignObservation& result,
                                                    bool crash) noexcept {
        std::uint32_t score = 1U + static_cast<std::uint32_t>(result.novel_edges) * 12U;
        if (result.new_outcome) score += 6U;
        if (crash) score += 48U;
        return static_cast<std::uint16_t>(score > 128U ? 128U : score);
    }

    [[nodiscard]] static std::uint16_t saturating_energy(std::uint16_t current,
                                                         std::uint16_t delta) noexcept {
        const std::uint32_t sum = static_cast<std::uint32_t>(current) + delta;
        return static_cast<std::uint16_t>(sum > 256U ? 256U : sum);
    }

    [[nodiscard]] int choose_slot(std::uint16_t incoming_score) const noexcept {
        for (std::size_t i = 0; i < seeds_.size(); ++i) {
            if (!seeds_[i].used) return static_cast<int>(i);
        }
        std::size_t weakest = 0;
        for (std::size_t i = 1; i < seeds_.size(); ++i) {
            const auto lhs = seeds_[i].energy + (seeds_[i].favored ? 8U : 0U);
            const auto rhs = seeds_[weakest].energy + (seeds_[weakest].favored ? 8U : 0U);
            if (lhs < rhs) weakest = i;
        }
        const auto weakest_score = seeds_[weakest].energy + (seeds_[weakest].favored ? 8U : 0U);
        return incoming_score > weakest_score ? static_cast<int>(weakest) : -1;
    }

    std::array<CampaignSeed, kMaxCampaignSeeds> seeds_{};
    std::array<std::uint32_t, kCampaignMapWords> seen_edges_{};
    std::array<OutcomeKey, kMaxOutcomeKeys> outcomes_{};
    std::uint32_t rng_state_{0x4E455855U};
    std::uint32_t total_executions_{0};
    std::uint32_t total_admissions_{0};
    std::uint32_t total_novel_edges_{0};
    std::uint32_t dropped_candidates_{0};
    std::uint16_t seed_count_{0};
    std::uint16_t outcome_count_{0};
};

} // namespace nexus
