#pragma once

#include "nexus/types.hpp"

#include <cstddef>
#include <cstdint>

namespace nexus {

[[nodiscard]] constexpr std::uint8_t checksum_width(ChecksumAlgorithm algorithm) noexcept {
    switch (algorithm) {
        case ChecksumAlgorithm::Xor8:
        case ChecksumAlgorithm::Sum8:
        case ChecksumAlgorithm::Crc8Maxim:
        case ChecksumAlgorithm::Crc8Custom: return 1;
        case ChecksumAlgorithm::Crc16CcittFalse:
        case ChecksumAlgorithm::Crc16Modbus:
        case ChecksumAlgorithm::Crc16Custom: return 2;
        case ChecksumAlgorithm::Crc32Ieee:
        case ChecksumAlgorithm::Crc32Custom: return 4;
        case ChecksumAlgorithm::None: return 0;
    }
    return 0;
}

[[nodiscard]] inline std::uint32_t checksum_compute(const std::uint8_t* data,
                                                     std::size_t length,
                                                     ChecksumAlgorithm algorithm) noexcept {
    if (data == nullptr && length != 0) return 0;
    switch (algorithm) {
        case ChecksumAlgorithm::None:
        case ChecksumAlgorithm::Crc8Custom:
        case ChecksumAlgorithm::Crc16Custom:
        case ChecksumAlgorithm::Crc32Custom:
            return 0; // Custom CRC variants require the full ChecksumSpec overload.
        case ChecksumAlgorithm::Xor8: {
            std::uint8_t value = 0;
            for (std::size_t i = 0; i < length; ++i) value ^= data[i];
            return value;
        }
        case ChecksumAlgorithm::Sum8: {
            std::uint8_t value = 0;
            for (std::size_t i = 0; i < length; ++i)
                value = static_cast<std::uint8_t>(value + data[i]);
            return value;
        }
        case ChecksumAlgorithm::Crc8Maxim: {
            std::uint8_t crc = 0;
            for (std::size_t i = 0; i < length; ++i) {
                crc ^= data[i];
                for (std::uint8_t bit = 0; bit < 8; ++bit)
                    crc = (crc & 1U) != 0U
                        ? static_cast<std::uint8_t>((crc >> 1U) ^ 0x8CU)
                        : static_cast<std::uint8_t>(crc >> 1U);
            }
            return crc;
        }
        case ChecksumAlgorithm::Crc16CcittFalse: {
            std::uint16_t crc = 0xFFFFU;
            for (std::size_t i = 0; i < length; ++i) {
                crc ^= static_cast<std::uint16_t>(static_cast<std::uint16_t>(data[i]) << 8U);
                for (std::uint8_t bit = 0; bit < 8; ++bit)
                    crc = (crc & 0x8000U) != 0U
                        ? static_cast<std::uint16_t>((crc << 1U) ^ 0x1021U)
                        : static_cast<std::uint16_t>(crc << 1U);
            }
            return crc;
        }
        case ChecksumAlgorithm::Crc16Modbus: {
            std::uint16_t crc = 0xFFFFU;
            for (std::size_t i = 0; i < length; ++i) {
                crc ^= data[i];
                for (std::uint8_t bit = 0; bit < 8; ++bit)
                    crc = (crc & 1U) != 0U
                        ? static_cast<std::uint16_t>((crc >> 1U) ^ 0xA001U)
                        : static_cast<std::uint16_t>(crc >> 1U);
            }
            return crc;
        }
        case ChecksumAlgorithm::Crc32Ieee: {
            std::uint32_t crc = 0xFFFFFFFFU;
            for (std::size_t i = 0; i < length; ++i) {
                crc ^= data[i];
                for (std::uint8_t bit = 0; bit < 8; ++bit)
                    crc = (crc & 1U) != 0UL ? (crc >> 1U) ^ 0xEDB88320U : crc >> 1U;
            }
            return crc ^ 0xFFFFFFFFU;
        }
    }
    return 0;
}

[[nodiscard]] constexpr std::uint32_t reflect_bits(std::uint32_t value, std::uint8_t width) noexcept {
    std::uint32_t result = 0;
    for (std::uint8_t i = 0; i < width; ++i) {
        result = static_cast<std::uint32_t>((result << 1U) | (value & 1U));
        value >>= 1U;
    }
    return result;
}

[[nodiscard]] inline std::uint32_t checksum_compute_custom(const std::uint8_t* data,
                                                            std::size_t length,
                                                            const ChecksumSpec& spec) noexcept {
    const std::uint8_t width = checksum_width(spec.algorithm) == 1 ? 8U :
                               checksum_width(spec.algorithm) == 2 ? 16U : 32U;
    const std::uint32_t mask = width == 32U ? 0xFFFFFFFFU : ((1U << width) - 1U);
    const std::uint32_t top = 1U << (width - 1U);
    const std::uint32_t poly = spec.reflect_input ? reflect_bits(spec.polynomial, width) : spec.polynomial;
    std::uint32_t crc = spec.initial & mask;
    for (std::size_t i = 0; i < length; ++i) {
        if (spec.reflect_input) {
            crc ^= data[i];
            for (std::uint8_t bit = 0; bit < 8U; ++bit)
                crc = (crc & 1U) != 0UL ? (crc >> 1U) ^ poly : crc >> 1U;
        } else {
            crc ^= static_cast<std::uint32_t>(data[i]) << (width - 8U);
            for (std::uint8_t bit = 0; bit < 8U; ++bit)
                crc = (crc & top) != 0UL ? ((crc << 1U) ^ spec.polynomial) & mask : (crc << 1U) & mask;
        }
    }
    if (spec.reflect_input != spec.reflect_output) crc = reflect_bits(crc, width);
    return (crc ^ spec.xor_out) & mask;
}

[[nodiscard]] inline std::uint32_t checksum_compute(const std::uint8_t* data,
                                                     std::size_t length,
                                                     const ChecksumSpec& spec) noexcept {
    if (spec.algorithm == ChecksumAlgorithm::Crc8Custom ||
        spec.algorithm == ChecksumAlgorithm::Crc16Custom ||
        spec.algorithm == ChecksumAlgorithm::Crc32Custom) {
        if (spec.polynomial == 0U) return 0U;
        return checksum_compute_custom(data, length, spec);
    }
    return checksum_compute(data, length, spec.algorithm);
}

[[nodiscard]] inline bool checksum_spec_valid(const Frame& frame,
                                               const ChecksumSpec& spec) noexcept {
    if (!spec.enabled) return true;
    const std::uint8_t width = checksum_width(spec.algorithm);
    if (!frame.valid() || width == 0 || spec.data_length == 0) return false;
    if (spec.algorithm == ChecksumAlgorithm::Crc8Custom ||
        spec.algorithm == ChecksumAlgorithm::Crc16Custom ||
        spec.algorithm == ChecksumAlgorithm::Crc32Custom) {
        const std::uint8_t bits = static_cast<std::uint8_t>(width * 8U);
        const std::uint32_t mask = bits == 32U ? 0xFFFFFFFFU : ((1U << bits) - 1U);
        if (spec.polynomial == 0U || spec.polynomial > mask ||
            spec.initial > mask || spec.xor_out > mask) return false;
    }
    const std::uint32_t data_end = static_cast<std::uint32_t>(spec.data_offset) + spec.data_length;
    const std::uint32_t checksum_end = static_cast<std::uint32_t>(spec.checksum_offset) + width;
    if (data_end > frame.size || checksum_end > frame.size) return false;
    // The checksum field must not be part of the bytes over which it is calculated.
    const bool disjoint = data_end <= spec.checksum_offset || checksum_end <= spec.data_offset;
    return disjoint;
}

[[nodiscard]] inline bool apply_checksum(Frame& frame, const ChecksumSpec& spec) noexcept {
    if (!spec.enabled) return frame.valid();
    if (!checksum_spec_valid(frame, spec)) return false;
    const std::uint32_t value = checksum_compute(
        frame.bytes.data() + spec.data_offset, spec.data_length, spec);
    const std::uint8_t width = checksum_width(spec.algorithm);
    for (std::uint8_t i = 0; i < width; ++i) {
        const std::uint8_t shift_index = spec.big_endian
            ? static_cast<std::uint8_t>(width - 1U - i) : i;
        const auto shift = static_cast<std::uint8_t>(shift_index * 8U);
        frame.bytes[static_cast<std::uint16_t>(spec.checksum_offset + i)] =
            static_cast<std::uint8_t>((value >> shift) & 0xFFU);
    }
    return true;
}

[[nodiscard]] inline bool verify_checksum(const Frame& frame,
                                          const ChecksumSpec& spec) noexcept {
    if (!spec.enabled) return frame.valid();
    if (!checksum_spec_valid(frame, spec)) return false;
    Frame expected = frame;
    if (!apply_checksum(expected, spec)) return false;
    const std::uint8_t width = checksum_width(spec.algorithm);
    for (std::uint8_t i = 0; i < width; ++i) {
        const auto offset = static_cast<std::uint16_t>(spec.checksum_offset + i);
        if (frame.bytes[offset] != expected.bytes[offset]) return false;
    }
    return true;
}

} // namespace nexus
