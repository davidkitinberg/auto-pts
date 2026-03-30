# AutoPTS on TI LP-EM-CC2340R53 — Setup Guide & Troubleshooting

> **Board:** TI LP-EM-CC2340R53 (CC2340R53E0RKPR, Cortex-M0+, 512 KB Flash, 64 KB RAM)  
> **Debug Probe:** On-board XDS110 (USB VID `0451`, PID `bef3`)  
> **Zephyr:** 3.7.0 &nbsp;|&nbsp; **Zephyr SDK:** 0.16.8 &nbsp;|&nbsp; **OpenOCD:** 0.12.0+dev (TI fork)  
> **AutoPTS:** [intel/auto-pts](https://github.com/intel/auto-pts) (commit `cb256f0d`)

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Prerequisites](#2-prerequisites)
3. [Zephyr Environment Setup](#3-zephyr-environment-setup)
4. [Building the BTP Tester Firmware](#4-building-the-btp-tester-firmware)
5. [Board-Specific Configuration Files](#5-board-specific-configuration-files)
6. [Flashing the Firmware](#6-flashing-the-firmware)
7. [AutoPTS Setup (WSL / Linux Client)](#7-autopts-setup-wsl--linux-client)
8. [AutoPTS Setup (Windows Server)](#8-autopts-setup-windows-server)
9. [Running Tests](#9-running-tests)
10. [Troubleshooting](#10-troubleshooting)
11. [Problems Encountered & Fixes (Detailed)](#11-problems-encountered--fixes-detailed)
12. [Architecture Diagram](#12-architecture-diagram)
13. [File Reference](#13-file-reference)
14. [Appendix A: First-Time Installation Checklist](#appendix-a-first-time-installation-checklist)
15. [Appendix B: Daily Startup Procedure](#appendix-b-daily-startup-procedure)

---

## 1. Architecture Overview

AutoPTS is a framework for automated Bluetooth Profile Tuning Suite (PTS) testing. It consists of two components:

| Component | Runs On | Role |
|-----------|---------|------|
| **autoptsserver** | Windows | Controls the PTS dongle and PTS GUI via COM automation |
| **autoptsclient** | Linux / WSL | Controls the IUT (Implementation Under Test) board, communicates with the server over TCP |

For the CC2340R53 board, the client runs in **TTY mode**: it communicates with the board's firmware over a serial port (`/dev/ttyACM0`) using the **BTP (Bluetooth Test Protocol)** binary protocol. The serial-to-socket bridging is handled by `socat`.

```
┌─────────────────────────┐            ┌──────────────────────────┐
│  Windows Host           │            │  WSL / Linux             │
│                         │  TCP       │                          │
│  autoptsserver.py       │◄──65000──► │  autoptsclient-zephyr.py │
│  PTS Bluetooth Dongle   │◄──65001──► │                          │
│  172.21.128.1           │            │  172.21.144.1            │
└─────────────────────────┘            └──────────┬───────────────┘
                                                  │
                                             ┌────▼────┐
                                             │  socat  │
                                             └────┬────┘
                                                  │
                                     UNIX socket: /tmp/bt-stack-tester
                                                  │
                                             ┌────▼──────────┐
                                             │ /dev/ttyACM0  │ 115200 baud
                                             │  (XDS110 USB) │
                                             └────┬──────────┘
                                                  │
                                             ┌────▼──────────────────┐
                                             │  CC2340R53 MCU        │
                                             │  uart0 → UART_PIPE   │
                                             │  BTP tester firmware  │
                                             └───────────────────────┘
```

---

## 2. Prerequisites

### Hardware

- **TI LP-EM-CC2340R53** LaunchPad (with on-board XDS110 debug probe)
- USB cable connecting the LaunchPad to your PC
- **PTS Bluetooth dongle** connected to the Windows host

### Software — Linux / WSL Side

| Tool | Version Tested | Install |
|------|---------------|---------|
| Python | 3.12+ | `sudo apt install python3 python3-pip` |
| socat | 1.8.0+ | `sudo apt install socat` |
| TI OpenOCD (fork) | 0.12.0+dev | Build from source or TI installer |
| Zephyr SDK | 0.16.8 | [Zephyr SDK docs](https://docs.zephyrproject.org/latest/develop/toolchains/zephyr_sdk.html) |
| West | latest | `pip3 install west` |
| USB CDC-ACM driver | built-in | `sudo modprobe cdc_acm` (if `/dev/ttyACM*` doesn't appear) |

### Software — Windows Side

| Tool | Version / Notes | Install |
|------|----------------|--------|
| PTS (Profile Tuning Suite) | 8.x (latest) | [Bluetooth SIG downloads](https://www.bluetooth.com/develop-with-bluetooth/qualification-listing/qualification-test-tools/profile-tuning-suite/) (requires SIG account) |
| Teledyne LeCroy Frontline | Bundled with PTS dongle | See [Section 8.2](#82-pts-dongle--teledyne-firmware) |
| Python | 3.10+ | [python.org](https://www.python.org/downloads/windows/) — **check "Add Python to PATH"** during install |
| auto-pts | Latest master | `git clone https://github.com/intel/auto-pts.git` |
| pywin32, wmi, pyserial | — | `py -m pip install pywin32 wmi pyserial` |

---

## 3. Zephyr Environment Setup

```bash
# Clone Zephyr (if not done)
west init -m https://github.com/zephyrproject-rtos/zephyr ~/ti-workspace/zephyr
cd ~/ti-workspace/zephyr
west update

# Set up Zephyr environment
source zephyr-env.sh

# Verify the board is recognized
west boards | grep cc2340
# Expected: lp_em_cc2340r53/cc2340r53
```

### Python Virtual Environment

If you use a Python virtual environment (recommended), activate it before running any `west` or `pip` commands:

```bash
# Activate venv (if used)
source ~/ti-workspace/.venv/bin/activate
# You should see (.venv) at the beginning of your terminal prompt
```

> **Tip:** Without an active venv (or system install), `west` and other tools will not be found. If you see `west: command not found`, this is almost always the cause.

### Twister (Zephyr Test Runner)

Twister is Zephyr's built-in test runner. While AutoPTS does not use Twister directly, you may want it for local testing. Install its dependencies inside your venv:

```bash
cd ~/ti-workspace/zephyr
pip install -r scripts/requirements-base.txt
pip install -r scripts/requirements-run-test.txt
pip install -r scripts/requirements-build-test.txt
pip install setuptools

# Verify Twister works
python3 scripts/twister --help
```

> **Note:** `pip install -r scripts/requirements.txt` may show dependency-conflict warnings with TI SDK packages. This is harmless — installing the three individual requirements files above avoids those warnings.

### TI OpenOCD

The CC2340R53 requires TI's fork of OpenOCD with XDS110 support.

```bash
# Option A: TI installer (sets TI_OPENOCD_INSTALL_DIR)
# Download from TI's website and install

# Option B: Build from source
git clone https://github.com/nicandris/ti-openocd.git ~/ti-openocd
cd ~/ti-openocd
./bootstrap
./configure
make -j$(nproc)

# Verify
~/ti-openocd/src/openocd --version
```

---

## 4. Building the BTP Tester Firmware

```bash
cd ~/ti-workspace/zephyr/tests/bluetooth/tester

# Clean build
west build -p auto -b lp_em_cc2340r53/cc2340r53

# The output firmware is at:
#   build/zephyr/zephyr.hex
#   build/zephyr/zephyr.elf
```

The build system automatically picks up the board-specific overlay and .conf files from the `boards/` subdirectory (see [Section 5](#5-board-specific-configuration-files)).

### Memory Usage (typical)

| Region | Used | Available | Usage |
|--------|------|-----------|-------|
| Flash | ~265 KB | 512 KB | ~52% |
| RAM | ~53 KB | 64 KB | ~81% |

---

## 5. Board-Specific Configuration Files

Three files configure the BTP tester for this board. They are located under `tests/bluetooth/tester/boards/`:

### 5.1 Device Tree Overlay — `lp_em_cc2340r53.overlay`

```dts
/*
 * BTP tester overlay for TI LP_EM_CC2340R53
 *
 * The CC2340R53 has only one UART (uart0). It must be used exclusively
 * for BTP (uart-pipe). Console output MUST be disabled in Kconfig to
 * prevent text from corrupting the BTP binary protocol stream.
 */

/ {
    chosen {
        zephyr,uart-pipe = &uart0;
        /delete-property/ zephyr,console;
        /delete-property/ zephyr,shell-uart;
    };
};
```

**Why:** The CC2340R53 has a single UART (`uart0`) which must be dedicated to the BTP binary protocol via `uart-pipe`. Any console output on the same UART would corrupt BTP messages.

### 5.2 Board Kconfig — `lp_em_cc2340r53.conf`

```ini
# Disable power management — PM can suspend the UART during idle,
# causing BTP timeouts.
CONFIG_PM=n
CONFIG_PM_DEVICE=n

# Force console off (overrides board defconfig)
CONFIG_CONSOLE=n
CONFIG_UART_CONSOLE=n

# Required by uart-pipe
CONFIG_UART_INTERRUPT_DRIVEN=y
```

**Why:**
- **Power management** must be off because the CC2340R53's PM subsystem can gate the UART clock during idle periods, causing missed BTP messages and timeouts.
- **Console** must be explicitly disabled because the board's defconfig enables it by default.

### 5.3 Project Kconfig — `prj.conf` (shared, key excerpts)

```ini
CONFIG_SERIAL=y
CONFIG_UART_INTERRUPT_DRIVEN=y
CONFIG_UART_PIPE=y

CONFIG_CONSOLE=n
CONFIG_UART_CONSOLE=n
CONFIG_STDOUT_CONSOLE=n
CONFIG_PRINTK=n
CONFIG_EARLY_CONSOLE=n
CONFIG_BOOT_BANNER=n

CONFIG_BT=y
CONFIG_BT_CENTRAL=y
CONFIG_BT_PERIPHERAL=y
# ... (full BT profile config)
```

### UART Hardware Configuration

| Parameter | Value |
|-----------|-------|
| Peripheral | `uart0` @ `0x40034000` |
| Baud rate | 115200 |
| TX pin | DIO20 |
| RX pin | DIO22 |
| Flow control | None |
| Clock | 48 MHz |

---

## 6. Flashing the Firmware

### Using West (recommended)

```bash
cd ~/ti-workspace/zephyr/tests/bluetooth/tester
west flash --skip-rebuild
```

### Using OpenOCD directly

```bash
sudo ~/ti-openocd/src/openocd \
  -s ~/ti-openocd/tcl \
  -f board/ti_lp_em_cc2340r53.cfg \
  -c "init" \
  -c "halt" \
  -c "program ~/ti-workspace/zephyr/build/zephyr/zephyr.hex" \
  -c "shutdown"
```

> **Note:** Do NOT use `reset run` after programming — see [Section 11, Problem 2](#problem-2-openocd-reset-run-does-not-boot-the-application--btp-init-error) for why.

---

## 7. AutoPTS Setup (WSL / Linux Client)

### 7.1 Clone and Install

```bash
git clone https://github.com/intel/auto-pts.git ~/auto-pts
cd ~/auto-pts

# If using a venv, activate it first:
source ~/ti-workspace/.venv/bin/activate

# Install client requirements and the package itself
pip install -r autoptsclient_requirements.txt
pip install -e .
```

### 7.2 Install Runtime Dependencies

The `setup.py` does not declare all runtime dependencies. Some may not be covered by `autoptsclient_requirements.txt` either. Install them manually:

```bash
pip install \
  termcolor \
  hid \
  psutil \
  pyserial \
  pyyaml \
  pylink-square \
  xlsxwriter \
  gitpython \
  google-api-python-client \
  oauth2client
```

> **Note:** If you are installing system-wide (no venv), add `--break-system-packages` to each `pip install` command. Inside a venv this is not needed.

### 7.3 Install socat

```bash
sudo apt install socat
```

`socat` is **required** for TTY mode — it bridges the serial port to the UNIX domain socket that the BTP stack uses.

### 7.4 Verify USB Serial Port

When the LP-EM-CC2340R53 is plugged in via USB, the XDS110 debug probe creates **two** CDC-ACM serial ports:

| Port | USB Interface | Purpose |
|------|--------------|---------|
| `/dev/ttyACM0` | Interface 0 | **Main UART data** — use this for BTP |
| `/dev/ttyACM1` | Interface 3 | Backchannel UART — not used |

If the ports don't appear:

```bash
sudo modprobe cdc_acm
ls /dev/ttyACM*
```

Verify which is which:

```bash
udevadm info -a /dev/ttyACM0 | grep bInterfaceNumber
# Should show: ATTR{bInterfaceNumber}=="00"
```

### 7.5 Board Python File

The board-specific AutoPTS integration is at:

```
~/auto-pts/autopts/ptsprojects/boards/lp_em_cc2340r53.py
```

This file defines:
- **`reset_cmd(iutctl)`** — How to reset the board between test cases
- **`build_and_flash()`** — How to build and flash the Zephyr BTP tester firmware
- **`board_type`** — The Zephyr board identifier (`lp_em_cc2340r53/cc2340r53`)

### 7.6 OpenOCD Path Resolution

The board file resolves the TI OpenOCD path using:

1. **Environment variable** `TI_OPENOCD_INSTALL_DIR` → `$TI_OPENOCD_INSTALL_DIR/openocd/bin/openocd`
2. **Fallback** → `~/ti-openocd/src/openocd` (for source builds)

Set the environment variable if using the TI installer:

```bash
export TI_OPENOCD_INSTALL_DIR=/path/to/ti/ccs/tools/openocd
```

---

## 8. AutoPTS Setup (Windows Server)

The Windows host runs the PTS software, the Bluetooth dongle, and the `autoptsserver.py` bridge that lets the WSL client control PTS remotely.

### 8.1 Install PTS (Profile Tuning Suite)

1. **Download** the latest PTS (currently 8.x) from the [Bluetooth SIG website](https://www.bluetooth.com/develop-with-bluetooth/qualification-listing/qualification-test-tools/profile-tuning-suite/).  
   You need a registered Bluetooth SIG account to access the download.
2. **Install** it on Windows (standard Next → Next → Finish wizard).
3. After installation, open PTS and verify it detects the Bluetooth dongle.

### 8.2 PTS Dongle & Teledyne Firmware

The PTS dongle needs up-to-date firmware. After installing PTS:

1. Connect the PTS Bluetooth dongle to a USB port.
2. Download and run the **Latest PTS Firmware Upgrade Software Release** (provided by Teledyne LeCroy, or received as a ZIP from your contact).
3. In the upgrade tool, click **Modify** and let it finish.
4. Open the Windows Start menu and search for **PTS Firmware Upgrade**. Run it.
5. It will auto-detect the dongle's COM port and install the latest firmware (PTS password required).
6. In PTS, verify the sniffer is linked: **File → Application Settings → Sniffer**.

### 8.3 Install Python & auto-pts Dependencies

Install Python 3.10+ for Windows from [python.org](https://www.python.org/downloads/windows/).  
**Important:** Check **"Add Python to PATH"** at the bottom of the first installer screen.

Then open CMD or PowerShell and install the server-side packages:

```cmd
:: Clone auto-pts (if not done)
git clone https://github.com/intel/auto-pts.git
cd auto-pts

:: Install Windows-specific dependencies
py -m pip install pywin32 wmi pyserial

:: Install server requirements
py -m pip install --user -r autoptsserver_requirements.txt
py -m pip install -e .

:: Verify installation
py -m pip show auto-pts
```

### 8.4 Start the Server

```cmd
cd auto-pts
py autoptsserver.py -S 65000 -C 65001
```

The server listens on ports 65000 (main) and 65001 (callback). Leave this terminal open while running tests.

---

## 9. Running Tests

### Finding IP Addresses

Before running tests, you need the Windows host IP as seen from WSL and your own WSL IP.

```bash
# Method 1: Check the DNS resolver (often the Windows host IP)
cat /etc/resolv.conf | grep nameserver

# Method 2: Check the default gateway
ip route show | grep default | awk '{print $3}'

# Method 3: Run ipconfig in Windows and look for the "vEthernet (WSL)" adapter
```

Use the Windows IP for `-i` and your WSL IP for `-l`. You can get your WSL IP automatically with `$(hostname -I | awk '{print $1}')`.

### Serial Port Permissions

Before the first run, grant access to the serial port:

```bash
sudo chmod 666 /dev/ttyACM0
```

If WSL does not see `/dev/ttyACM0`, load the kernel module manually:

```bash
sudo modprobe cdc_acm
```

### Basic Command

```bash
cd ~/auto-pts

python3 ./autoptsclient-zephyr.py zephyr-master \
  "Z:\home\david\ti-workspace\zephyr\build\zephyr\zephyr.elf" \
  -t /dev/ttyACM0 \
  -b lp_em_cc2340r53 \
  -i <WINDOWS_IP> -S 65000 -C 65001 \
  -l <WSL_IP> \
  --iut-mode tty \
  --tty-baudrate 115200 \
  -d \
  -c <TEST_CASES>
```

### Parameter Reference

| Flag | Description | Example |
|------|-------------|---------|
| `zephyr-master` | Project name | — |
| 1st positional | Path to .elf (Windows path format for PTS) | `"Z:\home\david\...\zephyr.elf"` |
| `-t` | Serial port (TTY) | `/dev/ttyACM0` |
| `-b` | Board name | `lp_em_cc2340r53` |
| `-i` | PTS server IP (Windows host) | `172.21.128.1` |
| `-S` | Server port | `65000` |
| `-C` | Callback port | `65001` |
| `-l` | Local (client) IP | `172.21.144.1` |
| `--iut-mode` | Communication mode | `tty` |
| `--tty-baudrate` | Serial baud rate | `115200` |
| `-d` | Enable debug logging | — |
| `-c` | Test case(s) or profile name(s) | `GAP`, `GAP/BROB/BCST/BV-01-C` |
| `-e` | Exclude test case(s) | `GAP/SEC/SEM/BV-29-C` |
| `--test_case_limit` | Max number of tests to run | `10` |

### Examples

```bash
# Run a single test case
python3 ./autoptsclient-zephyr.py zephyr-master \
  "Z:\home\david\ti-workspace\zephyr\build\zephyr\zephyr.elf" \
  -t /dev/ttyACM0 -b lp_em_cc2340r53 \
  -i 172.21.128.1 -S 65000 -C 65001 \
  -l $(hostname -I | awk '{print $1}') \
  --iut-mode tty --tty-baudrate 115200 \
  -d -c GAP/BROB/BCST/BV-01-C

# Run all GAP tests
python3 ./autoptsclient-zephyr.py zephyr-master \
  "Z:\home\david\ti-workspace\zephyr\build\zephyr\zephyr.elf" \
  -t /dev/ttyACM0 -b lp_em_cc2340r53 \
  -i 172.21.128.1 -S 65000 -C 65001 \
  -l $(hostname -I | awk '{print $1}') \
  --iut-mode tty --tty-baudrate 115200 \
  -d -c GAP

# Run GAP and GATT profiles together
... -c GAP GATT

# Run specific tests
... -c GAP/BROB/BCST/BV-01-C GAP/BROB/BCST/BV-02-C GAP/CONN/UCON/BV-01-C
```

### Understanding Results

| Status | Meaning |
|--------|---------|
| **PASS** | Test passed |
| **FAIL** | Test failed (IUT behavior didn't match expected) |
| **INDCSV** | Inconclusive — PTS couldn't determine pass/fail |
| **BTP INIT ERROR** | Board didn't send IUT Ready event (reset/communication issue) |
| **FATAL ERROR** | Framework-level error (missing tool, connection failure) |
| **MISSING WID ERROR** | No WID (Workflow ID) handler registered for a PTS prompt |

---

## 10. Troubleshooting

### Board doesn't appear as `/dev/ttyACM*`

```bash
# Load the CDC-ACM kernel module
sudo modprobe cdc_acm

# Check USB devices
lsusb | grep 0451
# Expected: Bus ... Device ...: ID 0451:bef3 Texas Instruments, Inc.

# If in WSL, you may need to attach the USB device first:
# (from PowerShell as admin)
usbipd list
usbipd bind --busid <BUSID>
usbipd attach --wsl --busid <BUSID>
```

### Permission denied on `/dev/ttyACM0`

```bash
sudo chmod 666 /dev/ttyACM0
# Or add user to dialout group:
sudo usermod -aG dialout $USER
```

### "socat: command not found"

```bash
sudo apt install socat
```

### BTP INIT ERROR (board not responding)

This means the board didn't send the BTP IUT Ready event within 30 seconds. Check:

1. **Is the correct firmware flashed?** The BTP tester firmware must be built and flashed (not hello_world or any other sample).
2. **Is the serial port correct?** Use `/dev/ttyACM0` (interface 0), not `ttyACM1`.
3. **Is OpenOCD accessible?** The reset command requires `sudo` for OpenOCD. Check `sudo` doesn't prompt for a password (configure NOPASSWD if needed).
4. **Manual test:** Try the reset command manually and monitor serial:
   ```bash
   # In one terminal, monitor serial:
   cat /dev/ttyACM0 | xxd &
   
   # In another, run reset:
   sudo ~/ti-openocd/src/openocd \
     -s ~/ti-openocd/tcl \
     -f board/ti_lp_em_cc2340r53.cfg \
     -c init -c halt \
     -c "set vt0 [mrw 0x00000000]" \
     -c "set vt1 [mrw 0x00000004]" \
     -c "reg sp \$vt0" -c "reg pc \$vt1" \
     -c resume -c shutdown
   
   # You should see 5 bytes: 00 80 ff 00 00 (IUT Ready event)
   ```

### OpenOCD errors

- **"Error: no device found"** — USB not attached; check `lsusb` and WSL USB passthrough.
- **"Error: XDS110 ... not found"** — XDS110 firmware may need updating. Use TI's `xdsdfu` tool.
- **"Error: failed to reset target"** — This is expected for `reset run` on CC2340R53; the custom reset in the board file works around it.

### FATAL ERROR during test execution

Usually means the BTP socket disconnected mid-test. Common causes:
- Board crashed or hung (may need power cycle)
- `socat` process died
- USB disconnected

---

## 11. Problems Encountered & Fixes (Detailed)

### Problem 1: `socat` Not Installed — FATAL ERROR

**Symptom:** AutoPTS threw a `FATAL ERROR` immediately when starting any test case.

**Root Cause:** AutoPTS in TTY mode requires `socat` to bridge the serial port (`/dev/ttyACM0`) to a UNIX domain socket (`/tmp/bt-stack-tester`). The BTP stack communicates over this socket. Without `socat`, the bridge cannot be established and the framework crashes.

**How it works:** When `_start_tty_mode()` in `iutctl.py` runs, it spawns:
```
socat -x -v /dev/ttyACM0,rawer,b115200 UNIX-CONNECT:/tmp/bt-stack-tester
```
This opens the serial port in raw mode at 115200 baud and connects it to the UNIX socket that the BTP client listens on.

**Fix:**
```bash
sudo apt install socat
```

**Result:** Error changed from FATAL ERROR to BTP INIT ERROR.

---

### Problem 2: OpenOCD `reset run` Does Not Boot the Application — BTP INIT ERROR

**Symptom:** `BTP INIT ERROR 68.532` on every test case. The board's red LED showed it was resetting, but no BTP IUT Ready event was ever received over serial. AutoPTS waits 30 seconds, retries once (total ~68 seconds), then gives up.

**Investigation (step by step):**

1. **Serial port testing:** Connected to both `/dev/ttyACM0` and `/dev/ttyACM1` at every standard baud rate (9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600). **Zero bytes received** after OpenOCD `reset run`.

2. **hello_world test:** Built and flashed the Zephyr `samples/hello_world` sample (which prints "Hello World!" over UART). Also produced **zero serial output** after reset. This proved the problem was not BTP-specific — no firmware was running after reset.

3. **CPU register inspection:** Used OpenOCD to halt the MCU after `reset run` and read key registers:
   ```
   > halt
   > reg pc
   pc: 0x0F002DC4    ← ROM bootloader address!
   > reg sp
   sp: 0x200003C8
   ```
   The CPU was stuck in the **ROM bootloader** at address `0x0F002DC4`, deep inside the chip's built-in ROM. It never jumped to the application vector table at `0x00000000`.

4. **Flash verification:** Read the flash vector table using OpenOCD `mrw`:
   ```
   > mrw 0x00000000    → 0x200011E0  (Initial SP — valid SRAM address)
   > mrw 0x00000004    → 0x0000091C  (Reset handler — valid flash address)
   ```
   The vector table was correctly programmed. The CCFG (Customer Configuration) area also had `pAppVtor = 0x00000000` and a valid CRC. The flash contents were fine.

5. **Manual register jump:** Halted the CPU, manually set SP and PC from the vector table, then resumed:
   ```
   > halt
   > reg sp 0x200011E0
   > reg pc 0x0000091C
   > resume
   ```
   **The firmware ran immediately.** For hello_world, it printed "Hello World!" over serial. For the BTP tester, it sent the IUT Ready event: `00 80 FF 00 00`.

6. **Confirmation:** After 2 seconds of running, halted again and checked:
   ```
   > reg pc
   pc: 0x0000180D    ← user flash (BTP main loop)
   > reg xpsr
   xPSR: 0x01000000  ← Thread mode, no fault flags
   ```
   Firmware was running normally in Thread mode with no faults.

**Root Cause:** The CC2340R53's ROM bootloader does not reliably transfer control to the application after an OpenOCD `reset run` command. The ROM bootloader gets stuck in its own initialization/validation sequence and never jumps to the application entry point at the address specified in CCFG. This appears to be a chip-level issue specific to how the XDS110 debug probe interacts with the CC2340R53's boot sequence.

**Fix:** Replaced the `reset run` OpenOCD command with a manual vector-table-based reset sequence. Instead of relying on the ROM bootloader, we:

1. **Halt** the CPU
2. **Read** the initial Stack Pointer from flash address `0x00000000`
3. **Read** the initial Program Counter (reset handler) from flash address `0x00000004`
4. **Set** the SP and PC registers to those values
5. **Resume** execution

This is implemented in `lp_em_cc2340r53.py`:

```python
tcl_cmds = [
    'init',
    'halt',
    'set vt0 [mrw 0x00000000]',   # Read initial SP from vector table
    'set vt1 [mrw 0x00000004]',   # Read initial PC (reset handler)
    'reg sp $vt0',                 # Load stack pointer
    'reg pc $vt1',                 # Load program counter
    'resume',                      # Start execution
    'shutdown',
]
```

**Critical implementation detail:** Each TCL command **must** be passed as a separate `-c` flag to OpenOCD. When combined with semicolons in a single `-c "cmd1; cmd2; ..."` string, the CC2340R53 target does not reliably execute the sequence (the TCL variable substitution for `$vt0`/`$vt1` can fail silently). The separate `-c` approach was validated to work 100% of the time.

The command string is constructed so that Python's `shlex.split()` (used by `Board.reset()` in `__init__.py`) correctly preserves each quoted `-c "arg"` pair:

```python
# Produces:
# sudo /path/openocd -s /scripts -f board/cfg -c "init" -c "halt" -c "set vt0 [mrw 0x00000000]" ...
parts = [f'sudo {openocd_bin}', f'-s {openocd_scripts}', '-f board/ti_lp_em_cc2340r53.cfg']
for c in tcl_cmds:
    parts.append(f'-c "{c}"')
return ' '.join(parts)
```

**Result:** BTP IUT Ready event (`00 80 FF 00 00`) received reliably within ~1.5 seconds of reset. `GAP/BROB/BCST/BV-01-C` PASS.

---

### Problem 3: Missing Python Dependencies

**Symptom:** Various `ModuleNotFoundError` exceptions when launching `autoptsclient-zephyr.py`:
```
ModuleNotFoundError: No module named 'termcolor'
ModuleNotFoundError: No module named 'hid'
ModuleNotFoundError: No module named 'psutil'
ModuleNotFoundError: No module named 'pylink'
ModuleNotFoundError: No module named 'googleapiclient'
ModuleNotFoundError: No module named 'oauth2client'
ModuleNotFoundError: No module named 'xlsxwriter'
```

**Root Cause:** The auto-pts `setup.py` does not declare its runtime dependencies, so `pip install -e .` only installs the package structure without pulling in required third-party modules.

**Fix:**
```bash
pip3 install --break-system-packages \
  termcolor hid psutil pyserial pyyaml \
  pylink-square xlsxwriter gitpython \
  google-api-python-client oauth2client
```

**Note:** Some Windows-only modules (`pywintypes`, `win32com`, `winpexpect`) are also imported but only on the server side. They are not needed on the Linux/WSL client.

---

### Problem 4: USB Serial Port Not Appearing (`/dev/ttyACM*`)

**Symptom:** No `/dev/ttyACM*` devices visible in WSL after plugging in the board.

**Root Cause:** The `cdc_acm` kernel module was not loaded, so the USB CDC-ACM class driver couldn't claim the XDS110's serial interfaces.

**Fix:**
```bash
sudo modprobe cdc_acm
```

Also ensure the USB device is passed through to WSL (if applicable):
```powershell
# From Windows PowerShell (admin):
usbipd list         # Find the XDS110 bus ID
usbipd bind --busid <ID>
usbipd attach --wsl --busid <ID>
```

---

### Problem 5: Identifying the Correct Serial Port

**Symptom:** Two serial ports appear (`/dev/ttyACM0` and `/dev/ttyACM1`). It was unclear which one carries UART data for BTP.

**Investigation:** The XDS110 debug probe exposes multiple USB interfaces:
- **Interface 0** → `/dev/ttyACM0` — Main UART (connected to MCU's uart0, DIO20/22)
- **Interface 3** → `/dev/ttyACM1` — Backchannel UART (separate debug channel, not used)

**Fix:** Always use `/dev/ttyACM0` (USB interface 0) for the `-t` flag. Verified by receiving BTP IUT Ready event on this port.

---

## 12. Architecture Diagram

### Reset Flow (per test case)

```
AutoPTS Client
    │
    ├─► Board.reset()
    │       │
    │       └─► subprocess.Popen(shlex.split(reset_cmd))
    │               │
    │               └─► OpenOCD
    │                     ├── init (connect to XDS110)
    │                     ├── halt (stop CPU)
    │                     ├── mrw 0x0 → read SP from vector table
    │                     ├── mrw 0x4 → read PC from vector table
    │                     ├── reg sp $vt0 (set stack pointer)
    │                     ├── reg pc $vt1 (set program counter)
    │                     ├── resume (start firmware)
    │                     └── shutdown
    │
    ├─► flush_serial()
    │
    ├─► socat bridges /dev/ttyACM0 ↔ /tmp/bt-stack-tester
    │
    ├─► btp_socket.accept() on /tmp/bt-stack-tester
    │
    ├─► wait_iut_ready_event() ← receives 00 80 FF 00 00
    │
    └─► Run test case (exchange BTP commands with firmware)
```

### BTP IUT Ready Event Format

```
Offset  Field      Value      Meaning
──────  ─────      ─────      ───────
0       Service    0x00       CORE service
1       Opcode     0x80       IUT_READY event
2       Index      0xFF       NONE (broadcast)
3-4     Length     0x0000     No payload
```

---

## 13. File Reference

### AutoPTS Board Integration

| File | Purpose |
|------|---------|
| `auto-pts/autopts/ptsprojects/boards/lp_em_cc2340r53.py` | Board reset command, build-and-flash logic |
| `auto-pts/autopts/ptsprojects/boards/__init__.py` | `Board` class — calls `reset_cmd()` via `shlex.split()` + `subprocess.Popen()` |
| `auto-pts/autopts/ptsprojects/iutctl.py` | IUT control — TTY mode, socat management, BTP socket |
| `auto-pts/autoptsclient-zephyr.py` | Main client entry point |

### Zephyr BTP Tester

| File | Purpose |
|------|---------|
| `zephyr/tests/bluetooth/tester/prj.conf` | Main Kconfig for BTP tester |
| `zephyr/tests/bluetooth/tester/boards/lp_em_cc2340r53.overlay` | DT overlay: assigns uart0 to uart-pipe |
| `zephyr/tests/bluetooth/tester/boards/lp_em_cc2340r53.conf` | Board Kconfig: disables PM and console |
| `zephyr/tests/bluetooth/tester/src/btp.c` | BTP core — sends IUT Ready event at startup |

### OpenOCD

| File | Purpose |
|------|---------|
| `ti-openocd/tcl/board/ti_lp_em_cc2340r53.cfg` | Board config for OpenOCD (XDS110 + CC2340R53 target) |

---

## Appendix A: First-Time Installation Checklist

This checklist covers the one-time setup. Once completed, use [Appendix B](#appendix-b-daily-startup-procedure) for daily startup.

### Windows Side

```
[ ] PTS (Profile Tuning Suite) installed from Bluetooth SIG website
[ ] Teledyne LeCroy firmware updated (PTS Firmware Upgrade tool)
[ ] PTS dongle connected and detected in PTS software
[ ] Sniffer configured in PTS: File → Application Settings → Sniffer
[ ] Python 3.10+ installed ("Add Python to PATH" checked)
[ ] auto-pts cloned: git clone https://github.com/intel/auto-pts.git
[ ] Server deps installed: py -m pip install pywin32 wmi pyserial
[ ] Server requirements: py -m pip install -r autoptsserver_requirements.txt
[ ] auto-pts installed: py -m pip install -e .
[ ] Verify: py -m pip show auto-pts
```

### WSL / Linux Side

```
[ ] Zephyr workspace set up (west init + west update)
[ ] Zephyr SDK installed (~/zephyr-sdk-0.16.8)
[ ] TI OpenOCD built/installed (~/ti-openocd or TI_OPENOCD_INSTALL_DIR)
[ ] socat installed (sudo apt install socat)
[ ] Python venv created and activated
[ ] Twister requirements installed (scripts/requirements-*.txt)
[ ] auto-pts cloned: git clone https://github.com/intel/auto-pts.git ~/auto-pts
[ ] Client deps installed: pip install -r autoptsclient_requirements.txt
[ ] Extra deps installed: pip install termcolor hid psutil pylink-square ...
[ ] auto-pts installed: pip install -e .
[ ] Board Python file in place: autopts/ptsprojects/boards/lp_em_cc2340r53.py
[ ] BTP tester firmware built: west build -p auto -b lp_em_cc2340r53/cc2340r53
[ ] BTP tester firmware flashed: west flash
```

### Smoke Test

```
[ ] PTS server running on Windows (py autoptsserver.py -S 65000 -C 65001)
[ ] Can ping Windows host from WSL (ping <WINDOWS_IP>)
[ ] Run: python3 autoptsclient-zephyr.py ... -c GAP/BROB/BCST/BV-01-C
[ ] Verify: PASS
```

---

## Appendix B: Daily Startup Procedure

Every time you power on your machine and connect the board, follow these steps in order.

### Step 1: Connect Hardware (Windows)

1. Plug the LP-EM-CC2340R53 board into USB.
2. Open **PowerShell** (as Administrator if needed) and attach the USB device to WSL:

```powershell
usbipd attach --wsl --busid 2-2
```

> **Note:** The bus ID (`2-2`) may change if you use a different USB port. If the command fails, run `usbipd list` first to find the current bus ID of the XDS110 device.

### Step 2: Enter the Development Environment (WSL)

1. Open your WSL / Ubuntu terminal.

2. Navigate to your workspace and activate the Python virtual environment:

```bash
cd ~/ti-workspace/zephyr
source ~/ti-workspace/.venv/bin/activate
```

> You should see `(.venv)` at the beginning of your terminal prompt. Without this, `west` and other tools will not be available.

3. *(Optional)* Open VS Code connected to the WSL filesystem:

```bash
code .
```

This launches VS Code on Windows but connected to the Linux files via the WSL extension.

### Step 3: Verify the Serial Port

```bash
ls /dev/ttyACM*
# Expected: /dev/ttyACM0  /dev/ttyACM1

# If the ports don't appear:
sudo modprobe cdc_acm

# Grant access:
sudo chmod 666 /dev/ttyACM0
```

### Step 4: Build & Flash (if firmware changed)

If you modified the BTP tester firmware or need to reflash:

```bash
cd ~/ti-workspace/zephyr
west build -b lp_em_cc2340r53/cc2340r53 tests/bluetooth/tester/ -p always
west flash
```

### Step 5: Start the PTS Server (Windows)

On the Windows host, open CMD or PowerShell:

```cmd
cd auto-pts
py autoptsserver.py -S 65000 -C 65001
```

Leave this terminal open.

### Step 6: Run Tests (WSL)

```bash
cd ~/auto-pts

python3 ./autoptsclient-zephyr.py zephyr-master \
  "Z:\home\david\ti-workspace\zephyr\build\zephyr\zephyr.elf" \
  -t /dev/ttyACM0 -b lp_em_cc2340r53 \
  -i 172.21.128.1 -S 65000 -C 65001 \
  -l $(hostname -I | awk '{print $1}') \
  --iut-mode tty --tty-baudrate 115200 \
  -d -c GAP
```

> Adjust the `-i` IP address if your Windows host IP is different. Run `ipconfig` on Windows or `ip route show | grep default | awk '{print $3}'` in WSL to find it.

### Quick Reference: Daily Commands Summary

```bash
# --- WSL ---
cd ~/ti-workspace/zephyr
source ~/ti-workspace/.venv/bin/activate
sudo chmod 666 /dev/ttyACM0

# (If rebuild needed)
west build -b lp_em_cc2340r53/cc2340r53 tests/bluetooth/tester/ -p always
west flash

# Run tests
cd ~/auto-pts
python3 ./autoptsclient-zephyr.py zephyr-master \
  "Z:\home\david\ti-workspace\zephyr\build\zephyr\zephyr.elf" \
  -t /dev/ttyACM0 -b lp_em_cc2340r53 \
  -i 172.21.128.1 -S 65000 -C 65001 \
  -l $(hostname -I | awk '{print $1}') \
  --iut-mode tty --tty-baudrate 115200 \
  -d -c GAP
```

```powershell
# --- Windows (PowerShell) ---
usbipd attach --wsl --busid 2-2
cd auto-pts
py autoptsserver.py -S 65000 -C 65001
```
