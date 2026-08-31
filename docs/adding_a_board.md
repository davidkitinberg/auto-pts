# Adding a board to the Zephyr AutoPTS flow

Board support is independent of Bluetooth profiles. Add the board once, then
the same integration is used by every profile implemented by the Zephyr BTP
tester.

## What is required

Start by checking whether Zephyr already supports the board and whether its
runner can flash it:

```bash
west boards | grep <board-name>
west build -b <board-target> zephyr/tests/bluetooth/tester
west flash --skip-rebuild
```

If basic Zephyr or debugger support is missing, this is a board port rather
than an AutoPTS-only change. It may require DTS, pinctrl, Kconfig, runner, and
OpenOCD files in their respective repositories.

When that support already exists, review these three integration points:

| Integration | When it is needed | How to decide |
|---|---|---|
| `autopts/ptsprojects/boards/<name>.py` | For a hardware board controlled by AutoPTS | Define `supported_projects` and `reset_cmd()`. The module name becomes the AutoPTS `--board` value. `board_type` and `build_and_flash()` are additionally required by AutoPTS Bot when it builds/flashes firmware. The normal one-click client does not call `build_and_flash()`. |
| `zephyr/tests/bluetooth/tester/boards/<board>.overlay` | Only when the board DTS does not already select the UART used by BTP | The final devicetree must contain `zephyr,uart-pipe = &<uart>;`. Select the UART physically routed to the debugger's USB serial bridge. Remove console/shell chosen nodes if they refer to that same UART. |
| `zephyr/tests/bluetooth/tester/boards/<board>.conf` | Only for board-specific Kconfig differences not covered by `prj.conf` | First build without it and inspect `build/zephyr/.config`, warnings, and runtime behavior. Add only proven deltas such as a board-specific power-management or driver requirement. Do not duplicate values already forced by tester `prj.conf`. |

The filenames under the tester's `boards/` directory must match Zephyr's
normalized board target. For multi-qualifier boards, Zephyr normally joins the
board and qualifiers with underscores; use existing files in that directory as
examples and confirm the selected files in the CMake build output.

## What can be reused within a board family

Boards in one SoC family often share the OpenOCD target, reset sequence, UART
driver, and Kconfig requirements. Treat those as defaults to verify, not as
proof: package variants and board layouts can route a different UART or use a
different debug probe.

Use this decision sequence for a related board:

1. Compare the base DTS `chosen` node and UART pinctrl with a working sibling.
2. Compare the board defconfig and the tester's final `.config`.
3. Compare the Zephyr runner and OpenOCD board configuration.
4. Build and flash the tester without a board `.conf`; add one only when the
   build output or a runtime test demonstrates a missing setting.
5. Verify that AutoPTS receives the binary BTP IUT-ready event on the selected
   serial interface and that resets reproduce it reliably.

This checklist is the repository source of truth and can also be used as the
input for a team automation skill. Keeping the decisions here prevents a skill
from silently carrying assumptions that are valid for one TI family but not
for another.

## WSL USB setup

The one-click runner defaults to TI XDS110 (`0451:bef3`) and USB CDC interface
`00`. Override these with `--usb-id`, `--usb-interface`, or `--tty` for another
probe design.

Sharing a USB device is a one-time Administrator action on Windows:

```powershell
usbipd list
usbipd bind --busid <BUSID>
```

The runner performs the recurring `usbipd attach --wsl` action itself.

For persistent non-root serial access, add the user to `dialout` and install an
appropriate udev rule. For XDS110, for example:

```udev
SUBSYSTEM=="tty", ATTRS{idVendor}=="0451", ATTRS{idProduct}=="bef3", GROUP="dialout", MODE="0660"
```

Until such a rule is installed, the runner applies temporary permissions when
needed.
