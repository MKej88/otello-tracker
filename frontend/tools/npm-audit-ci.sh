#!/usr/bin/env bash
set -u -o pipefail

max_attempts=3
base_delay_seconds=5
attempt_timeout_seconds=45

is_external_audit_failure() {
  grep -Eqi 'npm (warn|error) audit (429|5[0-9]{2})|Service Unavailable|Bad Gateway|Gateway Timeout|audit endpoint returned an error|ECONNRESET|ECONNREFUSED|ETIMEDOUT|EAI_AGAIN|ENOTFOUND'
}

for attempt in $(seq 1 "$max_attempts"); do
  echo "npm audit attempt ${attempt}/${max_attempts} (maks ${attempt_timeout_seconds}s)"
  output="$(timeout --signal=TERM "${attempt_timeout_seconds}s" npm audit --audit-level=high 2>&1)"
  status=$?
  printf '%s\n' "$output"

  if [ "$status" -eq 0 ]; then
    exit 0
  fi

  timed_out=false
  if [ "$status" -eq 124 ]; then
    timed_out=true
    echo "npm audit tidsavbrutt etter ${attempt_timeout_seconds}s."
  fi

  if [ "$timed_out" = true ] || printf '%s\n' "$output" | is_external_audit_failure; then
    if [ "$attempt" -lt "$max_attempts" ]; then
      delay=$((base_delay_seconds * attempt))
      echo "Ekstern npm-audit-feil/tidsavbrudd oppdaget. Prøver igjen om ${delay}s."
      sleep "$delay"
      continue
    fi

    echo "::warning::npm audit kunne ikke fullføres etter ${max_attempts} forsøk på grunn av ekstern registry-/nettverksfeil eller tidsavbrudd. Build/deploy fortsetter."
    exit 0
  fi

  echo "::error::npm audit rapporterte en reell dependency-feil/sårbarhet eller en ikke-transient feil."
  exit "$status"
done
