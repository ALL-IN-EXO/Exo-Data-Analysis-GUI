#!/usr/bin/env bash
if [ -z "${BASH_VERSION:-}" ]; then
  exec /usr/bin/env bash "$0" "$@"
fi
set -euo pipefail

# Build macOS .app for:
#   data_analyzer_main.py
#
# Usage:
#   ./scripts/build_mac.sh
#
# Optional env vars:
#   PYTHON_BIN=/usr/local/bin/python3
#   APP_VERSION=1.3
#   APP_NAME_BASE=HipExoDataAnalyzer
#   APP_NAME=HipExoDataAnalyzer_v1.3
#   APP_NAME_INCLUDE_VERSION=1     # default ON; if APP_NAME unset, append _vX.Y
#   APP_DISPLAY_NAME="Hip Exo Data Analyzer v1.3"
#   ICON_SOURCE=/path/to/icon.png
#   ICON_ENABLED=1                 # default ON; set 0 to disable
#   VERSION_ENABLED=1              # default ON; set 0 to skip plist version stamping
#   SIGN_ENABLED=0                 # default OFF; set 1 to enable Developer ID signing
#   DEVELOPER_ID="Developer ID Application: Your Name"
#   CODESIGN_OPTIONS=runtime
#   NOTARIZE_ENABLED=0             # default OFF; set 1 to submit notarization
#   NOTARY_PROFILE=exo-notary
#   STAPLE_ENABLED=1
#   SKIP_DEP_INSTALL=0             # set 1 to skip pip install in venv
#   FULL_BUILD=0                   # set 1 to collect-all heavy deps
#   VENV_DIR=/custom/path/.venv-build
#   WORK_ROOT=/custom/local/build-root
#   PYI_CONFIG_DIR=/custom/path/pyinstaller-config

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENTRY="${REPO_ROOT}/data_analyzer_main.py"
README_FILE="${REPO_ROOT}/README.md"
CHANGELOG_FILE="${REPO_ROOT}/docs/CHANGELOG.md"

if [[ ! -f "${ENTRY}" ]]; then
  echo "Entry not found: ${ENTRY}"
  exit 1
fi

if [[ -n "${PYTHON_BIN:-}" ]]; then
  PY="${PYTHON_BIN}"
elif [[ -x "/usr/local/bin/python3" ]]; then
  PY="/usr/local/bin/python3"
else
  PY="$(command -v python3 || true)"
fi

if [[ -z "${PY}" ]]; then
  echo "python3 not found. Install Python first."
  exit 1
fi

extract_app_version() {
  local v=""
  if [[ -f "${CHANGELOG_FILE}" ]]; then
    v="$(grep -Eo '^## \[v?[0-9]+([.][0-9]+)*\]' "${CHANGELOG_FILE}" | head -n1 | sed -E 's/^## \[v?([0-9]+([.][0-9]+)*)\]$/\1/' || true)"
  fi
  if [[ -z "${v}" ]] && [[ -f "${README_FILE}" ]]; then
    v="$(grep -Eo 'Current Version: v[0-9]+([.][0-9]+)+' "${README_FILE}" | head -n1 | sed -E 's/.*v//' || true)"
  fi
  if [[ -z "${v}" ]]; then
    v="$(grep -Eo 'v[0-9]+([.][0-9]+)+' "${ENTRY}" | head -n1 | sed 's/^v//' || true)"
  fi
  if [[ -n "${v}" ]]; then
    echo "${v}"
  else
    echo "1.0.0"
  fi
}

APP_VERSION="${APP_VERSION:-$(extract_app_version)}"
APP_NAME_BASE="${APP_NAME_BASE:-HipExoDataAnalyzer}"
APP_NAME_INCLUDE_VERSION="${APP_NAME_INCLUDE_VERSION:-1}"
if [[ -n "${APP_NAME:-}" ]]; then
  APP_NAME="${APP_NAME}"
