# Pico I/O review commits

The review series keeps Pico phase changes and general Arduino/filesystem fixes
in focused commits. Stages 6-7 now select `PicoLittleFsMountImpl` at the LittleFS
mount factory and omit GPIO card detection. Shared Arduino mounts retain their
native deletion behavior. Every reviewed commit before stages 6-7 is unchanged.

The earlier Wire correction remains in focused roo_testing commits; its
emulator-only roo_io workaround and dependent RTC assertion are absent.

See [current review revisions](review_revisions.json),
[the commit mapping](history_rewrite.json) and
[current storage validation](storage_review_validation.json).
[Wire parity results](wire_parity_validation.json),
[intermediate snapshots](atomic_review_validation.json),
[profile-matrix revisions](revisions.json) and
[board-test revisions](board_revisions.json) preserve their tested checkpoints;
local backup refs retain the original commit objects.

## roo_io

- `3758c5fa2e` — Pico I/O: Record the staged support and validation plan.
- `1f8d4f11e3` — Pico I/O stage 2: Separate portable and threaded facilities.
- `060e142c7e` — Pico I/O stage 3: Connect Arduino adapters to Pico.
- `53e8228142` — Validate bounded Arduino stream tryRead requests.
- `ea8eb1dffa` — Preserve progress and status in blocking Arduino stream reads.
- `1f0ed58ac2` — Propagate errors from Arduino stream writes.
- `88f50c1421` — Retry partial Arduino stream writes to completion.
- `b4a612c17b` — Flush borrowed Arduino streams and propagate backend errors.
- `50a357e7c5` — Preserve Arduino stream errors when closing a view.
- `49c1061ec7` — Flush Arduino output views during concrete destruction.
- `997e4aa728` — Pico I/O stage 5: Add native SDK I2C, SPI and UART transports.
- `de7beaf02f` — Declare ESP32 backend capability boundaries in Bazel.
- `23a7a07583` — Prevent stale handles from unmounting replacement filesystems.
- `cbba52f0a5` — Close Arduino file handles before releasing their mounts.
- `b4e6179451` — Preserve Arduino file-stream status on zero-length I/O.
- `31c48580f1` — Release cached Arduino SD mounts before wrapper destruction.
- `3be310bee0` — Check media presence before mounting generic Arduino SD.
- `2f6d36f94d` — Initialize Arduino SD members in declaration order.
- `3660be79fb` — Compile Arduino filesystem adapters without RTTI or exceptions.
- `31308dc1d7` — Share Arduino SD presence probes between platform backends.
- `f856cc6fa8` — Pico I/O stages 6-7: Add Arduino-Pico SD and LittleFS support.
- `5346cb5c5a` — Pico I/O stage 8: Align profiles and prepare roo_io 2.5.0.

## roo_testing

- `bc713e1ab7` — Pico I/O stage 7: Emulate Pico filesystems and SD presence commands.
- `fd3ca59bd0` — Pico I/O stage 8: Prepare roo_testing 2.5.0 for coordinated clients.
- `7cceed7c82` — Match Arduino-Pico Wire buffer and lifecycle behavior.
- `27aed03a82` — Remove artificial task reservations from Pico Wire emulation.
- `99ac7ec4a1` — Match Arduino-Pico Wire pin-selection checks.
- `966a69c31b` — Emulate Arduino-Pico Wire address-only probes.

## roo_threads

- `9819411a00` — Pico I/O stage 1: Follow the physical Pico runtime.
- `47be96c8a2` — Pico I/O stage 8: Validate threaded examples and prepare roo_threads 1.3.0.

## roo_logging

- `2790e537ec` — Pico I/O stage 1: Make logging independent of framework streams.
- `07829a7381` — Pico I/O stage 8: Validate portable logging and prepare roo_logging 1.6.0.

## roo_time

- `9dd8ba3d20` — Pico I/O stage 8: Align time backend tests and prepare roo_time 2.1.0.

## roo_rtc

- `a38a1edc70` — Pico I/O stage 8: Verify every RTC driver on the Pico runtimes.

## roo_display

- `546324371b` — Pico I/O stage 8: Qualify the focused XPT2046 target across platforms.

## roo-registry

The containing stage 8 commit supplies the integration workspace, firmware
helper, historical qualification evidence, current storage validation and this
review index. It creates no releases or tags.

There are 35 source commits across seven libraries and one registry
commit, for 36 review commits in total.
