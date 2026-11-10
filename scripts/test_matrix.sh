#!/usr/bin/env sh
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

cmake -S "$ROOT" -B "$ROOT/build-release" -DCMAKE_BUILD_TYPE=Release -DNEXUS_WARNINGS_AS_ERRORS=ON
cmake --build "$ROOT/build-release" --parallel
ctest --test-dir "$ROOT/build-release" --output-on-failure

cmake -S "$ROOT" -B "$ROOT/build-sanitize" -DCMAKE_BUILD_TYPE=Debug -DNEXUS_ENABLE_SANITIZERS=ON
cmake --build "$ROOT/build-sanitize" --parallel
ASAN_OPTIONS="detect_leaks=1:strict_string_checks=1" UBSAN_OPTIONS="print_stacktrace=1:halt_on_error=1" \
  ctest --test-dir "$ROOT/build-sanitize" --output-on-failure
