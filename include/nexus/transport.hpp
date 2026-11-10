#pragma once

#include "nexus/types.hpp"

namespace nexus {

class ITransport {
public:
    virtual ~ITransport() = default;
    virtual bool begin() noexcept = 0;
    virtual void end() noexcept = 0;
    // Implementations must never retain references to tx/rx after returning.
    virtual IoStatus exchange(const Frame& tx, Frame& rx,
                              std::uint32_t timeout_us) noexcept = 0;
    [[nodiscard]] virtual LinkKind kind() const noexcept = 0;
};

class IClock {
public:
    virtual ~IClock() = default;
    [[nodiscard]] virtual std::uint64_t now_us() const noexcept = 0;
    virtual void sleep_us(std::uint32_t duration_us) noexcept = 0;
};

} // namespace nexus
