#!/usr/bin/env bash
#
# Builds an offline installation bundle of all Python dependencies and the
# default Ansible playbook collection. The result is a directory (and
# optionally a tar.gz) that a customer can install with pip on a server
# without internet access.
#
# Usage:
#   ./tools/build_offline_bundle.sh [--include-syncer] [--include-enterprise]
#                             [--python-version 3.11]
#                             [--platform manylinux2014_x86_64]
#                             [--output-dir offline_bundle]
#                             [--no-archive]
#
# Options:
#   --include-syncer      Also download cmdbsyncer from PyPI into the bundle
#   --include-enterprise  Also download cmdbsyncer-enterprise from PyPI
#   --pre                 Allow pre-releases (.devN / aN / bN / rcN) when
#                         resolving cmdbsyncer / cmdbsyncer-enterprise from
#                         PyPI. Use this to bundle a Test-Build for QA.
#   --python-version      Target Python version, e.g. 3.11
#   --platform            Target platform tag, e.g. manylinux2014_x86_64
#   --output-dir DIR      Output directory (default: offline_bundle)
#   --no-archive          Do not create a tar.gz, only the directory
#
# Example (typical Linux target server, Python 3.11):
#   ./tools/build_offline_bundle.sh --include-syncer --include-enterprise \
#       --python-version 3.11 \
#       --platform manylinux2014_x86_64
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# --- Defaults ---------------------------------------------------------------
INCLUDE_SYNCER=0
INCLUDE_ENTERPRISE=0
ALLOW_PRE=0
PYTHON_VERSION=""
PLATFORM=""
OUTPUT_DIR="offline_bundle"
CREATE_ARCHIVE=1

# --- Arguments --------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --include-syncer)      INCLUDE_SYNCER=1; shift ;;
        --include-enterprise)  INCLUDE_ENTERPRISE=1; shift ;;
        --pre)                 ALLOW_PRE=1; shift ;;
        --python-version)      PYTHON_VERSION="$2"; shift 2 ;;
        --platform)            PLATFORM="$2"; shift 2 ;;
        --output-dir)          OUTPUT_DIR="$2"; shift 2 ;;
        --no-archive)          CREATE_ARCHIVE=0; shift ;;
        -h|--help)
            sed -n '2,30p' "$0"; exit 0 ;;
        *)
            echo "Unknown argument: $1" >&2; exit 2 ;;
    esac
done

# --- Collect requirements ---------------------------------------------------
# Always bundle base + extras + ansible. An offline bundle is meant to be a
# complete installable artifact; cherry-picking sub-requirement-files just
# leaves the customer guessing which optional features they have.
REQ_FILES=(requirements.txt requirements-extras.txt requirements-ansible.txt)

for f in "${REQ_FILES[@]}"; do
    [[ -f "$f" ]] || { echo "Missing file: $f" >&2; exit 1; }
done

if [[ ! -d ansible ]]; then
    echo "Missing ansible/ directory in repo root — cannot bundle playbooks." >&2
    exit 1
fi

# --- Clean output directory -------------------------------------------------
if [[ -d "$OUTPUT_DIR" ]]; then
    echo "Removing previous output directory: $OUTPUT_DIR"
    rm -rf "$OUTPUT_DIR"
fi
mkdir -p "$OUTPUT_DIR/packages"

# --- pip download arguments -------------------------------------------------
# --no-cache-dir prevents pip from reusing an older wheel that's still in
# ~/.cache/pip when a newer release is on the index. Without it, rebuilds
# silently ship the cached version.
PIP_ARGS=(download --no-cache-dir --dest "$OUTPUT_DIR/packages")

# When a target platform is specified, source distributions cannot be
# resolved locally. --only-binary :all: forces wheels for every package.
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

echo "Downloading packages into $OUTPUT_DIR/packages ..."
python3 -m pip "${PIP_ARGS[@]}"

