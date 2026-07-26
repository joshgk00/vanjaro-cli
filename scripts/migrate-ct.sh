#!/usr/bin/env bash
#
# migrate-ct.sh - Migrate a Proxmox LXC rootfs to another storage safely.
#
# Default workflow:
#   1. Run preflight checks and show current config, mounts, and usage.
#   2. Ask for explicit approval of the migration plan.
#   3. Stop the container before the final backup, so no writes are lost.
#   4. Take a fresh PBS backup and capture the exact new backup volid.
#   5. Ask for explicit approval before destroy.
#   6. Destroy, restore rootfs on target storage, start, and validate.
#
# Usage:
#   ./migrate-ct.sh [options] <CTID> <target-storage> <new-size-gb> [-- smoke-test...]
#
# Examples:
#   ./migrate-ct.sh 127 resilience-01 4
#   ./migrate-ct.sh 132 resilience-01 8 -- curl -sf http://192.168.1.50:8123
#   ./migrate-ct.sh --preflight-only 127 resilience-01 4
#
# Options:
#   --backup-storage NAME      PBS storage name (default: proxmox-pbs)
#   --skip-size-check          Continue if rootfs usage cannot be checked
#   --allow-bind-mounts        Allow bind mounts after warning that their data is not in backups
#   --allow-unbacked-mounts    Allow storage-backed mpN entries with backup=0
#   --preflight-only, --dry-run
#                              Run checks and print the plan, then exit
#   -h, --help                 Show this help

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

