# Releases & Versioning

CMDBsyncer uses a **Release-Train** model on `main`: changes land continuously, and a new version (tag + PyPI release) is cut 1–2× per week — not per commit. In parallel, a **long-term-support branch `lts/3.12`** receives only security fixes and general bugfixes backported from `main` — no new features.

## For users — which version should I run?

### Git checkout

- **`lts/3.12` branch** — long-term-support line. Receives only security fixes and general bugfixes, no new features. Best for production. Move forward with `git pull`.
  ```bash
  git checkout lts/3.12
  git pull
  ```
- **Tag `vX.Y.Z`** — a pinned, reproducible release. Best for deployments that must not shift.
  ```bash
  git fetch --tags
  git checkout v3.12.13
  ```
- **`main`** — rolling development with new features. Contains an `## Unreleased` section in the changelog with work that has not yet been cut into a release. Not recommended for production.

### Docker / Docker Compose

The Docker image is built from the repo source (`Dockerfile`), so the version you run is determined by the branch or tag you cloned. Check out `lts/3.12` (or a specific tag) **before** building the image:

```bash
git clone https://github.com/kuhn-ruess/cmdbsyncer.git
cd cmdbsyncer
git checkout lts/3.12         # or: git checkout v3.12.13
./helper up                   # builds and starts the image
```

After a release you want to pick up, update on the host running Docker:

```bash
git checkout lts/3.12
git pull
./helper up --build
```

### pip / PyPI

Every tagged release is published to PyPI. `pip install cmdbsyncer` always pulls the newest release; pin a specific version with `pip install cmdbsyncer==3.12.13`.

## For maintainers — cutting a release

Commits on `main` accumulate changelog bullets under `## Unreleased` at the top of the newest `changelog/v*.md` file. A release cut turns those bullets into a real version.

### 1. Accumulate on `main`

Every meaningful commit adds a bullet under `## Unreleased` — do not create a new `## Version x.y.z` header per commit. Prefixes: `SEC:`, `FIX:`, `FEAT:`.

### 2. Cut the release

When it's time to ship (triggered by the maintainer, typically 1–2× per week):

```bash
# 1. Rename "## Unreleased" → "## Version 3.13.0" in the current changelog/v*.md
#    (manual edit)

# 2. Propagate the version into _version.py + pyproject.toml
make sync-version

# 3. Commit the release
git add changelog/v*.md application/_version.py pyproject.toml
git commit -m "Version 3.13.0"

# 4. Annotated tag
git tag -a v3.13.0 -m "Version 3.13.0"

# 5. Push tag (main moves on its own cadence)
git push origin v3.13.0
```

### 3. Open a new `## Unreleased` section

The next commit on `main` that adds a changelog bullet re-opens an `## Unreleased` section at the top of the current `changelog/v*.md`.

### 4. Publish to PyPI

```bash
make release   # clean + build + check + upload + tag
```

(`make release` already builds from the synced version and re-pushes the tag if needed.)

## For maintainers — the LTS branch

The **`lts/3.12`** branch is the long-term-support line based on `v3.12.13`. It only receives:

- **Security fixes** (`SEC:` prefix)
- **General bugfixes** (`FIX:` prefix)

New features (`FEAT:`) never land on `lts/3.12` — they go exclusively to `main`.

### LTS version-number scheme

The LTS branch carries a marker file `.lts-release` at the repo root whose content is the `MAJOR.MINOR` LTS base line (e.g. `3.12`). When `make sync-version` runs with the marker present it picks up the newest `## Version {base}-LTS{n}` header from `changelog/v{base}.md` and writes:

- `application/_version.py` → `__version__ = "3.12-LTS1"` (shown in the UI)
- `pyproject.toml` → `version = "3.12+lts1"` (PEP 440-compliant local version identifier, so setuptools/pip still accept it)
- Git tags are `v{base}-LTS{n}` (e.g. `v3.12-LTS1`, `v3.12-LTS2`)

The LTS counter is independent from the upstream patch stream — once `main` moves past `3.12.13` with new features, sharing a patch number would be misleading. LTS releases are numbered `3.12-LTS1`, `3.12-LTS2`, … and count up with every cut.

The LTS branch **must never contain an `## Unreleased` section** — `sync_version` aborts if one is found. This is what guarantees the UI never shows `-dev` on LTS.

The `+lts` local version identifier means LTS wheels are **not uploadable to PyPI** (PyPI rejects local versions). Distribute LTS releases via git tag / `pip install git+https://…@v3.12-LTS1` or a private index.

### Backport workflow

When a fix on `main` should also ship on the LTS line:

```bash
# 1. Cherry-pick the fix commit from main onto the LTS branch
git checkout lts/3.12
git pull
git cherry-pick <commit-sha-from-main>

# 2. Resolve conflicts if needed, then verify the changelog entry. Add the
#    bullet under the current open "## Version 3.12-LTS<n>" header in
#    changelog/v3.12.md — never under "## Unreleased".

# 3. Push
git push origin lts/3.12
```

### Cutting an LTS release

On LTS, the changelog always carries an open `## Version 3.12-LTS<n>` header at the top while fixes accumulate — there is no intermediate `## Unreleased` phase. Cutting a release just means tagging the current state:

```bash
git checkout lts/3.12

# 1. Verify the current "## Version 3.12-LTS<n>" header in changelog/v3.12.md
#    is the one you want to ship (no renaming needed — the counter was already
#    opened right after the previous tag).

# 2. Sync version files (reads .lts-release + newest "-LTS<n>" header →
#    writes 3.12-LTS<n> / 3.12+lts<n>)
make sync-version

# 3. Commit + tag
git add application/_version.py pyproject.toml
git commit -m "Version 3.12-LTS<n>"
git tag -a v3.12-LTS<n> -m "Version 3.12-LTS<n>"

# 4. Push branch + tag
git push origin lts/3.12
git push origin v3.12-LTS<n>

# 5. Immediately open the next section at the top of changelog/v3.12.md:
#    ## Version 3.12-LTS<n+1>
#    (leave it empty until the next backport lands — never use ## Unreleased)
git commit -am "Open 3.12-LTS<n+1>"
git push origin lts/3.12
```

## Version scheme

- `MAJOR.MINOR.PATCH` (semver-ish).
- **PATCH** — bugfixes, small features, security fixes. Bumped on every release train.
- **MINOR** — larger feature batches; bumped when the maintainer decides a release is feature-worthy.
- **MAJOR** — breaking changes to APIs, config, or storage layout.

Version bumps are **never automatic** — only when the maintainer cuts a release.
