#!/bin/bash
# cspell: ignore nullglob
set -euo pipefail

DEBUG="${1:-false}"
if [[ "${DEBUG}" = "true" ]]
then
  set -x
fi

shopt -s nullglob
IFS=$'\n' read -r -d '' -a INPUT_PATH_ARRAY < <(printf '%s\0' "$INPUT_PATH")
RESULT=0
gitleaks=$(command -v gitleaks) || gitleaks=~/.local/bin/gitleaks
for path in "${INPUT_PATH_ARRAY[@]}"; do
    for file in $path; do
    if [ -e "$file" ]; then
        $gitleaks dir -v --redact=100 --no-banner --max-archive-depth=2 "$file" || RESULT=$?
    fi
    done
done
exit $RESULT
