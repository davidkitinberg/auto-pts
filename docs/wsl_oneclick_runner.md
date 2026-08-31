# WSL one-click AutoPTS runner

`tools/run_autopts_oneclick.sh` owns the routine setup around an AutoPTS test
run. The board still needs its one-time repository integration, described in
[adding_a_board.md](adding_a_board.md).

## Before this change

The user had to find the XDS110 BUSID, run `usbipd attach`, find which
`/dev/ttyACM*` represented the BTP UART, fix its permissions, supply the
Windows host IP, and ensure the Windows side was ready. The runner handled
server/client orchestration but assumed `/dev/ttyACM0` and failed when the USB
device had not already been attached.

## Current flow

For each invocation the runner now:

1. Uses the control repository's `.venv` automatically when it exists, then
   detects the Windows host and WSL IP addresses unless overridden.
2. Finds the configured USB probe in `usbipd list`.
3. Attaches it to WSL when its state is `Shared`.
4. Waits for the matching CDC-ACM interface and selects it by USB VID:PID and
   interface number, independent of `ttyACM` enumeration order.
5. Ensures the serial device is accessible.
6. Reuses an existing Windows AutoPTS server or starts one owned by this run.
7. Starts the standard Zephyr AutoPTS client; the client creates the `socat`
   BTP bridge. A kernel/ELF path is not required in TTY mode.
8. Generates the report and cleans up only Windows processes created by this
   invocation.

## Change record

| Item | Intended change | Implemented result | Reason |
|---|---|---|---|
| USB availability | Remove the recurring manual WSL connection step | Detect by VID:PID, wait for enumeration, and attach when usbipd reports `Shared` | BUSIDs and WSL attachment are not stable across ports, unplugging, or WSL restarts |
| Serial port | Stop relying on `/dev/ttyACM0` | Select the configured USB interface from sysfs; keep `--tty` as an override | Linux enumeration order can change |
| Client/server | Make the test command own routine startup | Auto-detect IPs, reuse or launch the Windows server, then launch the client and its `socat` bridge | These are orchestration steps, not board-specific knowledge |
| Safety | Avoid privileged guessing | Keep Administrator `bind`, board selection, and multi-probe selection explicit | The test runner cannot elevate safely or infer the target MCU from an XDS110 descriptor |

Example:

```bash
cd auto-pts
./tools/run_autopts_oneclick.sh \
  --workspace-file 'C:\Users\USER\Documents\PTS\project.pqw6' \
  --board lp_em_cc2340r53
```

Use `--board lp_em_cc2745r10_q1` for the CC2745R10-Q1 integration. Board model
selection is intentionally explicit: an XDS110 USB descriptor identifies the
probe, not necessarily the MCU connected behind it.

## Intentional boundaries

- If usbipd reports `Not shared`, the runner prints the exact `usbipd bind`
  command. Binding requires an Administrator PowerShell and is not attempted
  by the test command.
- If more than one matching probe is connected, select one with
  `--usb-busid`; the runner does not choose randomly.
- `--tty`, `--pts-ip`, and `--local-ip` remain available as diagnostics and
  explicit overrides.
- `--no-usb-setup` and `--no-server-launch` preserve manually managed setups.
