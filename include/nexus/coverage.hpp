#pragma once

#include <array>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <cstdio>

namespace nexus {

// Fixed-size edge bitmap for firmware that is built specifically for testing.
// Insert NEXUS_COV_HIT(edge_id) at basic-block/branch boundaries in code you own
// or are authorized to instrument. This does not infer arbitrary binary coverage.
template <std::size_t Bits = 1024>
class CoverageBitmap {
    static_assert(Bits >= 32 && Bits <= 8192, "coverage bitmap size must be 32..8192 bits");
    static constexpr std::size_t kWords = (Bits + 31U) / 32U;
public:
    CoverageBitmap() noexcept { reset(); }

    void reset() noexcept {
        for (auto& word : words_) word.store(0U, std::memory_order_relaxed);
        hits_.store(0U, std::memory_order_relaxed);
    }

    [[nodiscard]] bool hit(std::uint32_t edge_id) noexcept {
        if (edge_id >= Bits) return false;
        const std::size_t word_index = edge_id / 32U;
        const std::uint32_t mask = 1UL << (edge_id % 32U);
        const std::uint32_t previous = words_[word_index].fetch_or(mask, std::memory_order_relaxed);
        const bool is_new = (previous & mask) == 0U;
        if (is_new) hits_.fetch_add(1U, std::memory_order_relaxed);
        return is_new;
    }

    [[nodiscard]] std::uint32_t unique_edges() const noexcept {
        return hits_.load(std::memory_order_relaxed);
    }

    [[nodiscard]] static constexpr std::size_t capacity_bits() noexcept { return Bits; }

    // Emits: NXCOV1,run=<id>,bits=<Bits>,bitmap=<fixed-width hex>
    [[nodiscard]] bool format_record(char* output, std::size_t capacity,
                                     std::uint32_t run_id) const noexcept {
        if (output == nullptr || capacity == 0) return false;
        const int prefix = std::snprintf(output, capacity,
            "NXCOV1,run=%lu,bits=%lu,bitmap=",
            static_cast<unsigned long>(run_id), static_cast<unsigned long>(Bits));
        if (prefix < 0) return false;
        const std::size_t prefix_size = static_cast<std::size_t>(prefix);
        constexpr char hex[] = "0123456789ABCDEF";
        const std::size_t required = prefix_size + kWords * 8U + 1U;
        if (required > capacity) return false;
        std::size_t cursor = prefix_size;
        for (std::size_t w = 0; w < kWords; ++w) {
            const std::uint32_t value = words_[w].load(std::memory_order_relaxed);
            for (int nibble = 7; nibble >= 0; --nibble) {
                output[cursor++] = hex[(value >> (static_cast<unsigned>(nibble) * 4U)) & 0x0FU];
            }
        }
        output[cursor] = '\0';
        return true;
    }

private:
    std::array<std::atomic<std::uint32_t>, kWords> words_{};
    std::atomic<std::uint32_t> hits_{0};
};

inline CoverageBitmap<2048> g_nexus_coverage{};

} // namespace nexus

#define NEXUS_COV_HIT(edge_id) \
    ((void)::nexus::g_nexus_coverage.hit(static_cast<std::uint32_t>(edge_id)))