# --- Optional: ship cmdbsyncer and cmdbsyncer-enterprise from PyPI ----------
# These packages may pull in transitive dependencies that are not listed
# in requirements.txt (e.g. cmdbsyncer-enterprise depends on authlib), so
# we intentionally resolve the full dependency tree here.
download_from_pypi() {
    local pkg="$1"
    echo "Downloading $pkg and its dependencies from PyPI ..."
    local args=(download --no-cache-dir --dest "$OUTPUT_DIR/packages")
    [[ -n "$PLATFORM" ]]       && args+=(--platform "$PLATFORM" --only-binary=:all:)
    [[ -n "$PYTHON_VERSION" ]] && args+=(--python-version "$PYTHON_VERSION")
    # --pre tells pip to consider .devN / aN / bN / rcN releases when
    # picking a version. Only needed for cmdbsyncer / cmdbsyncer-enterprise
    # — the requirement files are version-pinned and unaffected.
    [[ $ALLOW_PRE -eq 1 ]]     && args+=(--pre)
    args+=("$pkg")
    python3 -m pip "${args[@]}"
    # Print the resolved version so the build log shows what actually
    # ended up in the bundle — surfaces "old version pinned somewhere"
    # immediately instead of after a customer install.
    local resolved
    resolved=$(ls "$OUTPUT_DIR/packages/" \
        | grep -iE "^${pkg//-/[-_]}-[0-9]" | head -1 || true)
    [[ -n "$resolved" ]] && echo "  -> resolved: $resolved"
}

[[ $INCLUDE_SYNCER     -eq 1 ]] && download_from_pypi "cmdbsyncer"
[[ $INCLUDE_ENTERPRISE -eq 1 ]] && download_from_pypi "cmdbsyncer-enterprise"

