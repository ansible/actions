#!/bin/bash
# cspell: ignore shopt euxo msys armv
set -euo pipefail

DEBUG="${1:-false}"
MAX_ATTEMPTS=10

# Global variables used across platform-specific installation logic
attempt=0
version=""

if [[ "${DEBUG}" = "true" ]]
then
  set -x
fi

# restore executable bit on cached binary if needed
if [[ -f ~/.local/bin/gitleaks && ! -x ~/.local/bin/gitleaks ]]; then
    echo "::debug::Restoring executable bit on cached binary ~/.local/bin/gitleaks"
    chmod +x ~/.local/bin/gitleaks
fi

gitleaks_cmd=$(command -v gitleaks 2>/dev/null || find ~/.local/bin -name gitleaks -executable 2>/dev/null | head -1 || true)
arch="$(uname)_$(uname -m)"
platform=$(echo "$arch" | tr '[:upper:]' '[:lower:]' )
if [[ "$platform" =~ mingw.* || "$platform" =~ cygwin.* || "$platform" =~ msys.* ]]; then
    if [[ $PROCESSOR_ARCHITECTURE == "AMD64" ]]; then
        platform="windows_x64"
    elif [[ $PROCESSOR_ARCHITECTURE == "ARM64" ]]; then
        platform="windows_armv7"
    else
        echo "::error::Unsupported platform: $PROCESSOR_ARCHITECTURE"
        exit 4
    fi
    archive="zip"
else
    platform="${platform//aarch64/arm64}"
    platform="${platform//x86_64/x64}"
    archive="tar.gz"
fi

if [[ -n "$gitleaks_cmd" ]]; then
    version="$($gitleaks_cmd --version 2>/dev/null || true)"
    if [[ -n "$version" ]]; then
        echo "::debug::Detected ${gitleaks_cmd} version ${version} on ${platform}."
        exit 0
    else
        echo "::warning::Found gitleaks at ${gitleaks_cmd} but version check failed. Will attempt to reinstall."
        # Clear gitleaks_cmd to force reinstallation
        gitleaks_cmd=""
    fi
fi

# Installation logic (runs if no working gitleaks found)
if [[ -z "$gitleaks_cmd" ]]; then
    if [[ "$OSTYPE" == "darwin"* ]]; then
        brew install gitleaks
        gitleaks_cmd=$(command -v gitleaks)
        version="$($gitleaks_cmd --version || true)"
    elif [[ "$OSTYPE" == "linux"* || "$OSTYPE" == "msys"* ]]; then
        # Function to fetch version using gh CLI
        fetch_version_with_gh() {
            if command -v gh >/dev/null 2>&1; then
                local version_tag
                version_tag="$(gh release view --repo gitleaks/gitleaks --json tagName -q .tagName 2>/dev/null || true)"
                if [[ -n "$version_tag" ]]; then
                    echo "${version_tag#v}"
                    return 0
                fi
            fi
            return 1
        }

        # Function to fetch version using curl as fallback
        fetch_version_with_curl() {
            local version_tag
            version_tag="$(curl -s --fail --connect-timeout 10 --max-time 30 \
                "https://api.github.com/repos/gitleaks/gitleaks/releases/latest" \
                | grep -o '"tag_name": *"[^"]*"' \
                | grep -o 'v[^"]*' || true)"
            if [[ -n "$version_tag" ]]; then
                echo "${version_tag#v}"
                return 0
            fi
            return 1
        }

        while [[ $attempt -lt $MAX_ATTEMPTS ]]; do
            attempt=$((attempt + 1))
            echo "Attempt $attempt to fetch Gitleaks version..."

            # Try gh first, then curl as fallback
            if version="$(fetch_version_with_gh)"; then
                echo "::notice::Successfully fetched version $version using gh CLI"
                break
            elif version="$(fetch_version_with_curl)"; then
                echo "::notice::Successfully fetched version $version using curl fallback"
                break
            else
                if [[ $attempt -lt $MAX_ATTEMPTS ]]; then
                    delay=$((10 + attempt * 5))
                    echo "::warning::Attempt $attempt failed to fetch version. Retrying in $delay seconds..."
                    sleep $delay
                else
                    echo "::error::Failed to fetch Gitleaks version after $MAX_ATTEMPTS attempts."
                    exit 3
                fi
            fi
        done
        mkdir -p ~/.local/bin
        if [[ "$OSTYPE" == "msys"* ]]; then
            tmp_file=$TEMP/gitleaks.zip
        else
            tmp_file=$(mktemp)
        fi
        curl -Lf -o "$tmp_file" "https://github.com/gitleaks/gitleaks/releases/download/v${version}/gitleaks_${version}_${platform}.${archive}"
        if [[ "$OSTYPE" == "msys"* ]]; then
            unzip -p "$tmp_file" gitleaks.exe > "$USERPROFILE\AppData\Local\Microsoft\WindowsApps\gitleaks.exe"
            gitleaks_cmd=~/.local/bin/gitleaks
        else
            tar xf "$tmp_file" -C ~/.local/bin/ gitleaks
            gitleaks_cmd=~/.local/bin/gitleaks
            chmod +x ~/.local/bin/gitleaks
        fi
        rm "$tmp_file"
    else
        echo "::error::Unsupported platform: $OSTYPE"
        exit 4
    fi
fi

if [[ -z "${version:-}" ]]; then
    echo "::error::Failed to fetch Gitleaks version after $MAX_ATTEMPTS attempts."
    exit 3
fi
{
    echo "platform=$platform";
    echo "version=${version}";
} >> "${GITHUB_OUTPUT:-/dev/stdout}"
echo "::debug::Detected ${gitleaks_cmd} version ${version} on ${platform}."
