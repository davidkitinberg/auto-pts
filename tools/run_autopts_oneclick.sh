#!/usr/bin/env bash
set -euo pipefail

# One-click AutoPTS orchestrator for WSL + Windows.
#
# Example:
#   tools/run_autopts_oneclick.sh \
#     --workspace-file "C:\\Users\\USER\\Documents\\Profile Tuning Suite\\PTS_PROJECT\\PTS_PROJECT.pqw6"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="$(command -v python3 2>/dev/null || true)"
if [[ -z "${VIRTUAL_ENV:-}" && -x "${REPO_ROOT}/../.venv/bin/python3" ]]; then
    PYTHON_BIN="${REPO_ROOT}/../.venv/bin/python3"
fi

# Defaults tuned to the user's existing workflow.
TESTS=""
PTS_IP=""
WORKSPACE="zephyr-master"
WORKSPACE_FILE=""
WORKSPACE_RESOLVED=""
ELF_PATH=""
TTY_DEV="auto"
TTY_EXPLICIT=0
BOARD="lp_em_cc2340r53"
PTS_SRV_PORT="65000"
PTS_CLI_PORT="65001"
PTS_DONGLE=""
TTY_BAUD="115200"
CLIENT_LOCAL_IP=""
USB_ID="0451:bef3"
USB_BUSID=""
USB_INTERFACE="00"
USB_DISCOVERY_TIMEOUT="10"
USB_ATTACH_TIMEOUT="20"

ENABLE_USB_SETUP=1
START_WINDOWS_SERVER=1
RUN_REPORT=1
OPEN_REPORT=1
VERBOSE=0
DRY_RUN=0

# Windows processes created by this invocation. Existing processes are never
# adopted or stopped by the wrapper.
WINDOWS_SERVER_PID=""
WINDOWS_SERVER_OWNED=0
WINDOWS_FTS_PIDS_BEFORE=""
WINDOWS_FTS_PIDS_STARTED=""

usage() {
    cat <<'EOF'
Usage:
    tools/run_autopts_oneclick.sh [selection-options] [options]

Selection options:
    --workspace-file <value>    Path to a PTS workspace (.pqw6). If this is a Linux path,
                                                            it is converted to Windows path before launching the client.
    --workspace <value>         Workspace name/path passed to client (default: zephyr-master)
    --tests <value>             Test(s) to run (e.g. GAP/BROB/BCST or GAP).
                                                            Can be repeated or comma-separated.
                                                            If omitted, AutoPTS runs enabled tests from workspace.

Options:
  --elf <value>              Optional kernel image (not needed in TTY mode)
  --pts-ip <value>           Windows host IP (default: auto-detected)
  --tty <value>              TTY device (default: auto-detected)
  --board <value>            Board name (default: lp_em_cc2340r53)
  --usb-id <VID:PID>         Windows USB device to attach (default: 0451:bef3, XDS110)
  --usb-busid <value>        Select one device when multiple matching probes are connected
  --usb-interface <hex>      CDC interface used for BTP (default: 00)
  --srv-port <value>         PTS server port (default: 65000)
  --cli-port <value>         PTS callback/client port (default: 65001)
    --pts-dongle <value>       PTS dongle selector passed to server (e.g. COM5)
  --tty-baud <value>         TTY baudrate (default: 115200)
  --local-ip <value>         Local WSL IP (default: auto-detected)

  --no-usb-setup             Skip usbipd, driver, and permission setup
  --no-server-launch         Do not auto-launch Windows autoptsserver.py
  --no-report                Skip report generation
  --no-open                  Generate report but do not open in browser

  --dry-run                  Print actions but do not execute
  --verbose                  Print commands as they execute
  -h, --help                 Show this help

Notes:
- Run from any location; script auto-resolves repo root.
- On WSL, the matching USB probe is attached with usbipd automatically and
  its BTP serial interface is selected without assuming /dev/ttyACM0.
- `usbipd bind` is a one-time Administrator action. If the device is not yet
  shared, this command prints the exact PowerShell command to run.
- `--workspace-file` takes precedence over `--workspace` when both are provided.
- A Windows AutoPTS server launched by this command is stopped automatically
  after the client and report finish, including on errors or Ctrl-C.
- If a server is already listening on `--srv-port`, it is reused and left running.
  Use `--no-server-launch` when managing the Windows server manually.
- A persistent udev rule is recommended for non-interactive serial permissions.
EOF
}

