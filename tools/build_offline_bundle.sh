#!/usr/bin/env bash
#
# Builds an offline installation bundle of all Python dependencies and the
# default Ansible playbook collection. The result is a directory (and
# optionally a tar.gz) that a customer can install with pip on a server
# without internet access.
#
# Usage:
#   ./tools/build_offline_bundle.sh [--include-syncer | --syncer-from-git]
#                             [--syncer-only] [--include-enterprise]
#                             [--with-extras] [--with-ansible]
#                             [--with-ansible-windows]
#                             [--python-version 3.11]
#                             [--platform manylinux2014_x86_64]
#                             [--output-dir offline_bundle]
#                             [--no-archive]
#
# The bundle always ships the base Python dependencies (requirements.txt). The
# optional requirement sets are opt-in via the --with-* flags below, so a
# bundle only carries what the target deployment actually needs.
#
# Options:
#   --syncer-only             Bundle ONLY the cmdbsyncer package (no
#                             dependencies) and install it with --no-deps, so
#                             the dependencies already present on the target are
#                             kept. Needs a syncer source (--syncer-from-git or
#                             --include-syncer); ignores the --with-* flags.
#                             Ideal for updating the syncer on a locked-down
#                             host that can't fetch dependencies.
#   --with-extras             Also bundle the optional extras
#                             (requirements-extras.txt: LDAP / SQL / MCP /
#                             vmware). Not needed for normal operation.
#   --with-ansible            Also bundle Ansible for Linux/SSH targets
#                             (requirements-ansible.txt) and the playbook
#                             collection.
#   --with-ansible-windows    Also bundle the Ansible Windows deps (WinRM +
#                             Kerberos/NTLM, requirements-ansible-windows.txt);
#                             implies --with-ansible.
#   --include-syncer          Also download cmdbsyncer from PyPI into the
#                             bundle.
#   --syncer-from-git         Build the cmdbsyncer wheel from THIS local git
#                             checkout instead of downloading it from PyPI —
#                             use when you want to ship your current tree (an
#                             unreleased state) rather than a published
#                             release. Mutually exclusive with --include-syncer
#                             / --syncer-version.
#   --include-enterprise      Also download cmdbsyncer-enterprise from PyPI.
#   --syncer-version VER      Pin cmdbsyncer to exactly this version (e.g.
#                             4.1.0.dev3). Without this flag, pip picks the
#                             latest stable. Required for pre-releases — pip
#                             only installs .devN / aN / bN / rcN versions
#                             when they are pinned explicitly.
#   --enterprise-version VER  Same idea for cmdbsyncer-enterprise.
#   --python-version VER      Target Python version, e.g. 3.11
#   --platform TAG            Target platform tag, e.g. manylinux2014_x86_64
#   --output-dir DIR          Output directory (default: offline_bundle)
#   --no-archive              Do not create a tar.gz, only the directory
#
# Example (stable build for a typical Linux target, Python 3.11):
#   ./tools/build_offline_bundle.sh --include-syncer --include-enterprise \
#       --python-version 3.11 \
#       --platform manylinux2014_x86_64
#
# Example (pre-release test build):
#   ./tools/build_offline_bundle.sh \
#       --include-syncer    --syncer-version 4.1.0.dev3 \
#       --include-enterprise --enterprise-version 0.3.9.dev1
#
# Example (ship the current local checkout instead of a PyPI release):
#   ./tools/build_offline_bundle.sh --syncer-from-git \
#       --python-version 3.11 --platform manylinux2014_x86_64
#
# Example (update ONLY the syncer from the checkout, keep installed deps):
#   ./tools/build_offline_bundle.sh --syncer-from-git --syncer-only
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Absolute path to this script — the --help handler reads it with sed, and the
# script cd's into REPO_ROOT below, which would break a relative "$0".
SCRIPT_PATH="$SCRIPT_DIR/$(basename "${BASH_SOURCE[0]}")"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# --- Defaults ---------------------------------------------------------------
INCLUDE_SYNCER=0
SYNCER_FROM_GIT=0
INCLUDE_ENTERPRISE=0
SYNCER_VERSION=""
ENTERPRISE_VERSION=""
PYTHON_VERSION=""
PLATFORM=""
OUTPUT_DIR="offline_bundle"
CREATE_ARCHIVE=1
# Optional requirement sets — base (requirements.txt) is always bundled; the
# rest are opt-in so a bundle only carries what a deployment actually needs.
WITH_EXTRAS=0
WITH_ANSIBLE=0
WITH_ANSIBLE_WINDOWS=0
# Ship ONLY the cmdbsyncer package, no dependencies — for updating a syncer
# whose dependencies are already installed on the target.
SYNCER_ONLY=0

