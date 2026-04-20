#!/usr/bin/env bash
#
# Builds an offline installation bundle of all Python dependencies.
# The result is a directory (and optionally a tar.gz) that a customer
# can install with pip on a server without internet access.
#
# Usage:
#   ./build_offline_bundle.sh [--extras] [--ansible] [--all]
#                             [--include-syncer]
#                             [--python-version 3.11]
#                             [--platform manylinux2014_x86_64]
#                             [--output-dir offline_bundle]
#                             [--no-archive]
#
# Options:
#   --extras           Include requirements-extras.txt (LDAP, ODBC, vmware, ...)
#   --ansible          Include requirements-ansible.txt (Kerberos, WinRM, ...)
#   --all              Shortcut for --extras --ansible
#   --include-syncer   Also download cmdbsyncer from PyPI into the bundle
#   --python-version   Target Python version, e.g. 3.11
#   --platform         Target platform tag, e.g. manylinux2014_x86_64
#   --output-dir DIR   Output directory (default: offline_bundle)
#   --no-archive       Do not create a tar.gz, only the directory
#
# Example (typical Linux target server, Python 3.11):
#   ./build_offline_bundle.sh --all --include-syncer \
#       --python-version 3.11 \
#       --platform manylinux2014_x86_64
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# --- Defaults ---------------------------------------------------------------
INCLUDE_EXTRAS=0
INCLUDE_ANSIBLE=0
INCLUDE_SYNCER=0
PYTHON_VERSION=""
PLATFORM=""
OUTPUT_DIR="offline_bundle"
CREATE_ARCHIVE=1

# --- Argumente --------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --extras)          INCLUDE_EXTRAS=1; shift ;;
        --ansible)         INCLUDE_ANSIBLE=1; shift ;;
        --all)             INCLUDE_EXTRAS=1; INCLUDE_ANSIBLE=1; shift ;;
        --include-syncer)  INCLUDE_SYNCER=1; shift ;;
        --python-version)  PYTHON_VERSION="$2"; shift 2 ;;
        --platform)        PLATFORM="$2"; shift 2 ;;
        --output-dir)      OUTPUT_DIR="$2"; shift 2 ;;
        --no-archive)      CREATE_ARCHIVE=0; shift ;;
        -h|--help)
            sed -n '2,29p' "$0"; exit 0 ;;
        *)
            echo "Unknown argument: $1" >&2; exit 2 ;;
    esac
done

# --- Requirements sammeln ---------------------------------------------------
REQ_FILES=("requirements.txt")
[[ $INCLUDE_EXTRAS  -eq 1 ]] && REQ_FILES+=("requirements-extras.txt")
[[ $INCLUDE_ANSIBLE -eq 1 ]] && REQ_FILES+=("requirements-ansible.txt")

for f in "${REQ_FILES[@]}"; do
    [[ -f "$f" ]] || { echo "Fehlende Datei: $f" >&2; exit 1; }
done

# --- Zielordner aufraeumen --------------------------------------------------
if [[ -d "$OUTPUT_DIR" ]]; then
    echo "Raeume alten Zielordner auf: $OUTPUT_DIR"
    rm -rf "$OUTPUT_DIR"
fi
mkdir -p "$OUTPUT_DIR/packages"

# --- pip download Argumente -------------------------------------------------
PIP_ARGS=(download --dest "$OUTPUT_DIR/packages")

# Wenn eine Ziel-Plattform angegeben ist, duerfen keine Quell-Distributionen
# gebaut werden. --only-binary :all: erzwingt wheels fuer ALLE Pakete.
if [[ -n "$PLATFORM" ]]; then
    PIP_ARGS+=(--platform "$PLATFORM" --only-binary=:all:)
fi
if [[ -n "$PYTHON_VERSION" ]]; then
    PIP_ARGS+=(--python-version "$PYTHON_VERSION")
fi