log()    { echo -e "${BLUE}[$(date +%H:%M:%S)]${NC} $*"; }
ok()     { echo -e "${GREEN}[OK]${NC} $*"; }
warn()   { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()    { echo -e "${RED}[ERROR]${NC} $*" >&2; }
header() { echo -e "\n${BOLD}=== $* ===${NC}\n"; }
die()    { err "$*"; exit 1; }

BACKUP_STORAGE="proxmox-pbs"
SKIP_SIZE_CHECK=0
ALLOW_BIND_MOUNTS=0
ALLOW_UNBACKED_MOUNTS=0
PREFLIGHT_ONLY=0
MOUNTED_FOR_CHECK=0
BACKUP_VOLID=""
DESTROYED=0

usage() {
  sed -n '2,28p' "$0" | sed 's/^# \{0,1\}//'
}

cleanup() {
  if [[ "${MOUNTED_FOR_CHECK:-0}" -eq 1 && -n "${CTID:-}" ]]; then
    warn "Attempting to unmount CT $CTID after interrupted size check"
    pct unmount "$CTID" >/dev/null 2>&1 || warn "Could not unmount CT $CTID automatically"
    MOUNTED_FOR_CHECK=0
  fi
}

on_error() {
  local line="$1"
  local command="$2"
  err "Script exited unexpectedly at line $line"
  err "Last command: $command"
  if [[ -n "${BACKUP_VOLID:-}" ]]; then
    err "Recovery backup volid: $BACKUP_VOLID"
  fi
  if [[ "${DESTROYED:-0}" -eq 1 ]]; then
    err "Container was already destroyed. Restore manually from the recovery backup above."
  fi
  cleanup
}

trap 'on_error "$LINENO" "$BASH_COMMAND"' ERR
trap cleanup EXIT

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --backup-storage)
        [[ $# -ge 2 ]] || die "--backup-storage requires a value"
        BACKUP_STORAGE="$2"
        shift 2
        ;;
      --skip-size-check)
        SKIP_SIZE_CHECK=1
        shift
        ;;
      --allow-bind-mounts)
        ALLOW_BIND_MOUNTS=1
        shift
        ;;
      --allow-unbacked-mounts)
        ALLOW_UNBACKED_MOUNTS=1
        shift
        ;;
      --preflight-only|--dry-run)
        PREFLIGHT_ONLY=1
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      --)
        shift
        break
        ;;
      -*)
        die "Unknown option: $1"
        ;;
      *)
        break
        ;;
    esac
  done

  [[ $# -ge 3 ]] || { usage; exit 1; }

  CTID="$1"
  TARGET_STORAGE="$2"
  NEW_SIZE="$3"
  shift 3

  SMOKE_TEST_ARGS=("$@")
}

get_pct_state() {
  pct status "$1" | awk '{print $2}'
}

is_running() {
  [[ "$(get_pct_state "$1")" == "running" ]]
}

wait_for_stopped() {
  local ctid="$1"
  local i

  for i in {1..60}; do
    if ! is_running "$ctid"; then
      return 0
    fi
    sleep 2
  done

  return 1
}

stop_container() {
  local ctid="$1"

  if ! is_running "$ctid"; then
    ok "Container is already stopped"
    return 0
  fi

  log "Gracefully shutting down CT $ctid"
  if pct shutdown "$ctid" --timeout 120 && wait_for_stopped "$ctid"; then
    ok "Container shut down cleanly"
    return 0
  fi

  warn "Graceful shutdown timed out or failed; forcing stop"
  pct stop "$ctid"

  if wait_for_stopped "$ctid"; then
    ok "Container stopped"
  else
    die "Container did not stop"
  fi
}

get_rootfs_used_mb_running() {
  local ctid="$1"
  pct exec "$ctid" -- df -P -m / 2>/dev/null | awk 'NR==2 {print $3}'
}

get_rootfs_used_mb_stopped() {
  local ctid="$1"
  local mount_output mount_path used

  if ! mount_output=$(pct mount "$ctid" 2>&1); then
    warn "pct mount failed: $mount_output"
    return 1
  fi
  MOUNTED_FOR_CHECK=1

  mount_path=$(printf '%s\n' "$mount_output" | sed -n "s/.*'\([^']*\)'.*/\1/p" | tail -n 1)
  if [[ -z "$mount_path" ]]; then
    mount_path="/var/lib/lxc/$ctid/rootfs"
  fi

  [[ -d "$mount_path" ]] || {
    pct unmount "$ctid" >/dev/null 2>&1 || true
    MOUNTED_FOR_CHECK=0
    return 1
  }

  used=$(df -P -m "$mount_path" 2>/dev/null | awk 'NR==2 {print $3}')

  if ! pct unmount "$ctid" >/dev/null; then
    MOUNTED_FOR_CHECK=0
    warn "pct unmount failed after size check"
    return 1
  fi
  MOUNTED_FOR_CHECK=0

  printf '%s\n' "$used"
}

check_size() {
  local ctid="$1"
  local used_mb=""
  local new_size_mb

  if is_running "$ctid"; then
    log "Checking rootfs usage from inside the running container"
    used_mb=$(get_rootfs_used_mb_running "$ctid" || true)
  else
    log "Container is stopped; mounting rootfs on the host for usage check"
    used_mb=$(get_rootfs_used_mb_stopped "$ctid" || true)
  fi

  if [[ -z "$used_mb" || ! "$used_mb" =~ ^[0-9]+$ ]]; then
    if [[ "$SKIP_SIZE_CHECK" -eq 1 ]]; then
      warn "Could not determine rootfs usage; continuing because --skip-size-check was provided"
      USAGE_MB=""
      return 0
    fi
    die "Could not determine rootfs usage. Start the CT, fix pct mount, or rerun with --skip-size-check."
  fi

  USAGE_MB="$used_mb"
  new_size_mb=$((NEW_SIZE * 1024))

  log "Actual rootfs usage: ${USAGE_MB}M"
  if [[ "$USAGE_MB" -gt "$new_size_mb" ]]; then
    die "Cannot resize to ${NEW_SIZE}G; actual usage is ${USAGE_MB}M"
  fi

  ok "Target size ${NEW_SIZE}G is large enough for ${USAGE_MB}M of rootfs data"
}

list_backup_volids() {
  local ctid="$1"
  local output

  if output=$(pvesm list "$BACKUP_STORAGE" --vmid "$ctid" --content backup 2>/dev/null); then
    :
  else
    output=$(pvesm list "$BACKUP_STORAGE")
  fi

  printf '%s\n' "$output" \
    | awk -v ctid="$ctid" 'NR > 1 && $1 ~ "(^|:)backup/ct/" ctid "/" {print $1}'
}

capture_new_backup_volid() {
  local before="$1"
  local after="$2"
  local new_backups count

  new_backups=$(
    comm -13 \
      <(printf '%s\n' "$before" | sed '/^$/d' | sort) \
      <(printf '%s\n' "$after" | sed '/^$/d' | sort)
  )
  count=$(printf '%s\n' "$new_backups" | sed '/^$/d' | wc -l | tr -d ' ')

  if [[ "$count" -eq 1 ]]; then
    printf '%s\n' "$new_backups" | sed '/^$/d'
    return 0
  fi

  if [[ "$count" -eq 0 ]]; then
    err "No new backup appeared for CT $CTID on $BACKUP_STORAGE"
  else
    err "More than one new backup appeared for CT $CTID:"
    printf '%s\n' "$new_backups" | sed '/^$/d' >&2
  fi

  return 1
}

confirm_exact() {
  local prompt="$1"
  local expected="$2"
  local answer

  read -r -p "$prompt" answer
  [[ "$answer" == "$expected" ]]
}

inspect_mount_points() {
  local config="$1"
  local line key value volume has_failure=0

  MOUNT_LINES=$(printf '%s\n' "$config" | awk '/^(rootfs|mp[0-9]+):/ {print}')

  if [[ -z "$MOUNT_LINES" ]]; then
    die "Could not find rootfs in pct config"
  fi

  log "Configured rootfs and mount points:"
  printf '%s\n' "$MOUNT_LINES" | sed 's/^/  /'

  while IFS= read -r line; do
    key="${line%%:*}"
    value="${line#*: }"

    [[ "$key" =~ ^mp[0-9]+$ ]] || continue

    volume="${value%%,*}"

    if [[ ",$value," == *",backup=0,"* ]]; then
      if [[ "$ALLOW_UNBACKED_MOUNTS" -eq 1 ]]; then
        warn "$key has backup=0 and will not be protected by the PBS backup"
      else
        err "$key has backup=0: $value"
        has_failure=1
      fi
    fi

    if [[ "$volume" == /* ]]; then
      if [[ "$ALLOW_BIND_MOUNTS" -eq 1 ]]; then
        warn "$key is a bind mount. Proxmox backups include the config, not the bind-mounted data: $volume"
      else
        err "$key appears to be a bind mount: $value"
        has_failure=1
      fi
    else
      ok "$key is storage-backed and eligible for Proxmox backup handling"
    fi
  done <<< "$MOUNT_LINES"

  if [[ "$has_failure" -eq 1 ]]; then
    die "Mount point guardrail failed. Review the entries above or rerun with explicit allow flags."
  fi
}

run_smoke_test() {
  if [[ "${#SMOKE_TEST_ARGS[@]}" -eq 0 ]]; then
    warn "No smoke test provided; manually verify the service externally"
    return 0
  fi

  log "Running smoke test: ${SMOKE_TEST_ARGS[*]}"
  if [[ "${#SMOKE_TEST_ARGS[@]}" -eq 1 ]]; then
    bash -lc "${SMOKE_TEST_ARGS[0]}"
  else
    "${SMOKE_TEST_ARGS[@]}"
  fi
}

parse_args "$@"

[[ "$CTID" =~ ^[0-9]+$ ]] || die "CTID must be numeric"
[[ "$NEW_SIZE" =~ ^[1-9][0-9]*$ ]] || die "new-size-gb must be a positive integer"

header "Preflight checks (CT $CTID -> $TARGET_STORAGE, ${NEW_SIZE}G)"

if ! command -v pct >/dev/null 2>&1; then
  die "pct command not found. Run this on a Proxmox node."
fi

if ! command -v pvesm >/dev/null 2>&1; then
  die "pvesm command not found. Run this on a Proxmox node."
fi

if ! command -v vzdump >/dev/null 2>&1; then
  die "vzdump command not found. Run this on a Proxmox node."
fi

if ! pct config "$CTID" >/dev/null 2>&1; then
  die "Container $CTID does not exist"
fi
ok "Container $CTID exists"

if ! pvesm status | awk -v s="$TARGET_STORAGE" '$1 == s && $3 == "active" {found=1} END {exit !found}'; then
  die "Target storage '$TARGET_STORAGE' not found or not active"
fi
TARGET_TYPE=$(pvesm status | awk -v s="$TARGET_STORAGE" '$1 == s {print $2}')
ok "Target storage '$TARGET_STORAGE' is active (${TARGET_TYPE:-unknown type})"

if ! pvesm status | awk -v s="$BACKUP_STORAGE" '$1 == s && $3 == "active" {found=1} END {exit !found}'; then
  die "Backup storage '$BACKUP_STORAGE' not found or not active"
fi
ok "Backup storage '$BACKUP_STORAGE' is active"

CONFIG=$(pct config "$CTID")
HOSTNAME=$(printf '%s\n' "$CONFIG" | awk '/^hostname:/ {print $2}')
CURRENT_ROOTFS=$(printf '%s\n' "$CONFIG" | awk '/^rootfs:/ {print $2}')
CURRENT_STORAGE=$(printf '%s\n' "$CURRENT_ROOTFS" | cut -d: -f1)
INITIAL_STATE=$(get_pct_state "$CTID")

[[ -n "$CURRENT_ROOTFS" ]] || die "Could not read current rootfs from pct config"
[[ "$CURRENT_STORAGE" != "$TARGET_STORAGE" ]] || die "Container $CTID is already on $TARGET_STORAGE"

log "Hostname: ${HOSTNAME:-unknown}"
log "Initial state: $INITIAL_STATE"
log "Current rootfs: $CURRENT_ROOTFS"
ok "Currently on '$CURRENT_STORAGE'; target is '$TARGET_STORAGE'"

inspect_mount_points "$CONFIG"
check_size "$CTID"

header "Migration plan"
echo "  Container:        $CTID (${HOSTNAME:-unknown})"
echo "  Initial state:    $INITIAL_STATE"
echo "  Current storage:  $CURRENT_STORAGE"
echo "  Target storage:   $TARGET_STORAGE"
echo "  Target type:      ${TARGET_TYPE:-unknown}"
echo "  New rootfs size:  ${NEW_SIZE}G"
echo "  Backup storage:   $BACKUP_STORAGE"
if [[ -n "${USAGE_MB:-}" ]]; then
  echo "  Rootfs usage:     ${USAGE_MB}M"
else
  echo "  Rootfs usage:     skipped"
fi
if [[ "${#SMOKE_TEST_ARGS[@]}" -gt 0 ]]; then
  echo "  Smoke test:       ${SMOKE_TEST_ARGS[*]}"
fi
echo ""
echo "  Steps:"
echo "    1. Stop CT $CTID before the final backup"
echo "    2. Take fresh PBS backup while CT $CTID is stopped"
echo "    3. Capture the exact newly-created backup volid"
echo "    4. Ask for explicit destroy confirmation"
echo "    5. Destroy CT $CTID"
echo "    6. Restore to $TARGET_STORAGE with ${NEW_SIZE}G rootfs"
echo "    7. Start and validate CT $CTID"
echo ""

if [[ "$PREFLIGHT_ONLY" -eq 1 ]]; then
  ok "Preflight complete; exiting before changes because --preflight-only was provided"
  exit 0
fi

if ! confirm_exact "Proceed? Type 'yes' to stop, back up, and migrate CT $CTID: " "yes"; then
  warn "Cancelled. No changes made."
  exit 0
fi

header "Step 1/7: Stop container before final backup"
stop_container "$CTID"

header "Step 2/7: Fresh stopped backup to PBS"
BEFORE_BACKUPS=$(list_backup_volids "$CTID" || true)
log "Running: vzdump $CTID --storage $BACKUP_STORAGE --mode stop --compress zstd"
vzdump "$CTID" --storage "$BACKUP_STORAGE" --mode stop --compress zstd
AFTER_BACKUPS=$(list_backup_volids "$CTID" || true)

BACKUP_VOLID=$(capture_new_backup_volid "$BEFORE_BACKUPS" "$AFTER_BACKUPS")
ok "Backup completed and identified: $BACKUP_VOLID"

header "Step 3/7: Final confirmation before destroy"
echo "About to run: pct destroy $CTID"
echo ""
echo "This removes the container and its referenced volumes from:"
echo "  $CURRENT_STORAGE"
echo ""
echo "Recovery backup volid:"
echo "  $BACKUP_VOLID"
echo ""
if ! confirm_exact "Type 'destroy' to proceed: " "destroy"; then
  warn "Cancelled at destroy step. Container is stopped and backup is complete."
  warn "To resume service without migrating, run: pct start $CTID"
  exit 0
fi

header "Step 4/7: Destroy old container"
pct destroy "$CTID"
DESTROYED=1
ok "Container destroyed"

header "Step 5/7: Restore from PBS to $TARGET_STORAGE"
log "Running: pct restore $CTID $BACKUP_VOLID --storage $TARGET_STORAGE --rootfs $TARGET_STORAGE:$NEW_SIZE"
pct restore "$CTID" "$BACKUP_VOLID" \
  --storage "$TARGET_STORAGE" \
  --rootfs "$TARGET_STORAGE:$NEW_SIZE"
DESTROYED=0
ok "Restore completed"

header "Step 6/7: Start container"
pct start "$CTID"
sleep 5

if ! is_running "$CTID"; then
  die "Container did not start"
fi
ok "Container started"

header "Step 7/7: Validation"
NEW_CONFIG=$(pct config "$CTID")
NEW_ROOTFS=$(printf '%s\n' "$NEW_CONFIG" | awk '/^rootfs:/ {print $2}')
log "New rootfs: $NEW_ROOTFS"

if [[ "$NEW_ROOTFS" != "${TARGET_STORAGE}:"* ]]; then
  die "Rootfs is not on $TARGET_STORAGE: $NEW_ROOTFS"
fi
ok "Rootfs is on target storage"

if pct exec "$CTID" -- df -h / 2>/dev/null; then
  ok "Container filesystem is reachable"
else
  warn "Could not get df output from container; it may still be booting"
fi

NEW_USAGE_MB=$(get_rootfs_used_mb_running "$CTID" || true)
if [[ -n "${USAGE_MB:-}" && -n "${NEW_USAGE_MB:-}" && "$NEW_USAGE_MB" =~ ^[0-9]+$ && "$NEW_USAGE_MB" -gt 0 ]]; then
  RATIO=$(awk -v a="$USAGE_MB" -v b="$NEW_USAGE_MB" 'BEGIN {printf "%.2f", a / b}')
  log "Usage comparison: ${USAGE_MB}M before -> ${NEW_USAGE_MB}M after (${RATIO}x apparent ratio)"
fi

if run_smoke_test; then
  ok "Smoke test passed or was skipped"
else
  die "Smoke test FAILED. Investigate the restored container before declaring success."
fi

trap - ERR
header "Migration complete: CT $CTID (${HOSTNAME:-unknown})"
echo "  $CURRENT_STORAGE -> $TARGET_STORAGE"
echo "  Rootfs: ${NEW_SIZE}G"
echo "  Backup: $BACKUP_VOLID"
if [[ "${#SMOKE_TEST_ARGS[@]}" -gt 0 ]]; then
  echo "  Smoke test: passed"
fi
echo ""
echo "Next steps:"
echo "  - Verify the service externally"
echo "  - Record the migration and usage comparison in your tracking sheet"
