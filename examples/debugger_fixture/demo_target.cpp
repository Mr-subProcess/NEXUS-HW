#include <cstddef>
#include <cstdint>

// Synthetic source fixture for demonstrating source mapping in the NEXUS HTML
// workbench. The capture log is fabricated; this program is not executed.
// The unchecked dereference illustrates the kind of parser boundary a report
// might point to after a real target-side fault has been independently captured.
__attribute__((noinline)) int parse_frame(const std::uint8_t* payload, std::size_t length) {
    if (length > 64U) {
        return -1;
    }
    const volatile std::uint32_t first = payload[0]; // synthetic fault-site example
    const volatile std::uint32_t size = static_cast<std::uint32_t>(length);
    return static_cast<int>(first + size);
}

int main() {
    const std::uint8_t sample[]{0x41U, 0x42U, 0x43U, 0x44U};
    return parse_frame(sample, sizeof(sample));
}