# --- Convert any remaining source distributions to wheels -------------------
# pip install --no-index refuses to build sdists on the target because the
# isolated build environment cannot fetch setuptools/wheel. Build every
# sdist into a wheel here instead, so only .whl files ship in the bundle.
shopt -s nullglob
SDISTS=("$OUTPUT_DIR"/packages/*.tar.gz "$OUTPUT_DIR"/packages/*.zip)
shopt -u nullglob
if (( ${#SDISTS[@]} > 0 )); then
    echo "Converting ${#SDISTS[@]} source distribution(s) to wheels ..."
    for f in "${SDISTS[@]}"; do
        python3 -m pip wheel --no-deps --wheel-dir "$OUTPUT_DIR/packages" "$f"
        rm -f "$f"
    done
fi

# --- Bundle the Ansible playbook collection ---------------------------------
# The pip-installed cmdbsyncer package does not contain the ansible/ tree;
# operators normally fetch it via `cmdbsyncer sys install_playbooks`, which
# git-clones from GitHub. That is unreachable in an air-gapped install, so
# ship a copy here and let install.sh place it in $ANSIBLE_TARGET.
echo "Bundling Ansible playbook collection ..."
cp -R ansible "$OUTPUT_DIR/ansible"

# --- Customer-facing install script -----------------------------------------
EXTRA_PACKAGES=""
[[ $INCLUDE_SYNCER     -eq 1 ]] && EXTRA_PACKAGES+=" cmdbsyncer"
[[ $INCLUDE_ENTERPRISE -eq 1 ]] && EXTRA_PACKAGES+=" cmdbsyncer-enterprise"
INSTALL_EXTRA_LINE=""
if [[ -n "$EXTRA_PACKAGES" ]]; then
    # When the bundle carries a pre-release wheel (.devN / rcN / …) pip
    # refuses to pick it for an unpinned ``cmdbsyncer`` request unless
    # --pre is on, even with --no-index. Propagate the flag so the
    # generated install.sh resolves the bundled wheel.
    INSTALL_EXTRA_LINE="PIP_ARGS+=($EXTRA_PACKAGES)"
    [[ $ALLOW_PRE -eq 1 ]] && INSTALL_EXTRA_LINE="PIP_ARGS+=(--pre$EXTRA_PACKAGES)"
fi

cat > "$OUTPUT_DIR/install.sh" <<'EOS'
#!/usr/bin/env bash
# Offline installer: installs every bundled Python package and copies the
# Ansible playbook collection into ANSIBLE_TARGET (default
# /opt/cmdbsyncer/ansible). Override by exporting ANSIBLE_TARGET=/path
# before running this script. Set FORCE=1 to overwrite an existing
# playbook directory; set SKIP_ANSIBLE=1 to skip the playbook copy.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANSIBLE_TARGET="${ANSIBLE_TARGET:-/opt/cmdbsyncer/ansible}"

REQ_FILES=(requirements.txt)
[[ -f "$HERE/requirements-extras.txt"  ]] && REQ_FILES+=(requirements-extras.txt)
[[ -f "$HERE/requirements-ansible.txt" ]] && REQ_FILES+=(requirements-ansible.txt)

PIP_ARGS=(install --no-index --find-links "$HERE/packages" --upgrade)
for f in "${REQ_FILES[@]}"; do PIP_ARGS+=(-r "$HERE/$f"); done
EOS

# Inject the optional extra-packages line (cmdbsyncer / cmdbsyncer-enterprise
# wheels), produced earlier from --include-syncer / --include-enterprise.
if [[ -n "$INSTALL_EXTRA_LINE" ]]; then
    echo "$INSTALL_EXTRA_LINE" >> "$OUTPUT_DIR/install.sh"
fi

cat >> "$OUTPUT_DIR/install.sh" <<'EOS'

python3 -m pip "${PIP_ARGS[@]}"

# --- Ansible playbook collection -------------------------------------------
if [[ "${SKIP_ANSIBLE:-0}" == "1" ]]; then
    echo "Skipping Ansible playbook install (SKIP_ANSIBLE=1)."
elif [[ ! -d "$HERE/ansible" ]]; then
    echo "Bundle has no ansible/ directory — skipping playbook install."
else
    if [[ -e "$ANSIBLE_TARGET" && "${FORCE:-0}" != "1" ]]; then
        echo "Refusing to overwrite existing $ANSIBLE_TARGET (set FORCE=1 to replace)."
    else
        echo "Installing Ansible playbooks to $ANSIBLE_TARGET ..."
        rm -rf "$ANSIBLE_TARGET"
        mkdir -p "$(dirname "$ANSIBLE_TARGET")"
        cp -R "$HERE/ansible" "$ANSIBLE_TARGET"
        echo "Playbooks installed to $ANSIBLE_TARGET."
        echo "Point cmdbsyncer at them by setting CMDBSYNCER_ANSIBLE_DIR=$ANSIBLE_TARGET"
        echo "or ANSIBLE_DIR='$ANSIBLE_TARGET' in local_config.py."
    fi
fi

echo "Installation complete."
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
Ansible        : ansible/ (default install target /opt/cmdbsyncer/ansible)

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

Customising the install
-----------------------
- ANSIBLE_TARGET=/path        Where to copy the playbook collection.
                              Defaults to /opt/cmdbsyncer/ansible.
- FORCE=1                     Overwrite an existing ANSIBLE_TARGET.
- SKIP_ANSIBLE=1              Skip the playbook copy entirely.

After installing, point cmdbsyncer at the playbooks via either
CMDBSYNCER_ANSIBLE_DIR=<path> in the environment, or ANSIBLE_DIR=<path>
in local_config.py.

Notes
-----
- The packages only match the Python version and platform they were
  built for. If these do not match, pip will report an incompatibility
  error.
- For packages with C extensions (e.g. python-ldap), the target system
  may need the corresponding system headers installed if a source
  distribution was shipped instead of a wheel.
EOS

# --- Build the archive ------------------------------------------------------
if [[ $CREATE_ARCHIVE -eq 1 ]]; then
    ARCHIVE="${OUTPUT_DIR}.tar.gz"
    echo "Creating archive: $ARCHIVE"
    tar -czf "$ARCHIVE" "$OUTPUT_DIR"
    echo "Done: $ARCHIVE ($(du -h "$ARCHIVE" | cut -f1))"
else
    echo "Done: $OUTPUT_DIR ($(du -sh "$OUTPUT_DIR" | cut -f1))"
fi
