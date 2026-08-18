#!/usr/bin/env bash

set -euo pipefail

image_tags_csv="${1:-}"
if [ -z "${image_tags_csv}" ]; then
  echo "Image tags are required." >&2
  exit 1
fi

IFS=',' read -r -a image_tags <<< "${image_tags_csv}"
max_attempts=5

for image_tag in "${image_tags[@]}"; do
  for ((attempt = 1; attempt <= max_attempts; attempt++)); do
    if docker push "${image_tag}"; then
      break
    fi

    if [ "${attempt}" -eq "${max_attempts}" ]; then
      echo "Failed to push ${image_tag} after ${max_attempts} attempts." >&2
      exit 1
    fi

    delay=$((30 * (2 ** (attempt - 1))))
    echo "Image push failed; retrying ${image_tag} in ${delay}s (${attempt}/${max_attempts})..." >&2
    sleep "${delay}"
  done
done
