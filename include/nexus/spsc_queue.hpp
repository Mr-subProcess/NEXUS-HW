#pragma once

#include <array>
#include <atomic>
#include <cstddef>
#include <type_traits>

namespace nexus {

// Single-producer/single-consumer bounded queue. No allocation and no locks.
template <typename T, std::size_t Capacity>
class SpscQueue {
    static_assert(Capacity >= 2, "Capacity must be at least two");
    static_assert(std::is_trivially_copyable_v<T>, "T must be trivially copyable");
public:
    [[nodiscard]] bool push(const T& value) noexcept {
        const std::size_t head = head_.load(std::memory_order_relaxed);
        const std::size_t next = increment(head);
        if (next == tail_.load(std::memory_order_acquire)) return false;
        slots_[head] = value;
        head_.store(next, std::memory_order_release);
        return true;
    }

    [[nodiscard]] bool pop(T& value) noexcept {
        const std::size_t tail = tail_.load(std::memory_order_relaxed);
        if (tail == head_.load(std::memory_order_acquire)) return false;
        value = slots_[tail];
        tail_.store(increment(tail), std::memory_order_release);
        return true;
    }

    [[nodiscard]] bool empty() const noexcept {
        return tail_.load(std::memory_order_acquire) == head_.load(std::memory_order_acquire);
    }

private:
    [[nodiscard]] static constexpr std::size_t increment(std::size_t value) noexcept {
        return (value + 1U) % Capacity;
    }
    std::array<T, Capacity> slots_{};
    alignas(64) std::atomic<std::size_t> head_{0};
    alignas(64) std::atomic<std::size_t> tail_{0};
};

} // namespace nexus
