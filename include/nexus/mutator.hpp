#pragma once

#include "nexus/types.hpp"
#include "nexus/checksum.hpp"

namespace nexus {

class XorShift32 {
public:
    explicit XorShift32(std::uint32_t seed = 0x9E3779B9U) noexcept
        : state_(seed == 0 ? 0xA341316CU : seed) {}

    [[nodiscard]] std::uint32_t next() noexcept {
        std::uint32_t x = state_;
        x ^= x << 13U;
        x ^= x >> 17U;
        x ^= x << 5U;
        state_ = x;
        return x;
    }

private:
    std::uint32_t state_;
};

class Mutator {
public:
    explicit Mutator(std::uint32_t seed = 0xC001D00DU) noexcept : rng_(seed) {}

    // Mutates only the payload of a caller-supplied, allowlisted corpus frame.
    // The command prefix and frame length remain unchanged.
    [[nodiscard]] bool next(const SeedSet& corpus, Frame& out,
                            std::uint32_t& case_id, std::uint16_t& command_tag,
                            MutationKind& mutation_kind) noexcept {
        if (corpus.count == 0 || corpus.count > kMaxCorpusEntries) return false;
        const std::uint8_t index = static_cast<std::uint8_t>(rng_.next() % corpus.count);
        const CorpusEntry& entry = corpus.entries[index];
        if (!entry.frame.valid() || entry.immutable_prefix >= entry.frame.size) return false;
        const std::uint16_t mutable_start = entry.immutable_prefix;
        const std::uint16_t checksum_width_bytes = entry.checksum.enabled
            ? checksum_width(entry.checksum.algorithm) : 0U;
        const std::uint16_t checksum_start = entry.checksum.checksum_offset;
        const std::uint16_t checksum_end = static_cast<std::uint16_t>(checksum_start + checksum_width_bytes);
        if (entry.checksum.enabled && (checksum_width_bytes == 0U || checksum_start < mutable_start ||
                                        checksum_end > entry.frame.size)) return false;
        const bool checksum_in_mutable = entry.checksum.enabled && checksum_start < entry.frame.size;
        const std::uint16_t before_checksum = checksum_in_mutable
            ? static_cast<std::uint16_t>(checksum_start - mutable_start)
            : static_cast<std::uint16_t>(entry.frame.size - mutable_start);
        const std::uint16_t after_checksum = checksum_in_mutable
            ? static_cast<std::uint16_t>(entry.frame.size - checksum_end) : 0U;
        const std::uint16_t mutable_len = static_cast<std::uint16_t>(before_checksum + after_checksum);
        if (mutable_len < entry.minimum_mutable_bytes || mutable_len == 0U) return false;

        out = entry.frame;
        const std::uint16_t slot = static_cast<std::uint16_t>(rng_.next() % mutable_len);
        const std::uint16_t offset = checksum_in_mutable && slot >= before_checksum
            ? static_cast<std::uint16_t>(checksum_end + (slot - before_checksum))
            : static_cast<std::uint16_t>(mutable_start + slot);
        const std::uint8_t selector = static_cast<std::uint8_t>(rng_.next() & 3U);
        switch (selector) {
            case 0: {
                out.bytes[offset] ^= static_cast<std::uint8_t>(1U << (rng_.next() & 7U));
                mutation_kind = MutationKind::BitFlip;
                break;
            }
            case 1: {
                const auto delta = static_cast<std::int8_t>((rng_.next() & 1U) ? 1 : -1);
                out.bytes[offset] = static_cast<std::uint8_t>(out.bytes[offset] + delta);
                mutation_kind = MutationKind::Arithmetic;
                break;
            }
            case 2: {
                constexpr std::uint8_t interesting[] = {
                    0x00, 0x01, 0x7F, 0x80, 0xAA, 0x55, 0x7E, 0x81,
                    0xFE, 0xFF, 0x10, 0x20, 0x40, 0xEE, 0xF0
                };
                out.bytes[offset] = interesting[rng_.next() % (sizeof(interesting) / sizeof(interesting[0]))];
                mutation_kind = MutationKind::InterestingByte;
                break;
            }
            default: {
                // Bounded 1-4 byte payload fill; never touches immutable prefix.
                const std::uint16_t remaining = static_cast<std::uint16_t>(out.size - offset);
                const std::uint16_t count = static_cast<std::uint16_t>(1U + (rng_.next() % 4U));
                const std::uint16_t bounded = count < remaining ? count : remaining;
                const std::uint8_t value = static_cast<std::uint8_t>(rng_.next());
                for (std::uint16_t i = 0; i < bounded; ++i) out.bytes[offset + i] = value;
                mutation_kind = MutationKind::BlockFill;
                break;
            }
        }
        if (entry.checksum.enabled && !apply_checksum(out, entry.checksum)) return false;
        case_id = ++case_counter_;
        command_tag = entry.command_tag;
        return true;
    }

private:
    XorShift32 rng_;
    std::uint32_t case_counter_{0};
};

} // namespace nexus
