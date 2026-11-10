cmake_minimum_required(VERSION 3.20)
project(NEXUS_HW VERSION 0.7.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

option(NEXUS_ENABLE_SANITIZERS "Build native targets with AddressSanitizer and UndefinedBehaviorSanitizer" OFF)
option(NEXUS_WARNINGS_AS_ERRORS "Treat compiler warnings as errors" OFF)

if(NEXUS_ENABLE_SANITIZERS)
    if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
        add_compile_options(-fsanitize=address,undefined -fno-omit-frame-pointer -fno-sanitize-recover=all -g3)
        add_link_options(-fsanitize=address,undefined -fno-omit-frame-pointer)
    else()
        message(FATAL_ERROR "NEXUS_ENABLE_SANITIZERS requires GCC or Clang")
    endif()
endif()

if(NEXUS_WARNINGS_AS_ERRORS)
    add_compile_options(-Werror)
endif()

add_library(nexus_core src/engine.cpp)
target_include_directories(nexus_core PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)
target_compile_options(nexus_core PRIVATE -Wall -Wextra -Wpedantic -Wconversion -Wshadow)

add_executable(nexus_sim host/native_simulator.cpp)
target_include_directories(nexus_sim PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/examples)
target_link_libraries(nexus_sim PRIVATE nexus_core)
target_compile_options(nexus_sim PRIVATE -Wall -Wextra -Wpedantic)

add_executable(nexus_tests tests/test_core.cpp)
target_link_libraries(nexus_tests PRIVATE nexus_core)
target_compile_options(nexus_tests PRIVATE -Wall -Wextra -Wpedantic)

enable_testing()
add_test(NAME nexus_core_tests COMMAND nexus_tests)

find_package(Python3 COMPONENTS Interpreter QUIET)
if(Python3_Interpreter_FOUND)
    add_test(NAME nexus_triage_tests
             COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_triage.py)
    add_test(NAME nexus_minimizer_tests
             COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_minimizer.py)
    add_test(NAME nexus_coverage_tests
             COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_coverage.py)
    add_test(NAME nexus_debug_tests
             COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_debug.py)
    add_test(NAME nexus_checksum_tests
             COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_checksum.py)
    add_test(NAME nexus_session_tests
             COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_session.py)
    add_test(NAME nexus_bundle_tests
             COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_bundle.py)
    add_test(NAME nexus_dashboard_tests
             COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_dashboard.py)
    add_test(NAME nexus_protocol_tests
             COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_protocol.py)
    add_test(NAME nexus_cli_doctor COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tools/nexus_doctor.py --json)
    add_test(NAME nexus_cli_help COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tools/nexus.py --help)
    add_test(NAME nexus_cli_version COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tools/nexus.py version)
endif()

add_test(NAME nexus_sim_smoke COMMAND nexus_sim)
add_test(NAME nexus_campaign_smoke COMMAND nexus_sim --campaign 300 1337 ${CMAKE_CURRENT_BINARY_DIR}/campaign-smoke.jsonl)
set_tests_properties(nexus_campaign_smoke PROPERTIES PASS_REGULAR_EXPRESSION "CAMPAIGN_SUMMARY")
add_test(NAME nexus_opcode_sweep_sim COMMAND nexus_sim --opcode-sweep-sim)
set_tests_properties(nexus_opcode_sweep_sim PROPERTIES PASS_REGULAR_EXPRESSION "tested=256")
add_test(NAME nexus_host_optimize COMMAND nexus_sim --host-optimize 256 ${CMAKE_CURRENT_BINARY_DIR}/nexus-optimized-corpus.hpp)
set_tests_properties(nexus_host_optimize PROPERTIES PASS_REGULAR_EXPRESSION "HOST_OPTIMIZE_SUMMARY")