log()  { printf '[oneclick] %s\n' "$*"; }
warn() { printf '[oneclick][warn] %s\n' "$*" >&2; }
err()  { printf '[oneclick][error] %s\n' "$*" >&2; }

run_cmd() {
    if [[ "${DRY_RUN}" -eq 1 ]]; then
        log "DRY-RUN: $*"
        return 0
    fi
    if [[ "${VERBOSE}" -eq 1 ]]; then
        log "EXEC: $*"
    fi
    "$@"
}

require_cmd() {
    local c="$1"
    command -v "$c" >/dev/null 2>&1 || {
        err "Missing required command: ${c}"
        exit 1
    }
}

is_wsl() {
    grep -qiE '(microsoft|wsl)' /proc/version 2>/dev/null
}

check_wsl_prereqs() {
    is_wsl || {
        err "This script is intended for WSL."
        exit 1
    }

    [[ -x "${PYTHON_BIN}" ]] || {
        err "Python 3 was not found."
        exit 1
    }
    require_cmd powershell.exe
    require_cmd explorer.exe
    require_cmd taskkill.exe
    require_cmd wslpath
    if [[ "${ENABLE_USB_SETUP}" -eq 1 ]]; then
        require_cmd usbipd.exe
    fi

    [[ -f "${REPO_ROOT}/autoptsclient-zephyr.py" ]] || {
        err "autoptsclient-zephyr.py not found in ${REPO_ROOT}"
        exit 1
    }
    [[ -f "${REPO_ROOT}/autoptsserver.py" ]] || {
        err "autoptsserver.py not found in ${REPO_ROOT}"
        exit 1
    }
    [[ -f "${REPO_ROOT}/tools/autopts_report.py" ]] || {
        err "tools/autopts_report.py not found"
        exit 1
    }

    if [[ -z "${VIRTUAL_ENV:-}" && "${PYTHON_BIN}" == "${REPO_ROOT}/../.venv/bin/python3" ]]; then
        log "Using repository virtual environment: ${REPO_ROOT}/../.venv"
    elif [[ -z "${VIRTUAL_ENV:-}" ]]; then
        warn "Python venv is not active and no repository .venv was found."
    fi
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --tests)
                if [[ -z "${TESTS}" ]]; then
                    TESTS="$2"
                else
                    TESTS+=" ,$2"
                fi
                shift 2
                ;;
            --pts-ip) PTS_IP="$2"; shift 2 ;;
            --workspace) WORKSPACE="$2"; shift 2 ;;
            --workspace-file) WORKSPACE_FILE="$2"; shift 2 ;;
            --elf) ELF_PATH="$2"; shift 2 ;;
            --tty) TTY_DEV="$2"; TTY_EXPLICIT=1; shift 2 ;;
            --board) BOARD="$2"; shift 2 ;;
            --usb-id) USB_ID="${2,,}"; shift 2 ;;
            --usb-busid) USB_BUSID="$2"; shift 2 ;;
            --usb-interface) USB_INTERFACE="${2,,}"; shift 2 ;;
            --srv-port) PTS_SRV_PORT="$2"; shift 2 ;;
            --cli-port) PTS_CLI_PORT="$2"; shift 2 ;;
            --pts-dongle) PTS_DONGLE="$2"; shift 2 ;;
            --tty-baud) TTY_BAUD="$2"; shift 2 ;;
            --local-ip) CLIENT_LOCAL_IP="$2"; shift 2 ;;

            --no-usb-setup) ENABLE_USB_SETUP=0; shift ;;
            --no-server-launch) START_WINDOWS_SERVER=0; shift ;;
            --no-report) RUN_REPORT=0; shift ;;
            --no-open) OPEN_REPORT=0; shift ;;

            --dry-run) DRY_RUN=1; shift ;;
            --verbose) VERBOSE=1; shift ;;
            -h|--help) usage; exit 0 ;;
            *) err "Unknown argument: $1"; usage; exit 2 ;;
        esac
    done

    [[ "${USB_ID}" =~ ^[[:xdigit:]]{4}:[[:xdigit:]]{4}$ ]] || {
        err "--usb-id must use VID:PID format (for example 0451:bef3)."
        exit 2
    }

    if [[ -n "${WORKSPACE_FILE}" && "${WORKSPACE}" != "zephyr-master" ]]; then
        warn "Both --workspace-file and --workspace were provided; using --workspace-file."
    fi

    if [[ -z "${TESTS}" ]]; then
        warn "No --tests provided. Client will run enabled tests from selected workspace."
    fi

}

