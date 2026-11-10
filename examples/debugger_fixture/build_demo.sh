#!/usr/bin/env sh
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
cd "$ROOT"
mkdir -p examples/debugger_fixture examples/reports
c++ -std=c++20 -g3 -O0 -fno-omit-frame-pointer -fno-pie -no-pie \
  -Wl,--build-id=sha1 -Wl,-Map=examples/debugger_fixture/demo_target.map \
  examples/debugger_fixture/demo_target.cpp -o examples/debugger_fixture/demo_target.elf
BUILD_ID="$(readelf -n examples/debugger_fixture/demo_target.elf | sed -n 's/.*Build ID: //p' | head -n 1)"
PC="$(nm -n examples/debugger_fixture/demo_target.elf | awk '$3 ~ /parse_frame/ {print "0x"$1; exit}')"
MAIN="$(nm -n examples/debugger_fixture/demo_target.elf | awk '$3 == "main" {print "0x"$1; exit}')"
: "${BUILD_ID:?failed to obtain ELF Build ID}"
: "${PC:?failed to find parse_frame symbol}"
: "${MAIN:?failed to find main symbol}"
SP=0x7fffffffdc80
cat > examples/debugger_fixture/synthetic-gdb-capture.log <<EOF
NEXUS_DEBUG_CAPTURE,profile=synthetic,arch=synthetic-native-ELF-fixture,mode=offline-core,remote=,halt=0
NEXUS_ELF_BUILD_ID=$BUILD_ID
NEXUS_ELF_SHA256=see-demo-target.elf
TARGET_BUILD_ID=$BUILD_ID
NEXUS_CAPTURE_MODE=offline-core
NEXUS_TARGET_ACTION=synthetic transcript; no target connected
Program received signal SIGSEGV, Segmentation fault.
pc $PC $PC
sp $SP $SP
rbp 0x7fffffffdca0 0x7fffffffdca0
rax 0x0 0
rdi 0x0 0
rsi 0x4 4
* 1 Thread 1 (LWP 4242)
#0  $PC in parse_frame (payload=0x0, length=4) at $(pwd)/examples/debugger_fixture/demo_target.cpp:11
#1  $MAIN in main () at $(pwd)/examples/debugger_fixture/demo_target.cpp:18
$SP: 0x0000000000000000 $MAIN $PC 0x0000000000000004
EOF
python3 tools/nexus_triage.py \
  --input examples/debugger_fixture/synthetic-gdb-capture.log \
  --elf examples/debugger_fixture/demo_target.elf \
  --map examples/debugger_fixture/demo_target.map \
  --source-root examples/debugger_fixture \
  --format html --output examples/reports/debugger-workbench-demo.html
python3 tools/nexus_triage.py \
  --input examples/debugger_fixture/synthetic-gdb-capture.log \
  --elf examples/debugger_fixture/demo_target.elf \
  --map examples/debugger_fixture/demo_target.map \
  --source-root examples/debugger_fixture \
  --format json --output examples/reports/debugger-workbench-demo.json
printf 'Generated synthetic workbench report: examples/reports/debugger-workbench-demo.html\n'
