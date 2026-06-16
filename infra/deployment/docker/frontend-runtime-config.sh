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

write_config_entry() {
  name="$1"
  eval "value=\${$name:-}"
  if [ -z "$value" ]; then
    return
  fi

  escaped="$(escape_js_string "$value")"
  printf '  "%s": "%s",\n' "$name" "$escaped"
}

{
  printf 'window.__AITEACHME_RUNTIME_CONFIG__ = Object.freeze({\n'
  write_config_entry VITE_POSTHOG_ENABLED
  write_config_entry VITE_POSTHOG_TOKEN
  write_config_entry VITE_POSTHOG_HOST
  write_config_entry VITE_POSTHOG_SESSION_REPLAY
  write_config_entry VITE_POSTHOG_DEBUG
  write_config_entry VITE_APP_VERSION
  printf '});\n'
} > "$runtime_config_path"