elif [[ "${APP_NAME_INCLUDE_VERSION}" != "0" ]]; then
  APP_NAME="${APP_NAME_BASE}_v${APP_VERSION}"
else
  APP_NAME="${APP_NAME_BASE}"
fi
APP_TITLE_BASE="${APP_TITLE_BASE:-Hip Exo Data Analyzer}"
APP_DISPLAY_NAME="${APP_DISPLAY_NAME:-${APP_TITLE_BASE} v${APP_VERSION}}"

ICON_ENABLED="${ICON_ENABLED:-1}"
VERSION_ENABLED="${VERSION_ENABLED:-1}"
SIGN_ENABLED="${SIGN_ENABLED:-0}"
DEVELOPER_ID="${DEVELOPER_ID:-Developer ID Application: Your Name}"
CODESIGN_OPTIONS="${CODESIGN_OPTIONS:-runtime}"
NOTARIZE_ENABLED="${NOTARIZE_ENABLED:-0}"
NOTARY_PROFILE="${NOTARY_PROFILE:-exo-notary}"
STAPLE_ENABLED="${STAPLE_ENABLED:-1}"
ICON_SOURCE="${ICON_SOURCE:-/Volumes/X10 Pro/Engineering For Lifelong Use/Hip Exo Controller All in one with Apple GUI/scripts/exoanalysis.png}"

# Keep build env outside removable/external drives to avoid AppleDouble metadata issues.
VENV_DIR="${VENV_DIR:-${HOME}/.exo_gui_build/analyzer/venv_mac_py39}"
WORK_ROOT="${WORK_ROOT:-${HOME}/.exo_gui_build/analyzer/work_mac}"
DIST_DIR="${WORK_ROOT}/dist"
BUILD_DIR="${WORK_ROOT}/build"
SPEC_DIR="${WORK_ROOT}/spec"
ICON_ICNS="${WORK_ROOT}/app_icon.icns"

GIT_SHA="$(git -C "${REPO_ROOT}" rev-parse --short HEAD 2>/dev/null || echo 'nogit')"
TS="$(date '+%Y%m%d_%H%M%S')"
BUILD_TAG="${TS}_${GIT_SHA}"
PYI_CONFIG_DIR="${PYI_CONFIG_DIR:-${WORK_ROOT}/pyinstaller_config_${BUILD_TAG}}"
RELEASE_DIR="${REPO_ROOT}/release/mac/${BUILD_TAG}"

echo "==> Repo: ${REPO_ROOT}"
echo "==> Entry: ${ENTRY}"
echo "==> Python: ${PY}"
echo "==> Changelog: ${CHANGELOG_FILE}"
echo "==> App version: ${APP_VERSION}"
echo "==> App name: ${APP_NAME}"
echo "==> App display name: ${APP_DISPLAY_NAME}"
echo "==> Build venv: ${VENV_DIR}"
echo "==> Work root: ${WORK_ROOT}"
echo "==> PyInstaller config/cache: ${PYI_CONFIG_DIR}"
echo "==> Build tag: ${BUILD_TAG}"
echo "==> Icon enabled: ${ICON_ENABLED}"
echo "==> Sign enabled: ${SIGN_ENABLED}"
echo "==> Notarize enabled: ${NOTARIZE_ENABLED}"

if [[ ! -d "${VENV_DIR}" ]]; then
  echo "==> Creating build venv: ${VENV_DIR}"
  "${PY}" -m venv "${VENV_DIR}"
fi

# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"

cleanup_appledouble_tree() {
  local target="$1"
  if [[ -d "${target}" || -f "${target}" ]]; then
    find "${target}" -type f -name '._*' -delete 2>/dev/null || true
  fi
}

set_plist_value() {
  local plist_file="$1"
  local key="$2"
  local type="$3"
  local value="$4"
  /usr/libexec/PlistBuddy -c "Set :${key} ${value}" "${plist_file}" >/dev/null 2>&1 \
    || /usr/libexec/PlistBuddy -c "Add :${key} ${type} ${value}" "${plist_file}" >/dev/null 2>&1 \
    || true
}

