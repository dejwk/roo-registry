# Pico I/O integration and release preparation

See [the phase commits for review](COMMITS.md),
[current review revisions](review_revisions.json) and
[validation evidence](VALIDATION.md).

The history was consolidated on 2026-11-04. Pico-specific fixes belong to their
phase; general Arduino/filesystem fixes are independent commits. CI pins follow
the rewritten testing phase. The
[history mapping](history_rewrite.json) connects every original commit to
its review commits. The [profile matrix](revisions.json) and
[board records](board_revisions.json) preserve exact original test
checkpoints; the review series also includes their later fixes.

The earlier Wire correction removes the emulator-only receive cleanup from
roo_io history. Buffer limits, no-op flush, caller-managed synchronization,
pin checks and address probes now follow the pinned Arduino-Pico core in
roo_testing. [Wire validation](wire_parity_validation.json) retains its exact
source hashes and tests.

The current storage review selects `PicoLittleFsMountImpl` under the Pico
compilation guard, moves parent restoration out of shared Arduino mounts, and
removes the GPIO presence API. SPI presence probes remain available. GPIO card
detection is deferred until a platform-independent digital-input API exists.
See [storage validation](storage_review_validation.json) for the current source
hashes, isolated storage-commit checks, host tests and firmware compiles.

Run `./test_profiles` from this directory with sibling Roo checkouts in their
usual layout. It tests all nine canonical profiles sequentially in normal and
ASAN modes, preserving `~/.bazelrc` resource limits and disk cache. Bazel uses
its normal persistent output root; never redirect Bazel storage under `/tmp`.
This standalone workspace uses local path overrides for the coordinated changes.

The consumer test runs the unchanged DS3231 and DS3234 production drivers through
both Arduino-Pico runtimes and SDK-only Pico, against independent clock fakes.
ESP profiles also run existing RTC and XPT2046 touch regressions. Pixel transport
implementations are outside this change.

Prepared versions and publication order:

| Order | Library | Version | Reason |
|---|---|---|---|
| 1 | roo_testing | 2.5.0 | Pico runtimes, canonical profiles and FS fakes |
| 2 | roo_time | 2.1.0 | Formatter APIs and Pico framework selection |
| 3 | roo_threads | 1.3.0 | Physical Pico runtime selection |
| 4 | roo_logging | 1.6.0 | Portable SDK formatter |
| 5 | roo_io | 2.5.0 | Portable targets, Pico transports and storage |
| 6 | roo_rtc | 0.1.0 | First release, including Pico transport validation |
| 6 | roo_display | 3.5.0 | Focused XPT2046 target and coherent I/O dependencies |

The source repositories carry matching module/library versions, dependency
minimums, release notes and CI. Consumer CI pins the roo_testing implementation
commit that supplies the new profile and filesystem APIs. Publish each dependency
and register its real release archive before releasing the next library. Use
`bin/release.py <library> --current --nolatest_deps` from the Roo parent directory
and its normal review/CI flow. For roo_testing, omit PlatformIO publication.
The first roo_rtc 0.1.0 has no earlier version tag; its metadata is prepared here.
After pushing its tested commit and passing commit CI, use
`bin/github_release.py roo_rtc` for that first publication.

No GitHub tags/releases or public registry entries are created by preparing these
commits. `source.json` integrity must be calculated from the actual published
archive; local archive hashes or placeholders must not be committed as release
metadata. After publication, this workspace can also validate registry resolution
by temporarily removing its local path overrides.

The PicoStorageSmoke sketch builds with the installed Arduino-Pico framework
package 1.50403.0 for both physical runtimes. Host tests use pinned core 6.3.1.
The subsequent [RP2040-Zero board tests](BOARD_VALIDATION.md) passed LittleFS
readback and lifecycle checks on both runtimes. Electrical SD behavior
remains unqualified because no SD module was connected.
To repeat the firmware compile using an installed PlatformIO platform that
supports Arduino-Pico:

```sh
python3 build_firmware.py --platform /path/to/installed/raspberrypi-platform
```

The helper snapshots the current library sources without editing them and
replaces only snapshot dependency metadata with local discovery. This avoids
asking PlatformIO for the prepared versions before they are published. It builds
the selected board (default `rpipico`) on bare-metal and FreeRTOS with
exceptions/RTTI disabled and compiles the
SDK UART views against ARM headers. Artifacts stay under
`~/.cache/roo_testing/pico-io-firmware` by default. The sketch uses SPI0/CS17 for
SD and requires explicitly provisioned LittleFS for physical readback.

For an RP2040-Zero without an SD module:

```sh
python3 build_firmware.py --platform /path/to/installed/raspberrypi-platform \
  --board waveshare_rp2040_zero --without-sd
```

Connect a serial monitor at 115200 baud with DTR asserted to run one pass;
send `t` to repeat. A successful run ends with
`ROO_IO_STORAGE_RESULT=PASS`. The sketch uses a dedicated directory and
refuses to overwrite one left by a previous run. Provision LittleFS
explicitly, or add `--format-if-needed` after backing up the complete
flash image. That option allows erasing an unmountable test partition.
The helper compiles firmware; flashing and backup/restore are separate.