for f in "${REQ_FILES[@]}"; do
    PIP_ARGS+=(-r "$f")
    cp "$f" "$OUTPUT_DIR/"
done

echo "Lade Pakete herunter nach $OUTPUT_DIR/packages ..."
python3 -m pip "${PIP_ARGS[@]}"

# --- Optional: cmdbsyncer selbst von PyPI beilegen --------------------------
if [[ $INCLUDE_SYNCER -eq 1 ]]; then
    echo "Lade cmdbsyncer von PyPI ..."
    SYNCER_PIP_ARGS=(download --no-deps --dest "$OUTPUT_DIR/packages")
    [[ -n "$PLATFORM" ]]       && SYNCER_PIP_ARGS+=(--platform "$PLATFORM" --only-binary=:all:)
    [[ -n "$PYTHON_VERSION" ]] && SYNCER_PIP_ARGS+=(--python-version "$PYTHON_VERSION")
    SYNCER_PIP_ARGS+=(cmdbsyncer)
    python3 -m pip "${SYNCER_PIP_ARGS[@]}"
fi

# --- Install-Script fuer den Kunden beilegen --------------------------------
INSTALL_SYNCER_LINE=""
if [[ $INCLUDE_SYNCER -eq 1 ]]; then
    INSTALL_SYNCER_LINE='PIP_ARGS+=(cmdbsyncer)'
fi

cat > "$OUTPUT_DIR/install.sh" <<EOS
#!/usr/bin/env bash
# Offline-Installer: installiert alle mitgelieferten Python-Pakete.
set -euo pipefail
HERE="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")" && pwd)"

REQ_FILES=(requirements.txt)
[[ -f "\$HERE/requirements-extras.txt"  ]] && REQ_FILES+=(requirements-extras.txt)
[[ -f "\$HERE/requirements-ansible.txt" ]] && REQ_FILES+=(requirements-ansible.txt)

PIP_ARGS=(install --no-index --find-links "\$HERE/packages" --upgrade)
for f in "\${REQ_FILES[@]}"; do PIP_ARGS+=(-r "\$HERE/\$f"); done
${INSTALL_SYNCER_LINE}

python3 -m pip "\${PIP_ARGS[@]}"
echo "Installation abgeschlossen."
EOS
chmod +x "$OUTPUT_DIR/install.sh"

# --- README -----------------------------------------------------------------
cat > "$OUTPUT_DIR/README.txt" <<EOS
Offline installation bundle
===========================

Built on       : $(date -u +"%Y-%m-%d %H:%M:%S UTC")
Python version : ${PYTHON_VERSION:-build host default}
Platform       : ${PLATFORM:-build host default}
Included files : ${REQ_FILES[*]}

Installation
------------
1. Extract the archive on the target system.
2. Change into the extracted directory.
3. Run:        ./install.sh
   (or manual: python3 -m pip install --no-index \\
                 --find-links packages -r requirements.txt)

We recommend installing into a virtual environment:

    python3 -m venv /opt/cmdbsyncer/venv
    source /opt/cmdbsyncer/venv/bin/activate
    ./install.sh

Notes
-----
- The packages only match the Python version and platform they were
  built for. If these do not match, pip will report an incompatibility
  error.
- For packages with C extensions (e.g. python-ldap), the target system
  may need the corresponding system headers installed if a source
  distribution was shipped instead of a wheel.
EOS

# --- Archiv bauen -----------------------------------------------------------
if [[ $CREATE_ARCHIVE -eq 1 ]]; then
    ARCHIVE="${OUTPUT_DIR}.tar.gz"
    echo "Erzeuge Archiv: $ARCHIVE"
    tar -czf "$ARCHIVE" "$OUTPUT_DIR"
    echo "Fertig: $ARCHIVE ($(du -h "$ARCHIVE" | cut -f1))"
else
    echo "Fertig: $OUTPUT_DIR ($(du -sh "$OUTPUT_DIR" | cut -f1))"
fi
