// Optional fault hook for firmware you own / are authorized to instrument.
// RP2040's Cortex-M0+ provides a stacked exception frame and HardFault entry;
// it does not provide the Cortex-M3/M4 CFSR/BFAR register set. This hook stores
// the core frame in .noinit SRAM and prints it after the next manual reset.
#include <Arduino.h>
#include <cstdint>

namespace {
constexpr std::uint32_t kFaultMagic = 0x4E584346UL; // "NXCF"
struct FaultSnapshot {
    std::uint32_t magic;
    std::uint32_t exc_return;
    std::uint32_t original_sp;
    std::uint32_t stacked[8]; // r0,r1,r2,r3,r12,lr,pc,xPSR
    std::uint32_t icsr;
    std::uint32_t checksum;
};

__attribute__((section(".noinit"), used)) volatile FaultSnapshot g_fault_snapshot;

std::uint32_t snapshot_checksum(const FaultSnapshot& value) {
    std::uint32_t x = value.magic ^ value.exc_return ^ value.original_sp ^ value.icsr;
    for (std::uint32_t item : value.stacked) x = (x << 5U) ^ (x >> 2U) ^ item;
    return x;
}
} // namespace

extern "C" __attribute__((used, noinline)) void nexus_rp2040_fault_capture(
    const std::uint32_t* exception_stack, std::uint32_t exc_return) {
    g_fault_snapshot.magic = kFaultMagic;
    g_fault_snapshot.exc_return = exc_return;
    g_fault_snapshot.original_sp = static_cast<std::uint32_t>(
        reinterpret_cast<std::uintptr_t>(exception_stack));
    for (std::uint32_t i = 0; i < 8; ++i) g_fault_snapshot.stacked[i] = exception_stack[i];
    g_fault_snapshot.icsr = *reinterpret_cast<volatile std::uint32_t*>(0xE000ED04UL);
    FaultSnapshot copy{};
    copy.magic = g_fault_snapshot.magic;
    copy.exc_return = g_fault_snapshot.exc_return;
    copy.original_sp = g_fault_snapshot.original_sp;
    for (std::uint32_t i = 0; i < 8; ++i) copy.stacked[i] = g_fault_snapshot.stacked[i];
    copy.icsr = g_fault_snapshot.icsr;
    g_fault_snapshot.checksum = snapshot_checksum(copy);
    for (;;) { __asm volatile("wfi"); }
}

extern "C" __attribute__((naked)) void HardFault_Handler(void) {
    __asm volatile(
        "tst lr, #4       \n"
        "ite eq           \n"
        "mrseq r0, msp    \n"
        "mrsne r0, psp    \n"
        "mov r1, lr       \n"
        "b nexus_rp2040_fault_capture \n");
}

void nexus_rp2040_print_fault_snapshot(Stream& out) {
    FaultSnapshot copy{};
    copy.magic = g_fault_snapshot.magic;
    copy.exc_return = g_fault_snapshot.exc_return;
    copy.original_sp = g_fault_snapshot.original_sp;
    for (std::uint32_t i = 0; i < 8; ++i) copy.stacked[i] = g_fault_snapshot.stacked[i];
    copy.icsr = g_fault_snapshot.icsr;
    copy.checksum = g_fault_snapshot.checksum;
    if (copy.magic != kFaultMagic || copy.checksum != snapshot_checksum(copy)) return;
    out.printf("RP2040_HARDFAULT,SP=0x%08lX,EXC_RETURN=0x%08lX,ICSR=0x%08lX\n",
               static_cast<unsigned long>(copy.original_sp),
               static_cast<unsigned long>(copy.exc_return),
               static_cast<unsigned long>(copy.icsr));
    out.printf("R0=0x%08lX R1=0x%08lX R2=0x%08lX R3=0x%08lX R12=0x%08lX LR=0x%08lX PC=0x%08lX XPSR=0x%08lX\n",
               static_cast<unsigned long>(copy.stacked[0]), static_cast<unsigned long>(copy.stacked[1]),
               static_cast<unsigned long>(copy.stacked[2]), static_cast<unsigned long>(copy.stacked[3]),
               static_cast<unsigned long>(copy.stacked[4]), static_cast<unsigned long>(copy.stacked[5]),
               static_cast<unsigned long>(copy.stacked[6]), static_cast<unsigned long>(copy.stacked[7]));
    g_fault_snapshot.magic = 0;
}
