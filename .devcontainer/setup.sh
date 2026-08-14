#!/usr/bin/env bash
# Saikei Civil codespace provisioning.
#
# Tier 1 (always): pure-Python test env — ifcopenshell (Linux build, incl. the
#   alignment API), shapely/numpy/lark, and pytest. Enables `make test-core`
#   and the pure-math tool tests via `-p no:pytest-blender`.
# Tier 2 (opt-in, SAIKEI_INSTALL_BLENDER=1): Blender headless + pytest-blender
#   for the tool/operator tests that import `bpy`.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BONSAI_DIR="${REPO_ROOT}/src/bonsai"
log() { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }
warn() { printf '\n\033[1;33m!!  %s\033[0m\n' "$*"; }

# ---------------------------------------------------------------------------
# Tier 1 — pure-Python test environment
# ---------------------------------------------------------------------------
log "Tier 1: installing Python test dependencies"
python -m pip install --upgrade pip
# ifcopenshell ships the alignment API + a manylinux compiled wrapper as one
# self-consistent wheel. Saikei's geometry math needs shapely/numpy/lark.
python -m pip install \
  ifcopenshell \
  shapely numpy lark \
  pytest pytest-bdd pygments \
  black ruff

log "Verifying ifcopenshell + alignment API import"
if python - <<'PY'
import ifcopenshell
import ifcopenshell.api.alignment  # noqa: F401
print("ifcopenshell", ifcopenshell.version, "+ api.alignment OK")
PY
then
  :
else
  warn "Released ifcopenshell lacks api.alignment — trying a pre-release wheel."
  python -m pip install --upgrade --pre ifcopenshell || true
  python - <<'PY' || warn "Still no api.alignment. The pip ifcopenshell may lag the repo's bundled source (VERSION $(cat "${REPO_ROOT}/VERSION" 2>/dev/null)). Core tests that touch alignment may fail until a matching Linux build is supplied."
import ifcopenshell.api.alignment  # noqa: F401
print("api.alignment OK after pre-release upgrade")
PY
fi

log "Smoke-testing bonsai.core import (via PYTHONPATH)"
PYTHONPATH="${BONSAI_DIR}" python - <<'PY' || warn "bonsai.core import failed — check PYTHONPATH and deps above."
import bonsai.core.alignment  # noqa: F401
print("bonsai.core.alignment import OK")
PY

cat <<EOF

Tier 1 ready. Run core tests from ${BONSAI_DIR}:
  cd src/bonsai
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest test/core -o "addopts=" -p no:pytest-blender -v
EOF

# ---------------------------------------------------------------------------
# Tier 2 — Blender headless (opt-in)
# ---------------------------------------------------------------------------
if [ "${SAIKEI_INSTALL_BLENDER:-0}" != "1" ]; then
  cat <<EOF

Tier 2 (Blender headless) skipped. To enable the tool/operator tests:
  1. Set the codespace env var SAIKEI_INSTALL_BLENDER=1
     (devcontainer.json containerEnv, or a Codespaces secret), then Rebuild.
  2. Or run it now manually:  SAIKEI_INSTALL_BLENDER=1 bash .devcontainer/setup.sh
EOF
  exit 0
fi

BLENDER_VERSION="${BLENDER_VERSION:-5.0.0}"
BLENDER_SERIES="${BLENDER_VERSION%.*}"          # 5.0.0 -> 5.0
BLENDER_TARBALL="blender-${BLENDER_VERSION}-linux-x64.tar.xz"
BLENDER_URL="https://download.blender.org/release/Blender${BLENDER_SERIES}/${BLENDER_TARBALL}"
BLENDER_HOME="/opt/blender"

log "Tier 2: installing Blender ${BLENDER_VERSION} runtime libraries"
sudo apt-get update
sudo apt-get install -y --no-install-recommends \
  libxi6 libxxf86vm1 libxfixes3 libxrender1 libgl1 libglu1-mesa \
  libxkbcommon0 libsm6 libice6 xz-utils wget

if [ ! -x "${BLENDER_HOME}/blender" ]; then
  log "Downloading ${BLENDER_URL}"
  if ! wget -q "${BLENDER_URL}" -O "/tmp/${BLENDER_TARBALL}"; then
    warn "Download failed (URL may be wrong for this Blender version)."
    warn "Set BLENDER_VERSION to a build that exists under https://download.blender.org/release/ and rerun."
    exit 1
  fi
  sudo mkdir -p "${BLENDER_HOME}"
  sudo tar -xf "/tmp/${BLENDER_TARBALL}" -C "${BLENDER_HOME}" --strip-components=1
  sudo ln -sf "${BLENDER_HOME}/blender" /usr/local/bin/blender
fi
blender --version || { warn "Blender failed to launch."; exit 1; }

log "Installing pytest deps into Blender's bundled Python"
# Mirrors src/bonsai/scripts/setup_pytest.py, plus the runtime deps Saikei needs
# inside Blender (compiled ifcopenshell + geometry libs).
blender -b --python-expr "
import subprocess, sys, ensurepip
ensurepip.bootstrap()
subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--upgrade', 'pip'])
subprocess.check_call([sys.executable, '-m', 'pip', 'install',
    'pytest', 'pytest-bdd', 'pytest-blender', 'pygments',
    'ifcopenshell', 'shapely', 'numpy', 'lark'])
"

log "Symlinking bonsai into Blender's site-packages"
BLENDER_SITE="$(blender -b --python-expr "import site,sys; print(site.getsitepackages()[0])" 2>/dev/null | tail -n1)"
if [ -n "${BLENDER_SITE}" ] && [ -d "${BLENDER_SITE}" ]; then
  sudo ln -sfn "${BONSAI_DIR}/bonsai" "${BLENDER_SITE}/bonsai"
  echo "Linked ${BLENDER_SITE}/bonsai -> ${BONSAI_DIR}/bonsai"
else
  warn "Could not resolve Blender site-packages; symlink skipped."
fi

cat <<EOF

Tier 2 ready. Run tool/operator tests from ${BONSAI_DIR}:
  cd src/bonsai
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest test/tool/test_alignment.py \\
    -o "addopts=" -p pytest-blender -v --blender-executable "\$(command -v blender)"
EOF
