# Sample target diagnostic logs

All logs in this directory are synthetic examples for parser tests. They are not captured from a commercial device and do not describe a real vulnerability.

Try:

```bash
python3 tools/nexus_triage.py --input examples/logs/esp32s3_stack_canary.log
python3 tools/nexus_triage.py --input examples/logs/esp32s3_loadprohibited.log
python3 tools/nexus_triage.py --input examples/logs/cortexm_precise_busfault.log
```

For a combined NEXUS trigger and target panic log, concatenate the NEXUS USB-serial capture and independent target diagnostic console capture, then provide the combined file to the triage tool.
