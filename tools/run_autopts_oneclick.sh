#!/usr/bin/env bash
set -euo pipefail

# One-click AutoPTS orchestrator for WSL + Windows.
#
# Required argument:
#   --pts-ip <windows-host-ip>
#
# Example:
#   tools/run_autopts_oneclick.sh \
#     --workspace-file "C:\\Users\\USER\\Documents\\Profile Tuning Suite\\PTS_PROJECT\\PTS_PROJECT.pqw6" \
#     --pts-ip 172.21.128.1 \
#     --elf "Z:\\home\\david\\ti-workspace\\zephyr\\build\\zephyr\\zephyr.elf"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Defaults tuned to the user's existing workflow.
TESTS=""
PTS_IP=""
WORKSPACE="zephyr-master"
WORKSPACE_FILE=""
WORKSPACE_RESOLVED=""
ELF_PATH='Z:\home\david\ti-workspace\zephyr\build\zephyr\zephyr.elf'
TTY_DEV="/dev/ttyACM0"
BOARD="lp_em_cc2340r53"
PTS_SRV_PORT="65000"
PTS_CLI_PORT="65001"
PTS_DONGLE=""
TTY_BAUD="115200"
CLIENT_LOCAL_IP=""

ENABLE_USB_SETUP=1
START_WINDOWS_SERVER=1
RUN_REPORT=1
OPEN_REPORT=1
VERBOSE=0
DRY_RUN=0

usage() {
    cat <<'EOF'
Usage:
    tools/run_autopts_oneclick.sh --pts-ip <IP> [selection-options] [options]

Required:
  --pts-ip <value>           Windows host IP for autoptsserver.py

Selection options:
    --workspace-file <value>    Path to a PTS workspace (.pqw6). If this is a Linux path,
                                                            it is converted to Windows path before launching the client.
    --workspace <value>         Workspace name/path passed to client (default: zephyr-master)
    --tests <value>             Test(s) to run (e.g. GAP/BROB/BCST or GAP).
                                                            Can be repeated or comma-separated.
                                                            If omitted, AutoPTS runs enabled tests from workspace.

Options:
  --elf <value>              Kernel image path passed to client
  --tty <value>              TTY device (default: /dev/ttyACM0)
  --board <value>            Board name (default: lp_em_cc2340r53)
  --srv-port <value>         PTS server port (default: 65000)
  --cli-port <value>         PTS callback/client port (default: 65001)
    --pts-dongle <value>       PTS dongle selector passed to server (e.g. COM5)
  --tty-baud <value>         TTY baudrate (default: 115200)
  --local-ip <value>         Local WSL IP (default: auto-detected)

  --no-usb-setup             Skip sudo modprobe/chmod setup
  --no-server-launch         Do not auto-launch Windows autoptsserver.py
  --no-report                Skip report generation
  --no-open                  Generate report but do not open in browser

  --dry-run                  Print actions but do not execute
  --verbose                  Print commands as they execute
  -h, --help                 Show this help

Notes:
- Run from any location; script auto-resolves repo root.
- `--workspace-file` takes precedence over `--workspace` when both are provided.
- For fully non-interactive USB setup, configure sudoers for:
  /sbin/modprobe cdc_acm and /bin/chmod 666 /dev/ttyACM0
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

run_bash() {
    local cmd="$1"
    if [[ "${DRY_RUN}" -eq 1 ]]; then
        log "DRY-RUN: ${cmd}"
        return 0
    fi
    if [[ "${VERBOSE}" -eq 1 ]]; then
        log "EXEC: ${cmd}"
    fi
    bash -lc "${cmd}"
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

    require_cmd python3
    require_cmd powershell.exe
    require_cmd explorer.exe
    require_cmd wslpath

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

    if [[ -z "${VIRTUAL_ENV:-}" ]]; then
        warn "Python venv is not active. Continuing, but venv is recommended."
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
            --tty) TTY_DEV="$2"; shift 2 ;;
            --board) BOARD="$2"; shift 2 ;;
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

    [[ -n "${PTS_IP}" ]] || { err "--pts-ip is required"; usage; exit 2; }

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

    # Quick TCP reachability probe for Windows host:port.
    python3 - <<PY
import socket, sys
host = ${PTS_IP@Q}
port = int(${PTS_SRV_PORT@Q})
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(1.5)
try:
    s.connect((host, port))
except Exception:
    sys.exit(0)
else:
    # Port already open: not an error; might be existing server.
    sys.exit(0)
finally:
    s.close()
PY
}

usb_setup() {
    [[ "${ENABLE_USB_SETUP}" -eq 1 ]] || {
        log "Skipping USB setup (--no-usb-setup)."
        return 0
    }

    log "Preparing USB serial access (${TTY_DEV})..."

    if ! run_bash "sudo -n modprobe cdc_acm"; then
        warn "Non-interactive sudo unavailable for modprobe; trying interactive sudo."
        if ! run_bash "sudo modprobe cdc_acm"; then
            err "Failed to load cdc_acm."
            err "Ensure sudo permissions are configured and the USB device is attached to WSL."
            exit 1
        fi
    fi

    if [[ "${DRY_RUN}" -eq 0 ]]; then
        if [[ ! -e "${TTY_DEV}" ]]; then
            err "TTY device not found after modprobe: ${TTY_DEV}"
            err "Ensure the board is attached to WSL (usbipd attach --wsl --busid <BUSID>)."
            exit 1
        fi
    else
        if [[ ! -e "${TTY_DEV}" ]]; then
            warn "TTY device not found (dry-run): ${TTY_DEV}"
        fi
    fi

    if ! run_bash "sudo -n chmod 666 ${TTY_DEV}"; then
        warn "Non-interactive sudo unavailable for chmod; trying interactive sudo."
        if ! run_bash "sudo chmod 666 ${TTY_DEV}"; then
            err "Failed to set permissions on ${TTY_DEV}."
            err "Use --no-usb-setup only if permissions are already managed via udev/sudoers."
            exit 1
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
    ps="Start-Process -FilePath 'cmd.exe' -WorkingDirectory \$env:USERPROFILE -ArgumentList '/k', '${cmd}' | Out-Null"

    run_cmd powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ps"

    # Best-effort wait for server port.
    if [[ "${DRY_RUN}" -eq 0 ]]; then
        local ok=0
        for _ in $(seq 1 25); do
            if python3 - <<PY
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

    cmd+="python3 ./autoptsclient-zephyr.py ${WORKSPACE_RESOLVED@Q} ${ELF_PATH@Q} "
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
    run_cmd python3 "${REPO_ROOT}/tools/autopts_report.py" --run-root "${run_root}"

    if [[ "${OPEN_REPORT}" -eq 1 ]]; then
        run_cmd explorer.exe "$(wslpath -w "${report_path}")"
    fi

    log "Run root: ${run_root}"
    log "Report: ${report_path}"
}

main() {
    parse_args "$@"
    check_wsl_prereqs
    resolve_workspace
    resolve_local_ip
    preflight_checks

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
    log "  elf=${ELF_PATH}"
    log "  local_ip=${CLIENT_LOCAL_IP}"
    usb_setup
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
        generate_report "${after_root:-$before_root}"
    fi

    if [[ ${client_rc} -ne 0 ]]; then
        err "AutoPTS client exited with code ${client_rc}"
    else
        log "AutoPTS run completed successfully."
    fi

    exit ${client_rc}
}

main "$@"
