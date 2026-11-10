# Protocol manifest compiler

NEXUS-HW includes a small JSON manifest compiler that validates documented,
read-only command frames and emits a C++ `SeedSet` and `ProtocolProfile` header.
The compiler is intended to eliminate hand-edited frame definitions and catch
unsafe or malformed corpus entries before a build.

## Example

```bash
python3 tools/nexus_protocol.py \
  --input examples/protocols/lab-demo-v1.json \
  --output generated/lab_protocol.hpp
```

The manifest uses schema `nexus.protocol.v1` and contains:

- `link`: `uart`, `spi`, or `i2c`;
- response signatures (`ack`, `nack`, `device_error`), maximum 8 bytes each;
- `commands`: at most 16 entries;
- unique 16-bit command tags;
- `classification` must be `documented_read_only`;
- fixed-length frame hex, immutable prefix and minimum mutable payload;
- optional supported checksum metadata with range and overlap validation.

Only entries explicitly marked `documented_read_only` are emitted. Unknown,
write, reset, erase, unlock, programming or actuator command classes are rejected
by the compiler instead of silently entering a physical corpus. The output is
source code; it must still be reviewed against the device's own protocol
documentation and electrical interface before use.

The tool validates the manifest and generates C++ without opening a serial
port, probing a device, or accessing hardware.