# --- Arguments --------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --include-syncer)        INCLUDE_SYNCER=1; shift ;;
        --syncer-from-git)       SYNCER_FROM_GIT=1; shift ;;
        --syncer-only)           SYNCER_ONLY=1; shift ;;
        --include-enterprise)    INCLUDE_ENTERPRISE=1; shift ;;
        --syncer-version)        SYNCER_VERSION="$2"; shift 2 ;;
        --enterprise-version)    ENTERPRISE_VERSION="$2"; shift 2 ;;
        --with-extras)           WITH_EXTRAS=1; shift ;;
        --with-ansible)          WITH_ANSIBLE=1; shift ;;
        --with-ansible-windows)  WITH_ANSIBLE_WINDOWS=1; shift ;;
        --python-version)        PYTHON_VERSION="$2"; shift 2 ;;
        --platform)              PLATFORM="$2"; shift 2 ;;
        --output-dir)            OUTPUT_DIR="$2"; shift 2 ;;
        --no-archive)            CREATE_ARCHIVE=0; shift ;;
        -h|--help)
            sed -n '2,75p' "$SCRIPT_PATH"; exit 0 ;;
        *)
            echo "Unknown argument: $1" >&2; exit 2 ;;
    esac
done

# Windows Ansible deps are useless without the Ansible base, so imply it.
if [[ $WITH_ANSIBLE_WINDOWS -eq 1 ]]; then
    WITH_ANSIBLE=1
fi

# --- Validate mutually exclusive syncer sources -----------------------------
# cmdbsyncer can come from PyPI (--include-syncer) OR the local git checkout
# (--syncer-from-git), never both — otherwise two cmdbsyncer wheels would land
# in the bundle and pip's pick would be ambiguous.
if [[ $SYNCER_FROM_GIT -eq 1 && ( $INCLUDE_SYNCER -eq 1 || -n "$SYNCER_VERSION" ) ]]; then
    echo "Choose either --include-syncer / --syncer-version (PyPI) or " \
         "--syncer-from-git (local checkout), not both." >&2
    exit 2
fi

# --syncer-only ships just the cmdbsyncer package (no dependencies), so it needs
# a syncer source and ignores the dependency-bundling flags.
if [[ $SYNCER_ONLY -eq 1 ]]; then
    if [[ $SYNCER_FROM_GIT -eq 0 && $INCLUDE_SYNCER -eq 0 ]]; then
        echo "--syncer-only needs a syncer source: add --syncer-from-git or " \
             "--include-syncer." >&2
        exit 2
    fi
    if [[ $WITH_EXTRAS -eq 1 || $WITH_ANSIBLE -eq 1 || $WITH_ANSIBLE_WINDOWS -eq 1 ]]; then
        echo "Note: --syncer-only bundles no dependencies; ignoring --with-* flags."
    fi
    WITH_EXTRAS=0; WITH_ANSIBLE=0; WITH_ANSIBLE_WINDOWS=0
fi

# --- Collect requirements ---------------------------------------------------
# Base is always bundled; extras / ansible / ansible-windows are opt-in via the
# --with-* flags so a bundle only carries what the target deployment needs.
# --syncer-only skips dependencies entirely (empty REQ_FILES).
REQ_FILES=()
if [[ $SYNCER_ONLY -eq 0 ]]; then
    REQ_FILES=(requirements.txt)
    [[ $WITH_EXTRAS -eq 1 ]]          && REQ_FILES+=(requirements-extras.txt)
    [[ $WITH_ANSIBLE -eq 1 ]]         && REQ_FILES+=(requirements-ansible.txt)
    [[ $WITH_ANSIBLE_WINDOWS -eq 1 ]] && REQ_FILES+=(requirements-ansible-windows.txt)
fi

# ${arr[@]+"${arr[@]}"} keeps an empty REQ_FILES (syncer-only) from tripping
# `set -u` on older bash (e.g. macOS 3.2).
for f in ${REQ_FILES[@]+"${REQ_FILES[@]}"}; do
    [[ -f "$f" ]] || { echo "Missing file: $f" >&2; exit 1; }