prepare_icon_icns() {
  local src="$1"
  local out="$2"
  local iconset_dir="${WORK_ROOT}/app_icon.iconset"

  rm -rf "${iconset_dir}" "${out}"
  mkdir -p "${iconset_dir}"

  python - <<PY
from PIL import Image

src = r"""${src}"""
iconset_dir = r"""${iconset_dir}"""
img = Image.open(src).convert("RGBA")
targets = [
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
    ("icon_512x512@2x.png", 1024),
]
for name, size in targets:
    out = img.resize((size, size), Image.LANCZOS)
    out.save(f"{iconset_dir}/{name}", format="PNG")
PY

  iconutil -c icns "${iconset_dir}" -o "${out}"
}

export COPYFILE_DISABLE=1
rm -rf "${PYI_CONFIG_DIR}"
mkdir -p "${PYI_CONFIG_DIR}"
export PYINSTALLER_CONFIG_DIR="${PYI_CONFIG_DIR}"

if [[ "${SKIP_DEP_INSTALL:-0}" != "1" ]]; then
  echo "==> Installing build/runtime dependencies into venv"
  python -m pip install --upgrade pip setuptools wheel
  python -m pip install --upgrade pyinstaller pyqt5 matplotlib pandas numpy scipy pillow
fi

echo "==> Cleaning previous build folders"
mkdir -p "${WORK_ROOT}"
rm -rf "${DIST_DIR}" "${BUILD_DIR}" "${SPEC_DIR}"
mkdir -p "${SPEC_DIR}"

ICON_FLAG_ARGS=()
if [[ "${ICON_ENABLED}" != "0" ]]; then
  if [[ -f "${ICON_SOURCE}" ]]; then
    echo "==> Preparing macOS icon (.icns) from: ${ICON_SOURCE}"
    if prepare_icon_icns "${ICON_SOURCE}" "${ICON_ICNS}"; then
      ICON_FLAG_ARGS+=(--icon "${ICON_ICNS}")
    else
      echo "[warn] Failed to prepare .icns icon, continue without custom icon"
    fi
  else
    echo "[warn] ICON_SOURCE not found: ${ICON_SOURCE} (continue without custom icon)"
  fi
fi

FULL_BUILD="${FULL_BUILD:-0}"
export QT_API=pyqt5

