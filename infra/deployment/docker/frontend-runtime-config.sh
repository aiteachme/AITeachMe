#!/bin/sh
set -eu

runtime_config_path="${AITEACHME_RUNTIME_CONFIG_PATH:-/usr/share/nginx/html/runtime-config.js}"
runtime_config_dir="$(dirname "$runtime_config_path")"
mkdir -p "$runtime_config_dir"

escape_js_string() {
  printf '%s' "$1" | awk '
    BEGIN { ORS = "" }
    {
      gsub(/\r/, "")
      gsub(/\\/, "\\\\")
      gsub(/"/, "\\\"")
      if (NR > 1) {
        printf "\\n"
      }
      printf "%s", $0
    }
  '
}

env_value() {
  name="$1"
  eval "printf '%s' \"\${$name:-}\""
}

write_config_entry() {
  output_name="$1"
  shift
  value=""
  for env_name in "$@"; do
    candidate="$(env_value "$env_name")"
    if [ -n "$candidate" ]; then
      value="$candidate"
      break
    fi
  done

  if [ -z "$value" ]; then
    return
  fi

  escaped="$(escape_js_string "$value")"
  printf '  "%s": "%s",\n' "$output_name" "$escaped"
}

{
  printf 'window.__AITEACHME_RUNTIME_CONFIG__ = Object.freeze({\n'
  write_config_entry VITE_POSTHOG_ENABLED VITE_POSTHOG_ENABLED POSTHOG_ENABLED
  write_config_entry VITE_POSTHOG_TOKEN VITE_POSTHOG_TOKEN POSTHOG_TOKEN
  write_config_entry VITE_POSTHOG_HOST VITE_POSTHOG_HOST POSTHOG_HOST
  write_config_entry VITE_POSTHOG_SESSION_REPLAY VITE_POSTHOG_SESSION_REPLAY
  write_config_entry VITE_POSTHOG_DEBUG VITE_POSTHOG_DEBUG POSTHOG_DEBUG
  write_config_entry VITE_APP_VERSION VITE_APP_VERSION
  printf '});\n'
} > "$runtime_config_path"
