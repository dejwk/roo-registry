# Pico I/O validation

This evidence retains the original checkpoints from before history
consolidation. See [the review revisions](review_revisions.json) and
[history mapping](history_rewrite.json) for the current phase series.

This initial profile matrix corresponds to the source revisions in
[revisions.json](revisions.json). Later board tests and focused regressions
are recorded separately in [BOARD_VALIDATION.md](BOARD_VALIDATION.md).

The recursive I/O, logging, threading, time and RTC trees were tested with the
downstream clock harness and focused touch target. The legacy touch/display
sharing regression also ran on classic ESP32. Counts are compatible Bazel test
targets, including reused passing results from the global disk cache.

| Profile | Normal | ASAN |
|---|---:|---:|
| arduino_esp32 | 87 | 87 |
| idf_esp32 | 80 | 80 |
| arduino_esp32s3 | 86 | 86 |
| idf_esp32s3 | 79 | 79 |
| arduino_esp32c3 | 86 | 86 |
| idf_esp32c3 | 79 | 79 |
| pico_rp2040 | 68 | 68 |
| arduino_rp2040 | 82 | 82 |
| arduino_rp2040_freertos | 88 | 88 |

The focused XPT2046 target supports eight profiles; SDK-only Pico touch HAL
integration is explicitly outside that target. Full native display emulation
retains its classic ESP32 qualification boundary. Hardware pixel source files
were not modified.

Additional checks:

- cquery confirmed Pico I2C/SPI/Stream/storage dependencies contain neither ESP-IDF nor Arduino-ESP32 framework targets.
- An explicit bare-metal ringpipe build was rejected as incompatible.
- All vendored profile fragments and tools match roo_testing byte-for-byte.
- The real release-note parser accepts all seven prepared library entries.
- The integration workspace passed all 10 selected FreeRTOS/ASAN tests from its own directory with relative overrides.
- Both rpipico firmware variants produced ELF/UF2 artifacts with exceptions and RTTI disabled; the SDK UART views also compiled against ARM headers.

Firmware used the installed Arduino-Pico framework package 1.50403.0, while
host tests used the imported 6.3.1 API. On-board SD electrical behavior and
LittleFS readback were unqualified at this initial matrix checkpoint.
The later board record qualifies LittleFS on both runtimes; physical SD
testing is still pending.
No GitHub releases, tags, or public registry archive entries were published.
