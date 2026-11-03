#!/usr/bin/env python3
"""Compile local Pico storage firmware without resolving unpublished packages."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--platform", required=True, help="Installed PlatformIO platform with Arduino-Pico support")
parser.add_argument("--output", type=Path, default=Path.home() / ".cache/roo_testing/pico-io-firmware")
parser.add_argument("--pio", default=str(Path.home() / ".platformio/penv/bin/pio"))
parser.add_argument("--board", default="rpipico", help="Installed PlatformIO board ID")
parser.add_argument("--without-sd", action="store_true", help="Skip SD probing and test onboard flash only")
parser.add_argument("--format-if-needed", action="store_true", help="Explicitly allow formatting an unmountable test partition; back up flash first")
args = parser.parse_args()
smoke_flags = []
if args.without_sd:
    smoke_flags.append("-DROO_IO_PICO_SMOKE_SD=0")
if args.format_if_needed:
    smoke_flags.append("-DROO_IO_PICO_SMOKE_FORMAT_IF_NEEDED=1")
smoke_flags = " ".join(smoke_flags)
checkouts = Path(__file__).resolve().parents[3]
output = args.output.resolve()
output.mkdir(parents=True, exist_ok=True)
(output / "src").mkdir(exist_ok=True)
for name in ["roo_io", "roo_backport", "roo_logging", "roo_threads", "roo_time", "roo_flags"]:
    source = checkouts / name
    snapshot = output / "local-libs" / name
    if snapshot.exists():
        shutil.rmtree(snapshot)
    shutil.copytree(source / "src", snapshot / "src")
    manifest = json.loads((source / "library.json").read_text())
    # Source stays byte-for-byte identical. Local discovery supplies dependencies
    # until their prepared versions exist in the public PlatformIO registry.
    manifest["dependencies"] = {}
    (snapshot / "library.json").write_text(json.dumps(manifest, indent=2) + "\n")
    shutil.copy2(source / "library.properties", snapshot / "library.properties")
shutil.copy2(checkouts / "roo_io/examples/PicoStorageSmoke/PicoStorageSmoke.ino", output / "src/main.ino")
(output / "src/sdk_uart_compile.cpp").write_text(
    '#include "roo_io/uart/pico/uart.h"\n'
    'void CompileSdkUart() {\n'
    '  roo_io::PicoUartInputStream input(uart0);\n'
    '  roo_io::PicoUartOutputStream output(uart0);\n'
    '}\n'
)
(output / "platformio.ini").write_text(f"""[platformio]
lib_dir = local-libs
libdeps_dir = local-dependencies

[env:pico]
platform = {args.platform}
board = {args.board}
framework = arduino
board_build.core = earlephilhower
board_build.filesystem_size = 0.5m
lib_ldf_mode = deep+
build_flags = -fno-exceptions -fno-rtti {smoke_flags}

[env:pico_freertos]
extends = env:pico
build_flags = -fno-exceptions -fno-rtti -DPIO_FRAMEWORK_ARDUINO_ENABLE_FREERTOS {smoke_flags}
""")
subprocess.run([args.pio, "run", "-e", "pico", "-e", "pico_freertos", "-j", "2"], cwd=output, check=True)
