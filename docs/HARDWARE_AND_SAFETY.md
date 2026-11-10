# Hardware setup and safety checklist

## Before wiring

- Confirm written authorization and isolate the target from production networks and safety-critical processes.
- Read the exact target schematic and datasheet. Identify signal direction, voltage, reference ground, pinout, bus mode, clock rate and address.
- Confirm both sides are 3.3 V compatible. ESP32-S3 GPIO is not 5 V tolerant; use appropriate level shifters.
- Use a current-limited bench supply. Do not power the target through an unknown signal pin.
- Keep a physical disconnect accessible. Start with the target unpowered while wiring.
- Verify that every corpus command is documented, read-only and safe to repeat. Exclude bootloader, unlock, write, erase, reset, actuator, calibration and safety-control commands.

## Example interface wiring (verify board pins)

| Bus | Attacker node | Target | Notes |
|---|---|---|---|
| UART | TX / RX / GND | RX / TX / GND | Cross TX/RX; match baud, parity and stop bits; share ground |
| SPI | SCK / MOSI / MISO / CS / GND | SCK / MOSI / MISO / CS / GND | Confirm voltage, SPI mode, chip-select timing and maximum clock |
| I²C | SDA / SCL / GND | SDA / SCL / GND | Confirm address and pull-up voltage; do not allow 5 V pull-ups onto ESP32 pins |
| Coverage sideband (ESP32-S3 option) | diagnostic TX / RX / GND | dedicated target diagnostic RX / TX / GND | Separate from fuzz bus; used for `NXCOV_BEGIN/READY` and per-case coverage; verify pin direction, voltage and isolation |

Do not connect to live PLC I/O, mains, vehicle control buses or deployed infrastructure. For automotive / industrial work use a vendor-approved isolated development fixture and the relevant safety process.

## ESP32-S3 default pin examples

UART: RX GPIO18, TX GPIO17. SPI: SCK GPIO12, MISO GPIO13, MOSI GPIO11, CS GPIO10. I²C: SDA GPIO8, SCL GPIO9. These are examples only and may conflict with board peripherals. Check your exact board revision before use.