done

# The Ansible playbook collection is only shipped when Ansible is bundled.
if [[ $WITH_ANSIBLE -eq 1 && ! -d ansible ]]; then
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

for f in ${REQ_FILES[@]+"${REQ_FILES[@]}"}; do
    PIP_ARGS+=(-r "$f")
    cp "$f" "$OUTPUT_DIR/"
done

# Skip the dependency download entirely for --syncer-only (no requirements).
if [[ ${#REQ_FILES[@]} -gt 0 ]]; then
    echo "Downloading packages into $OUTPUT_DIR/packages ..."
    python3 -m pip "${PIP_ARGS[@]}"
else
    echo "Skipping dependency download (--syncer-only)."
fi

# --- Optional: ship cmdbsyncer and cmdbsyncer-enterprise from PyPI ----------
# Resolution for both packages is explicit:
#   --syncer-version / --enterprise-version on the CLI: pin exactly.
#                Deterministic, ships the requested wheel, and fails
#                loudly if the version is missing on PyPI. Required to
#                bundle a pre-release (.devN / aN / bN / rcN), since
#                pip only installs those when pinned explicitly.
#   No flag:     pip picks the latest stable from PyPI.
#
# An earlier revision had a --pre fallback that let pip pick the highest
# pre-release for unpinned packages. It looked convenient but was also
# fragile — pip's resolver behaviour around --pre depends on its config
# (PIP_NO_PRE, --user index, version) and a customer build could
# silently land on the wrong wheel. Pinning is the only path that
# reliably ships the version the operator intended.
download_from_pypi() {
    local spec="$1"     # e.g. "cmdbsyncer==4.1.0.dev1" or just "cmdbsyncer"
    local pkg_name="$2" # bare package name for the resolved-line glob
    echo "Downloading $spec and its dependencies from PyPI ..."
    local args=(download --no-cache-dir --dest "$OUTPUT_DIR/packages")
    [[ -n "$PLATFORM" ]]       && args+=(--platform "$PLATFORM" --only-binary=:all:)
    [[ -n "$PYTHON_VERSION" ]] && args+=(--python-version "$PYTHON_VERSION")
    args+=("$spec")
    python3 -m pip "${args[@]}"
    # Print the resolved version so the build log shows what actually
    # ended up in the bundle — surfaces "old version pinned somewhere"
    # immediately instead of after a customer install.
    local resolved
    resolved=$(ls "$OUTPUT_DIR/packages/" \
        | grep -iE "^${pkg_name//-/[-_]}-[0-9]" | head -1 || true)
    [[ -n "$resolved" ]] && echo "  -> resolved: $resolved"
}

if [[ $INCLUDE_SYNCER -eq 1 ]]; then
    if [[ -n "$SYNCER_VERSION" ]]; then
        download_from_pypi "cmdbsyncer==$SYNCER_VERSION" "cmdbsyncer"
    else
        download_from_pypi "cmdbsyncer" "cmdbsyncer"
    fi
fi
if [[ $INCLUDE_ENTERPRISE -eq 1 ]]; then
    if [[ -n "$ENTERPRISE_VERSION" ]]; then
        download_from_pypi "cmdbsyncer-enterprise==$ENTERPRISE_VERSION" \
                           "cmdbsyncer-enterprise"
    else
        download_from_pypi "cmdbsyncer-enterprise" "cmdbsyncer-enterprise"
    fi
fi

# --- Optional: build cmdbsyncer from the local git checkout -----------------
# Builds a wheel from THIS repo (pure-python → platform independent, so the
# --platform / --python-version flags don't apply here) and drops it in the
# same packages/ dir. install.sh then installs it from there via
# --no-index --find-links, exactly like a PyPI-sourced wheel.
#
# --no-build-isolation is deliberate: PEP 517 build isolation would otherwise
# download setuptools/wheel into a fresh build env every time — which fails on a
# host without PyPI access (the whole point of --syncer-only). Instead we build
# with the setuptools/wheel already installed in the current environment.
GIT_SYNCER_VERSION=""
if [[ $SYNCER_FROM_GIT -eq 1 ]]; then
    if ! python3 -c "import setuptools, wheel" >/dev/null 2>&1; then
        echo "Building cmdbsyncer from git needs 'setuptools' and 'wheel' in the" \
             "current Python environment (build isolation is disabled to avoid" \
             "PyPI downloads). Install them once with: pip install setuptools wheel" >&2
        exit 1
    fi
    echo "Building cmdbsyncer wheel from local git checkout ($REPO_ROOT) ..."
    python3 -m pip wheel --no-deps --no-build-isolation --no-cache-dir \
        --wheel-dir "$OUTPUT_DIR/packages" "$REPO_ROOT"
    GIT_SYNCER_WHEEL=$(ls "$OUTPUT_DIR/packages/" \
        | grep -iE '^cmdbsyncer-[0-9]' | head -1 || true)
    if [[ -z "$GIT_SYNCER_WHEEL" ]]; then
        echo "Failed to build cmdbsyncer wheel from the checkout." >&2
        exit 1
    fi
    GIT_SYNCER_VERSION=$(echo "$GIT_SYNCER_WHEEL" | sed -E 's/^cmdbsyncer-([^-]+)-.*/\1/')
    echo "  -> built: $GIT_SYNCER_WHEEL (version $GIT_SYNCER_VERSION)"
fi

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
# ship a copy here and let install.sh place it in $ANSIBLE_TARGET. Only when
# Ansible support is bundled (--with-ansible).
if [[ $WITH_ANSIBLE -eq 1 ]]; then
    echo "Bundling Ansible playbook collection ..."
    cp -R ansible "$OUTPUT_DIR/ansible"
fi

# --- Customer-facing install script -----------------------------------------
# Mirror the same pinning into install.sh so the customer's pip lands on
# the same wheel we just bundled. With ==X.Y.Z (or ==X.Y.Z.devN) pip
# happily installs pre-releases too.
EXTRA_PACKAGES=""
if [[ $INCLUDE_SYNCER -eq 1 ]]; then
    if [[ -n "$SYNCER_VERSION" ]]; then
        EXTRA_PACKAGES+=" cmdbsyncer==$SYNCER_VERSION"
    else
        EXTRA_PACKAGES+=" cmdbsyncer"
    fi
elif [[ $SYNCER_FROM_GIT -eq 1 ]]; then
    # Pin to the exact version we just built from the checkout so pip installs
    # that wheel from packages/ and not some other cmdbsyncer artifact.
    EXTRA_PACKAGES+=" cmdbsyncer==$GIT_SYNCER_VERSION"
fi
if [[ $INCLUDE_ENTERPRISE -eq 1 ]]; then
    if [[ -n "$ENTERPRISE_VERSION" ]]; then
        EXTRA_PACKAGES+=" cmdbsyncer-enterprise==$ENTERPRISE_VERSION"
    else
        EXTRA_PACKAGES+=" cmdbsyncer-enterprise"
    fi
fi
INSTALL_EXTRA_LINE=""
if [[ -n "$EXTRA_PACKAGES" ]]; then
    INSTALL_EXTRA_LINE="PIP_ARGS+=($EXTRA_PACKAGES)"
fi

cat > "$OUTPUT_DIR/install.sh" <<'EOS'
#!/usr/bin/env bash
# Offline installer: installs the bundled Python package(s) and, when present,
# copies the Ansible playbook collection into ANSIBLE_TARGET (default
# /opt/cmdbsyncer/ansible). Override by exporting ANSIBLE_TARGET=/path
# before running this script. Set SKIP_ANSIBLE=1 to skip the playbook
# copy entirely. Both steps run independently — a failure in one is
# reported but never silently swallows the other.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANSIBLE_TARGET="${ANSIBLE_TARGET:-/opt/cmdbsyncer/ansible}"

EOS

# The pip invocation differs for a syncer-only bundle: no requirement files are
# shipped, and cmdbsyncer is installed with --no-deps so the dependencies
# already present on the target are kept untouched.
if [[ $SYNCER_ONLY -eq 1 ]]; then
    cat >> "$OUTPUT_DIR/install.sh" <<'EOS'
PIP_ARGS=(install --no-index --find-links "$HERE/packages" --no-deps --upgrade)
EOS
else
    cat >> "$OUTPUT_DIR/install.sh" <<'EOS'
REQ_FILES=(requirements.txt)
[[ -f "$HERE/requirements-extras.txt"          ]] && REQ_FILES+=(requirements-extras.txt)
[[ -f "$HERE/requirements-ansible.txt"         ]] && REQ_FILES+=(requirements-ansible.txt)
[[ -f "$HERE/requirements-ansible-windows.txt" ]] && REQ_FILES+=(requirements-ansible-windows.txt)

PIP_ARGS=(install --no-index --find-links "$HERE/packages" --upgrade)
for f in "${REQ_FILES[@]}"; do PIP_ARGS+=(-r "$HERE/$f"); done
EOS
fi

# Inject the optional extra-packages line (cmdbsyncer / cmdbsyncer-enterprise
# wheels), produced earlier from --include-syncer / --syncer-from-git /
# --include-enterprise.
if [[ -n "$INSTALL_EXTRA_LINE" ]]; then
    echo "$INSTALL_EXTRA_LINE" >> "$OUTPUT_DIR/install.sh"
fi

cat >> "$OUTPUT_DIR/install.sh" <<'EOS'

PIP_OK=1
ANSIBLE_OK=1

echo "=== Step 1/2: installing Python packages ==="
python3 -m pip "${PIP_ARGS[@]}" || PIP_OK=0

echo ""
echo "=== Step 2/2: copying Ansible playbooks to $ANSIBLE_TARGET ==="
if [[ "${SKIP_ANSIBLE:-0}" == "1" ]]; then
    echo "Skipped (SKIP_ANSIBLE=1)."
elif [[ ! -d "$HERE/ansible" ]]; then
    echo "Skipped: bundle has no ansible/ directory."
else
    rm -rf "$ANSIBLE_TARGET" \
        && mkdir -p "$(dirname "$ANSIBLE_TARGET")" \
        && cp -R "$HERE/ansible" "$ANSIBLE_TARGET" \
        || ANSIBLE_OK=0
    if [[ "$ANSIBLE_OK" == "1" ]]; then
        echo "Playbooks installed to $ANSIBLE_TARGET."
        echo "Point cmdbsyncer at them by setting CMDBSYNCER_ANSIBLE_DIR=$ANSIBLE_TARGET"
        echo "or ANSIBLE_DIR='$ANSIBLE_TARGET' in local_config.py."
    else
        echo "ERROR: failed to copy playbooks to $ANSIBLE_TARGET — see output above."
    fi
fi

echo ""
if [[ "$PIP_OK" == "1" && "$ANSIBLE_OK" == "1" ]]; then
    echo "Installation complete."
else
    echo "Installation finished with errors:"
    [[ "$PIP_OK" != "1" ]]    && echo "  - pip install failed (see Step 1/2)"
    [[ "$ANSIBLE_OK" != "1" ]] && echo "  - ansible copy failed (see Step 2/2)"
    exit 1
fi
EOS
chmod +x "$OUTPUT_DIR/install.sh"

# --- README -----------------------------------------------------------------
if [[ $SYNCER_FROM_GIT -eq 1 ]]; then
    SYNCER_SOURCE="local git checkout (version $GIT_SYNCER_VERSION)"
elif [[ $INCLUDE_SYNCER -eq 1 ]]; then
    SYNCER_SOURCE="PyPI${SYNCER_VERSION:+ ==$SYNCER_VERSION}"
else
    SYNCER_SOURCE="not bundled (install separately)"
fi
if [[ $WITH_ANSIBLE -eq 1 ]]; then
    ANSIBLE_SOURCE="ansible/ (default install target /opt/cmdbsyncer/ansible)"
else
    ANSIBLE_SOURCE="not bundled (build with --with-ansible)"
fi
if [[ $SYNCER_ONLY -eq 1 ]]; then
    REQ_SUMMARY="none — syncer only, installed with --no-deps (existing dependencies kept)"
else
    REQ_SUMMARY="${REQ_FILES[*]}"
fi

cat > "$OUTPUT_DIR/README.txt" <<EOS
Offline installation bundle
===========================

Built on       : $(date -u +"%Y-%m-%d %H:%M:%S UTC")
Python version : ${PYTHON_VERSION:-build host default}
Platform       : ${PLATFORM:-build host default}
Included files : ${REQ_SUMMARY}
cmdbsyncer     : ${SYNCER_SOURCE}
Ansible        : ${ANSIBLE_SOURCE}

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
                              An existing directory is replaced.
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