resolve_workspace() {
    local ws
    if [[ -n "${WORKSPACE_FILE}" ]]; then
        ws="${WORKSPACE_FILE}"
    else
        ws="${WORKSPACE}"
    fi

    if [[ "${ws,,}" == *.pqw6 ]]; then
        # If workspace path points to local Linux filesystem, convert it
        # so Windows autoptsserver can open it.
        if [[ "${ws}" == /* || "${ws}" == ./* || "${ws}" == ../* ]]; then
            if [[ -f "${ws}" ]]; then
                WORKSPACE_RESOLVED="$(wslpath -w "${ws}")"
            else
                if [[ "${DRY_RUN}" -eq 1 ]]; then
                    warn "Workspace file not found (dry-run): ${ws}"
                    WORKSPACE_RESOLVED="${ws}"
                else
                    err "Workspace file not found: ${ws}"
                    exit 1
                fi
            fi
        else
            WORKSPACE_RESOLVED="${ws}"
        fi
    else
        WORKSPACE_RESOLVED="${ws}"
    fi
}

resolve_local_ip() {
    if [[ -n "${CLIENT_LOCAL_IP}" ]]; then
        return
    fi
    CLIENT_LOCAL_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
    [[ -n "${CLIENT_LOCAL_IP}" ]] || {
        err "Unable to detect local IP. Use --local-ip explicitly."
        exit 1
    }
}

resolve_pts_ip() {
    if [[ -n "${PTS_IP}" ]]; then
        return
    fi

    # In normal WSL2 networking the default gateway is the Windows host. The
    # resolv.conf fallback covers WSL configurations without the `ip` command.
    if command -v ip >/dev/null 2>&1; then
        PTS_IP="$(ip route show default 2>/dev/null | awk 'NR == 1 { print $3 }')"
    fi
    if [[ -z "${PTS_IP}" ]]; then
        PTS_IP="$(awk '/^nameserver[[:space:]]+/ { print $2; exit }' /etc/resolv.conf 2>/dev/null || true)"
    fi
    [[ -n "${PTS_IP}" ]] || {
        err "Unable to detect the Windows host IP. Use --pts-ip explicitly."
        exit 1
    }
}

tcp_port_open() {
    local host="$1"
    local port="$2"

    "${PYTHON_BIN}" - "$host" "$port" <<'PY'
import socket
import sys

host = sys.argv[1]
port = int(sys.argv[2])
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(1.5)
try:
    s.connect((host, port))
except OSError:
    sys.exit(1)
finally:
    s.close()
PY
}

windows_process_ids() {
    local process_name="$1"
    local ps
    ps="(Get-Process -Name '${process_name}' -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id) -join ','"
    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ps" 2>/dev/null \
        | tr -d '\r\n'
}

capture_started_teledyne_pids() {
    local before_ps ps
    before_ps="${WINDOWS_FTS_PIDS_BEFORE}"
    ps="\$before = @(${before_ps}); (Get-Process -Name 'Fts' -ErrorAction SilentlyContinue | Where-Object { \$_.Id -notin \$before } | Select-Object -ExpandProperty Id) -join ','"
    WINDOWS_FTS_PIDS_STARTED="$(powershell.exe -NoProfile -ExecutionPolicy Bypass \
        -Command "$ps" 2>/dev/null | tr -d '\r\n')"
}

cleanup_windows_autopts_server() {
    local exit_code=$?
    local pid

    if [[ "${WINDOWS_SERVER_OWNED}" -ne 1 ]]; then
        return "${exit_code}"
    fi

    # Prevent a second cleanup if a caller invokes this function explicitly.
    WINDOWS_SERVER_OWNED=0
    log "Stopping Windows AutoPTS server started by this command..."

    # Ask PTS to release its COM resources first. The taskkill fallback below
    # guarantees that the console/server process tree does not remain behind.
    "${PYTHON_BIN}" - "${PTS_IP}" "${PTS_SRV_PORT}" <<'PY' >/dev/null 2>&1 || true
import socket
import sys
import xmlrpc.client

socket.setdefaulttimeout(5)
proxy = xmlrpc.client.ServerProxy(
    f"http://{sys.argv[1]}:{sys.argv[2]}/", allow_none=True)
proxy.stop_pts()
PY

    # The XML-RPC port can become reachable slightly before PTS launches Fts,
    # so refresh the owned Teledyne PID set at cleanup time as well.
    capture_started_teledyne_pids

    if [[ -n "${WINDOWS_SERVER_PID}" ]]; then
        taskkill.exe /PID "${WINDOWS_SERVER_PID}" /T /F >/dev/null 2>&1 || true
    fi

    # PTS may launch Teledyne's Bluetooth Protocol Viewer as a separate process
    # rather than as a child of cmd.exe. Stop only Fts instances absent from the
    # pre-launch snapshot taken by this invocation.
    for pid in ${WINDOWS_FTS_PIDS_STARTED//,/ }; do
        [[ "${pid}" =~ ^[0-9]+$ ]] || continue
        taskkill.exe /PID "${pid}" /T /F >/dev/null 2>&1 || true
    done

    log "Windows AutoPTS server cleanup complete."
    return "${exit_code}"
}

preflight_checks() {
    # Kernel image path can be Windows-style; only check Linux paths.
    if [[ "${ELF_PATH}" == /* || "${ELF_PATH}" == ./* || "${ELF_PATH}" == ../* ]]; then
        if [[ ! -f "${ELF_PATH}" ]]; then
            if [[ "${DRY_RUN}" -eq 1 ]]; then
                warn "ELF file not found (dry-run): ${ELF_PATH}"
            else
                err "ELF file not found: ${ELF_PATH}"
                exit 1
            fi
        fi
    fi

}

select_usb_device() {
    local usb_list matches="" line_count selected_line deadline
    deadline=$((SECONDS + USB_DISCOVERY_TIMEOUT))

    while (( SECONDS <= deadline )); do
        usb_list="$(usbipd.exe list 2>/dev/null | tr -d '\r')" || {
            err "Could not query usbipd on Windows. Install usbipd-win or use --no-usb-setup."
            exit 1
        }

        if [[ -n "${USB_BUSID}" ]]; then
            matches="$(awk -v bus="${USB_BUSID}" -v id="${USB_ID}" \
                'tolower($1) == tolower(bus) && tolower($2) == tolower(id)' <<< "${usb_list}")"
        else
            matches="$(awk -v id="${USB_ID}" \
                'tolower($2) == tolower(id)' <<< "${usb_list}")"
        fi

        [[ -n "${matches}" || "${DRY_RUN}" -eq 1 ]] && break
        sleep 1
    done

    line_count="$(sed '/^[[:space:]]*$/d' <<< "${matches}" | wc -l)"
    if [[ "${line_count}" -eq 0 ]]; then
        err "No connected Windows USB device matches ${USB_ID}."
        err "Connect the board and verify it with: usbipd list"
        exit 1
    fi
    if [[ "${line_count}" -gt 1 ]]; then
        err "Multiple USB devices match ${USB_ID}. Select one with --usb-busid <BUSID>."
        awk '{ print "  " $1 "  " $2 }' <<< "${matches}" >&2
        exit 1
    fi

    selected_line="$(sed -n '1p' <<< "${matches}")"
    USB_BUSID="$(awk '{ print $1 }' <<< "${selected_line}")"

    case "${selected_line}" in
        *"Not shared") USB_STATE="not-shared" ;;
        *"Shared") USB_STATE="shared" ;;
        *"Attached"*) USB_STATE="attached" ;;
        *)
            err "Unrecognized usbipd state for BUSID ${USB_BUSID}: ${selected_line}"
            exit 1
            ;;
    esac
}

attach_usb_to_wsl() {
    select_usb_device

    case "${USB_STATE}" in
        attached)
            log "USB ${USB_ID} at BUSID ${USB_BUSID} is already attached to WSL."
            ;;
        shared)
            log "Attaching USB ${USB_ID} at BUSID ${USB_BUSID} to WSL..."
            if ! run_cmd usbipd.exe attach --wsl --busid "${USB_BUSID}"; then
                err "usbipd could not attach BUSID ${USB_BUSID} to WSL."
                exit 1
            fi
            ;;
        not-shared)
            err "USB ${USB_ID} at BUSID ${USB_BUSID} has not been shared with WSL yet."
            err "Run this once in an Administrator PowerShell, then retry:"
            err "  usbipd bind --busid ${USB_BUSID}"
            exit 1
            ;;
    esac
}

tty_usb_attributes() {
    local tty_path="$1" node vid="" pid="" interface=""
    node="$(readlink -f "/sys/class/tty/$(basename "${tty_path}")" 2>/dev/null)" || return 1

    while [[ -n "${node}" && "${node}" != "/" ]]; do
        if [[ -z "${vid}" && -r "${node}/idVendor" && -r "${node}/idProduct" ]]; then
            vid="$(<"${node}/idVendor")"
            pid="$(<"${node}/idProduct")"
        fi
        if [[ -z "${interface}" && -r "${node}/bInterfaceNumber" ]]; then
            interface="$(<"${node}/bInterfaceNumber")"
        fi
        node="$(dirname "${node}")"
    done

    printf '%s:%s %s\n' "${vid,,}" "${pid,,}" "${interface,,}"
}

matching_ttys() {
    local tty attrs id interface
    shopt -s nullglob
    for tty in /dev/ttyACM*; do
        attrs="$(tty_usb_attributes "${tty}" 2>/dev/null || true)"
        id="${attrs%% *}"
        interface="${attrs#* }"
        if [[ "${id}" == "${USB_ID}" && "${interface}" == "${USB_INTERFACE}" ]]; then
            printf '%s\n' "${tty}"
        fi
    done
    shopt -u nullglob
}

resolve_tty() {
    local deadline candidates count

    if [[ "${TTY_EXPLICIT}" -eq 1 ]]; then
        if [[ "${DRY_RUN}" -eq 0 && ! -e "${TTY_DEV}" ]]; then
            err "Requested TTY does not exist after USB setup: ${TTY_DEV}"
            exit 1
        fi
        log "Using explicitly selected TTY: ${TTY_DEV}"
        return
    fi

    if [[ "${DRY_RUN}" -eq 1 ]]; then
        candidates="$(matching_ttys)"
        TTY_DEV="$(sed -n '1p' <<< "${candidates}")"
        TTY_DEV="${TTY_DEV:-/dev/ttyACM0}"
        log "DRY-RUN: would use detected BTP TTY ${TTY_DEV}"
        return
    fi

    deadline=$((SECONDS + USB_ATTACH_TIMEOUT))
    while (( SECONDS <= deadline )); do
        candidates="$(matching_ttys)"
        count="$(sed '/^[[:space:]]*$/d' <<< "${candidates}" | wc -l)"
        if [[ "${count}" -eq 1 ]]; then
            TTY_DEV="$(sed -n '1p' <<< "${candidates}")"
            log "Detected BTP TTY: ${TTY_DEV} (USB interface ${USB_INTERFACE})"
            return
        fi
        if [[ "${count}" -gt 1 ]]; then
            err "Multiple matching BTP serial ports were found. Select one with --tty."
            sed 's/^/  /' <<< "${candidates}" >&2
            exit 1
        fi
        sleep 1
    done

    err "No TTY for ${USB_ID}, interface ${USB_INTERFACE}, appeared within ${USB_ATTACH_TIMEOUT}s."
    err "Inspect /dev/ttyACM* or override with --tty and --usb-interface."
    exit 1
}

usb_setup() {
    [[ "${ENABLE_USB_SETUP}" -eq 1 ]] || {
        log "Skipping USB setup (--no-usb-setup)."
        resolve_tty
        return 0
    }

    log "Preparing USB serial access for ${USB_ID}..."

    if [[ ! -d /sys/module/cdc_acm ]]; then
        if ! run_cmd sudo -n modprobe cdc_acm; then
            warn "Non-interactive sudo unavailable for modprobe; trying interactive sudo."
            if ! run_cmd sudo modprobe cdc_acm; then
                err "Failed to load cdc_acm."
                exit 1
            fi
        fi
    fi

    attach_usb_to_wsl
    resolve_tty

    if [[ "${DRY_RUN}" -eq 0 && ( ! -r "${TTY_DEV}" || ! -w "${TTY_DEV}" ) ]]; then
        warn "${TTY_DEV} is not accessible to the current user; applying temporary permissions."
        if ! run_cmd sudo -n chmod a+rw "${TTY_DEV}"; then
            warn "Non-interactive sudo unavailable for chmod; trying interactive sudo."
            if ! run_cmd sudo chmod a+rw "${TTY_DEV}"; then
                err "Failed to set permissions on ${TTY_DEV}."
                err "Install the udev rule documented in docs/adding_a_board.md."
                exit 1
            fi
        fi
    fi

    if [[ "${DRY_RUN}" -eq 0 ]]; then
        [[ -r "${TTY_DEV}" && -w "${TTY_DEV}" ]] || {
            err "TTY is still not readable/writable after setup: ${TTY_DEV}"
            exit 1
        }
    fi
}

launch_windows_autopts_server() {
    [[ "${START_WINDOWS_SERVER}" -eq 1 ]] || {
        log "Skipping Windows autoptsserver launch (--no-server-launch)."
        return 0
    }

    if [[ "${DRY_RUN}" -eq 0 ]] && tcp_port_open "${PTS_IP}" "${PTS_SRV_PORT}"; then
        log "Reusing existing AutoPTS server at ${PTS_IP}:${PTS_SRV_PORT}; it will not be stopped."
        return 0
    fi

    local win_server_script
    win_server_script="$(wslpath -w "${REPO_ROOT}/autoptsserver.py")"

    log "Launching Windows AutoPTS server in a new CMD window..."
    local cmd ps
    cmd="py \"${win_server_script}\" -S ${PTS_SRV_PORT}"
    if [[ -n "${PTS_DONGLE}" ]]; then
        cmd+=" --dongle ${PTS_DONGLE}"
    fi
    # Escape single-quotes for PowerShell single-quoted string literal.
    cmd="${cmd//\'/\'\'}"
    # /c closes the console when Python exits. The PID is retained so the EXIT
    # trap can stop the exact process tree created by this invocation.
    ps="\$p = Start-Process -FilePath 'cmd.exe' -WorkingDirectory \$env:USERPROFILE -ArgumentList '/c', '${cmd}' -PassThru; [Console]::Out.WriteLine(\$p.Id)"

    if [[ "${DRY_RUN}" -eq 1 ]]; then
        log "DRY-RUN: powershell.exe -NoProfile -ExecutionPolicy Bypass -Command <launch owned AutoPTS server>"
        return 0
    fi

    WINDOWS_FTS_PIDS_BEFORE="$(windows_process_ids Fts)"
    if [[ "${VERBOSE}" -eq 1 ]]; then
        log "EXEC: powershell.exe -NoProfile -ExecutionPolicy Bypass -Command <launch owned AutoPTS server>"
    fi
    WINDOWS_SERVER_PID="$(powershell.exe -NoProfile -ExecutionPolicy Bypass \
        -Command "$ps" | tr -d '\r' | tail -n 1)"
    [[ "${WINDOWS_SERVER_PID}" =~ ^[0-9]+$ ]] || {
        err "Failed to capture the Windows AutoPTS server PID."
        exit 1
    }
    WINDOWS_SERVER_OWNED=1
    trap cleanup_windows_autopts_server EXIT

    # Best-effort wait for server port.
    if [[ "${DRY_RUN}" -eq 0 ]]; then
        local ok=0
        for _ in $(seq 1 25); do
            if "${PYTHON_BIN}" - <<PY
import socket, sys
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(1.0)
try:
    s.connect((${PTS_IP@Q}, int(${PTS_SRV_PORT@Q})))
except Exception:
    sys.exit(1)
finally:
    s.close()
sys.exit(0)
PY
            then
                ok=1
                break
            fi
            sleep 1
        done
        if [[ "$ok" -eq 0 ]]; then
            warn "AutoPTS server port ${PTS_IP}:${PTS_SRV_PORT} is not reachable yet."
            warn "If PTS app is not open/ready, client may fail."
        else
            # Fts.exe is normally spawned while PTS initializes, before the
            # XML-RPC port becomes reachable.
            sleep 1
            capture_started_teledyne_pids
        fi
    fi
}

check_pts_gui_ready() {
    # Best-effort check only. Process names vary between PTS versions.
    local ps
    ps="\$p = Get-Process | Where-Object { \$_.ProcessName -match 'PTS|PTSControl|Bluetooth' }; if (\$p) { exit 0 } else { exit 1 }"

    if [[ "${DRY_RUN}" -eq 1 ]]; then
        log "DRY-RUN: powershell.exe -NoProfile -ExecutionPolicy Bypass -Command <PTS process probe>"
        return 0
    fi

    if powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ps" >/dev/null 2>&1; then
        log "PTS GUI process appears to be running (best-effort check)."
    else
        warn "Could not detect a PTS GUI process on Windows."
        warn "Open PTS and ensure the dongle is paired before continuing if client fails."
    fi
}

build_client_cmd() {
    local cmd
    cmd="cd ${REPO_ROOT@Q} && "

    cmd+="${PYTHON_BIN@Q} ./autoptsclient-zephyr.py ${WORKSPACE_RESOLVED@Q} "
    if [[ -n "${ELF_PATH}" ]]; then
        cmd+="${ELF_PATH@Q} "
    fi
    cmd+="-t ${TTY_DEV@Q} -b ${BOARD@Q} "
    cmd+="-i ${PTS_IP@Q} -S ${PTS_SRV_PORT@Q} -C ${PTS_CLI_PORT@Q} "
    cmd+="-l ${CLIENT_LOCAL_IP@Q} "
    cmd+="--iut-mode tty --tty-baudrate ${TTY_BAUD@Q} "
    cmd+="-d "

    if [[ -z "${TESTS}" ]]; then
        printf '%s' "$cmd"
        return
    fi

    # TESTS may contain comma-separated values and/or repeated --tests values.
    local tc tc_clean
    IFS=',' read -r -a _tests_arr <<< "${TESTS}"
    for tc in "${_tests_arr[@]}"; do
        # Trim surrounding whitespace
        tc_clean="$(echo "${tc}" | xargs)"
        [[ -n "${tc_clean}" ]] || continue
        cmd+="-c ${tc_clean@Q} "
    done

    printf '%s' "$cmd"
}

latest_run_root() {
    ls -1dt "${REPO_ROOT}"/logs/cli_port_*/* 2>/dev/null | head -1 || true
}

generate_report() {
    [[ "${RUN_REPORT}" -eq 1 ]] || {
        log "Skipping report generation (--no-report)."
        return 0
    }

    local run_root="$1"
    if [[ -z "${run_root}" || ! -d "${run_root}" ]]; then
        warn "Could not determine run root; skipping report generation."
        return 0
    fi

    local report_path="${run_root}/report.html"
    run_cmd "${PYTHON_BIN}" "${REPO_ROOT}/tools/autopts_report.py" --run-root "${run_root}"

    if [[ "${OPEN_REPORT}" -eq 1 ]]; then
        if ! run_cmd explorer.exe "$(wslpath -w "${report_path}")"; then
            warn "Could not open the report automatically: ${report_path}"
        fi
    fi

    log "Run root: ${run_root}"
    log "Report: ${report_path}"
}

main() {
    parse_args "$@"
    check_wsl_prereqs
    resolve_workspace
    resolve_local_ip
    resolve_pts_ip
    preflight_checks
    usb_setup

    log "Resolved config:"
    if [[ -n "${TESTS}" ]]; then
        log "  tests=${TESTS}"
    else
        log "  tests=<workspace-enabled>"
    fi
    log "  pts_ip=${PTS_IP} srv_port=${PTS_SRV_PORT} cli_port=${PTS_CLI_PORT}"
    if [[ -n "${PTS_DONGLE}" ]]; then
        log "  pts_dongle=${PTS_DONGLE}"
    fi
    log "  tty=${TTY_DEV} board=${BOARD} baud=${TTY_BAUD}"
    log "  workspace=${WORKSPACE_RESOLVED}"
    log "  elf=${ELF_PATH:-<not-used-in-tty-mode>}"
    log "  local_ip=${CLIENT_LOCAL_IP}"
    launch_windows_autopts_server
    check_pts_gui_ready

    local before_root after_root client_cmd
    before_root="$(latest_run_root)"
    client_cmd="$(build_client_cmd)"

    log "Starting AutoPTS client..."
    if [[ "${DRY_RUN}" -eq 1 ]]; then
        log "DRY-RUN client command: ${client_cmd}"
        exit 0
    fi

    set +e
    bash -lc "${client_cmd}"
    local client_rc=$?
    set -e

    after_root="$(latest_run_root)"

    # Prefer the newly created run root when available.
    if [[ -n "${after_root}" && "${after_root}" != "${before_root}" ]]; then
        generate_report "${after_root}"
    else
        warn "No new AutoPTS run directory was created; skipping report generation."
    fi

    if [[ ${client_rc} -ne 0 ]]; then
        err "AutoPTS client exited with code ${client_rc}"
    else
        log "AutoPTS run completed successfully."
    fi

    exit ${client_rc}
}

main "$@"
