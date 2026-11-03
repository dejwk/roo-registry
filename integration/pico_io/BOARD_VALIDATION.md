# RP2040-Zero storage qualification

Source hashes in this record identify the original tested checkpoints.
The [review series](COMMITS.md) consolidates later fixes into those phases;
[history_rewrite.json](history_rewrite.json) records the correspondence.

Test date: 2026-11-03. User-supplied RP2040-Zero, RP2040 B2, 2 MiB flash;
no SD module connected. Both physical Arduino-Pico runtimes passed the finite
PicoStorageSmoke sketch. The original complete flash image was restored and
verified byte for byte after testing, then its application was rebooted.

| Runtime | LittleFS smoke | SD | Serial evidence |
|---|---|---|---|
| Bare-metal | PASS | Skipped | [pico.log](board_logs/pico.log) |
| FreeRTOS | PASS | Skipped | [pico_freertos.log](board_logs/pico_freertos.log) |

The checks cover four 64-byte writes, a 16-byte append, flush/close, stat,
existing-file rejection, rename, directory iteration, full readback after
unmount/remount, seek, zero-length reads, read-only policy, file-held mount
lifetime, stale mount handles, deletion and lazy-cache unmount. Each run ends
with `ROO_IO_STORAGE_RESULT=PASS`. These are filesystem tests; UART wire
completion, electrical SD transfers, SMP and interrupt timing are not qualified
by this sketch.

## Regression found on the board

The first physical run failed the final directory removal: Arduino-Pico
LittleFS automatically removes empty parent directories when deleting their
last entry. Its raw `rmdir()` also aliases `remove()`. This behavior exists in
both the installed 5.4.3 core and the
[pinned 6.3.1 implementation](https://github.com/earlephilhower/arduino-pico/blob/53f1d8ee31a9565a15731c5aad8a6297bdf70144/libraries/LittleFS/src/LittleFS.h).

The roo_testing LittleFS fake now reproduces those side effects. A new Roo
storage regression failed against the old adapter, then passed after the
adapter restored missing ancestors after deletion. SDFS retains its separate
behavior. Both final board runs passed with the adapter correction.

## Firmware and preservation

The firmware uses Arduino-Pico 5.4.3 (PlatformIO framework 1.50403.0), board ID
`waveshare_rp2040_zero` and a 0.5 MiB LittleFS partition. Both variants compile
with exceptions and RTTI disabled. The FreeRTOS build additionally defines
`PIO_FRAMEWORK_ARDUINO_ENABLE_FREERTOS`.

```sh
python3 build_firmware.py --platform /path/to/installed/raspberrypi-platform \
  --board waveshare_rp2040_zero --without-sd --format-if-needed
```

Before flashing, a complete 2,097,152-byte image was saved and verified. The
original LittleFS partition was unformatted, so the explicitly enabled format
option was used to provision the temporary test partition. Later runs mounted
it without formatting. After both runs, the original image was written back,
read back in full and compared byte for byte. Backup images remain local and
are not included in this repository.

Exact source revisions and UF2 SHA-256 digests are in
[board_revisions.json](board_revisions.json). Every firmware roo_io source and
the smoke sketch were compared against storage commit `8611733` with no
differences. The subsequent stream close/destruction correction (`58f319d`)
was tested separately on the host; the board sketch does not use that adapter.

## Focused host regressions

The following checks passed with the follow-up sources. The original full
nine-profile normal/ASAN matrix remains recorded against its original source
checkpoint in [VALIDATION.md](VALIDATION.md) and [revisions.json](revisions.json).

| Scope | Profile | ASAN | Compatible tests passed |
|---|---|---|---:|
| All roo_io Pico tests, fake FS test, smoke sketch build | arduino_rp2040 | Yes | 6 |
| All roo_io Pico tests, fake FS test, smoke sketch build | arduino_rp2040_freertos | Yes | 6 |
| Existing roo_io filesystem tests | arduino_esp32 | No | 5 |
| Stream close/destruction contract | arduino_esp32 | No | 1 |
| Stream close/destruction contract | arduino_rp2040 | Yes | 1 |
| Stream close/destruction contract | arduino_rp2040_freertos | Yes | 1 |

The stream rows include the final close/destruction changes. The six-test Pico
runs preceded that small stream correction; its focused test was then rerun
on both Pico profiles. No second full profile matrix is claimed.

Run the same host scopes from this integration workspace:

```sh
bazel test @roo_io//test/pico:all @roo_testing//test/arduino_pico:filesystem_test \
  @roo_io//examples/PicoStorageSmoke:PicoStorageSmoke \
  --config=roo_testing_arduino_rp2040 --config=asan
bazel test @roo_io//test/pico:stream_contract_test \
  --config=roo_testing_arduino_rp2040_freertos --config=asan
```

Use `roo_testing_arduino_rp2040_freertos` for the other full Pico scope and
`roo_testing_arduino_esp32` for ESP32. Keep Bazel storage persistent and retain
the global resource limits and disk cache. No releases, tags or public registry
archives were published by this follow-up.