PYI_ARGS=(
  --noconfirm
  --clean
  --windowed
  --name "${APP_NAME}"
  --distpath "${DIST_DIR}"
  --workpath "${BUILD_DIR}"
  --specpath "${SPEC_DIR}"
  --collect-data matplotlib
  --hidden-import matplotlib.backends.backend_qt5agg
  --hidden-import scipy.signal
  --hidden-import PyQt5.sip
  --exclude-module tkinter
  --exclude-module _tkinter
)
if [[ ${#ICON_FLAG_ARGS[@]} -gt 0 ]]; then
  PYI_ARGS+=("${ICON_FLAG_ARGS[@]}")
fi

if [[ -d "${REPO_ROOT}/data_output/sample_data" ]]; then
  PYI_ARGS+=(--add-data "${REPO_ROOT}/data_output/sample_data:data_output/sample_data")
fi
if [[ -f "${REPO_ROOT}/.column_mapping.json" ]]; then
  PYI_ARGS+=(--add-data "${REPO_ROOT}/.column_mapping.json:.")
fi

if [[ "${FULL_BUILD}" == "1" ]]; then
  echo "==> Build mode: FULL (collect-all)"
  PYI_ARGS+=(--collect-all PyQt5 --collect-all matplotlib --collect-all pandas --collect-all scipy --collect-all numpy)
else
  echo "==> Build mode: SLIM (default)"
fi

echo "==> Running PyInstaller"
python -m PyInstaller "${PYI_ARGS[@]}" "${ENTRY}"

APP_BUNDLE="${DIST_DIR}/${APP_NAME}.app"
if [[ ! -d "${APP_BUNDLE}" ]]; then
  echo "Build failed: app bundle not found at ${APP_BUNDLE}"
  exit 1
fi

if [[ "${VERSION_ENABLED}" != "0" ]]; then
  INFO_PLIST="${APP_BUNDLE}/Contents/Info.plist"
  if [[ -f "${INFO_PLIST}" ]]; then
    echo "==> Stamping app metadata in Info.plist"
    set_plist_value "${INFO_PLIST}" "CFBundleName" "string" "${APP_NAME}"
    set_plist_value "${INFO_PLIST}" "CFBundleDisplayName" "string" "${APP_DISPLAY_NAME}"
    set_plist_value "${INFO_PLIST}" "CFBundleShortVersionString" "string" "${APP_VERSION}"
    set_plist_value "${INFO_PLIST}" "CFBundleVersion" "string" "${BUILD_TAG}"
  fi
fi

echo "==> Cleaning AppleDouble metadata in app bundle"
cleanup_appledouble_tree "${APP_BUNDLE}"

if [[ "${SIGN_ENABLED}" != "0" ]]; then
  echo "==> Signing app bundle with Developer ID: ${DEVELOPER_ID}"
  codesign --force --deep --options "${CODESIGN_OPTIONS}" --timestamp \
    --sign "${DEVELOPER_ID}" "${APP_BUNDLE}"
  echo "==> Verifying codesign"
  codesign --verify --deep --strict --verbose=2 "${APP_BUNDLE}"
else
  echo "==> Ad-hoc signing app bundle (SIGN_ENABLED=0)"
  codesign --force --deep --sign - "${APP_BUNDLE}" >/dev/null 2>&1 || true
fi

mkdir -p "${RELEASE_DIR}"
echo "==> Copying app bundle to release folder"
rsync -a "${APP_BUNDLE}" "${RELEASE_DIR}/"
cleanup_appledouble_tree "${RELEASE_DIR}/${APP_NAME}.app"
RELEASE_APP="${RELEASE_DIR}/${APP_NAME}.app"

if [[ "${NOTARIZE_ENABLED}" != "0" ]]; then
  if [[ -z "${NOTARY_PROFILE}" ]]; then
    echo "NOTARIZE_ENABLED=1 but NOTARY_PROFILE is empty."
    echo "Create profile first: xcrun notarytool store-credentials <profile> ..."
    exit 1
  fi
  NOTARY_ZIP="${RELEASE_DIR}/${APP_NAME}_notary_${BUILD_TAG}.zip"
  echo "==> Preparing notarization zip: ${NOTARY_ZIP}"
  (
    cd "${RELEASE_DIR}"
    ditto -c -k --keepParent "${APP_NAME}.app" "$(basename "${NOTARY_ZIP}")"
  )
  echo "==> Submitting notarization (profile=${NOTARY_PROFILE})"
  xcrun notarytool submit "${NOTARY_ZIP}" --keychain-profile "${NOTARY_PROFILE}" --wait
  if [[ "${STAPLE_ENABLED}" != "0" ]]; then
    echo "==> Stapling notarization ticket"
    xcrun stapler staple "${RELEASE_APP}"
    xcrun stapler validate "${RELEASE_APP}" || true
  fi
fi

ZIP_PREFIX="${APP_NAME}"
if [[ "${ZIP_PREFIX}" != *"v${APP_VERSION}"* ]]; then
  ZIP_PREFIX="${ZIP_PREFIX}_v${APP_VERSION}"
fi
ZIP_NAME="${ZIP_PREFIX}_mac_${BUILD_TAG}.zip"
echo "==> Creating zip: ${ZIP_NAME}"
(
  cd "${RELEASE_DIR}"
  ditto -c -k --keepParent "${APP_NAME}.app" "${ZIP_NAME}"
)

echo
echo "Build complete."
echo "App bundle: ${RELEASE_DIR}/${APP_NAME}.app"
echo "Zip file:   ${RELEASE_DIR}/${ZIP_NAME}"
echo
