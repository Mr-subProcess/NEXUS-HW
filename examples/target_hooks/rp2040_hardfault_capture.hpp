#pragma once
#include <Arduino.h>

// Call once after Serial.begin() and before starting the target application.
void nexus_rp2040_print_fault_snapshot(Stream& out);
