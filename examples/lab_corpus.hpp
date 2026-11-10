#pragma once
#include "nexus/types.hpp"

namespace nexus::example {

// Example benign/read-only status-query corpus for a fictional lab target.
// Replace these bytes ONLY with commands documented as safe for your own fixture.
inline SeedSet make_lab_corpus() noexcept {
    SeedSet set{};
    set.count = 2;

    set.entries[0].frame.size = 4;
    set.entries[0].frame.bytes = {0x10, 0x00, 0x00, 0x00};
    set.entries[0].immutable_prefix = 1;
    set.entries[0].minimum_mutable_bytes = 1;
    set.entries[0].command_tag = 0x0010;

    set.entries[1].frame.size = 4;
    set.entries[1].frame.bytes = {0x11, 0x01, 0x00, 0x00};
    set.entries[1].immutable_prefix = 1;
    set.entries[1].minimum_mutable_bytes = 1;
    set.entries[1].command_tag = 0x0011;
    return set;
}

inline ProtocolProfile make_lab_profile() noexcept {
    ProtocolProfile profile{};
    profile.ack.size = 1;
    profile.ack.bytes[0] = 0x06;
    profile.nack.size = 1;
    profile.nack.bytes[0] = 0x15;
    profile.device_error.size = 1;
    profile.device_error.bytes[0] = 0x7F;
    return profile;
}

} // namespace nexus::example
