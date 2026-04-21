# Releases & Versioning

CMDBsyncer uses a **Release-Train** model: changes land continuously on `main`, and a new version (tag + PyPI release) is cut 1–2× per week — not per commit. Tags and the `stable` branch always point at a reviewed, published version.

## For users — which version should I run?

### Git checkout

- **`stable` branch** — the last published release. Best for production. Move forward with `git pull`.
  ```bash
  git checkout stable
  git pull
  ```
- **Tag `vX.Y.Z`** — a pinned, reproducible release. Best for deployments that must not shift.
  ```bash
  git fetch --tags
  git checkout v3.12.12
  ```
- **`main`** — rolling development. Contains an `## Unreleased` section in the changelog with work that has not yet been cut into a release. Not recommended for production.

### Docker / Docker Compose

The Docker image is built from the repo source (`Dockerfile`), so the version you run is determined by the branch or tag you cloned. Check out `stable` (or a specific tag) **before** building the image:

```bash
git clone https://github.com/kuhn-ruess/cmdbsyncer.git
cd cmdbsyncer
git checkout stable           # or: git checkout v3.12.12
./helper up                   # builds and starts the image
```

After a release you want to pick up, update on the host running Docker:

```bash
git checkout stable
git pull
./helper up --build
```

### pip / PyPI

Every tagged release is published to PyPI. `pip install cmdbsyncer` always pulls the newest release; pin a specific version with `pip install cmdbsyncer==3.12.12`.

## For maintainers — cutting a release

Commits on `main` accumulate changelog bullets under `## Unreleased` at the top of the newest `changelog/v*.md` file. A release cut turns those bullets into a real version.

### 1. Accumulate on `main`

Every meaningful commit adds a bullet under `## Unreleased` — do not create a new `## Version x.y.z` header per commit. Prefixes: `SEC:`, `FIX:`, `FEAT:`.

### 2. Cut the release

When it's time to ship (triggered by the maintainer, typically 1–2× per week):

```bash
# 1. Rename "## Unreleased" → "## Version 3.12.13" in changelog/v3.12.md
#    (manual edit)

# 2. Propagate the version into _version.py + pyproject.toml
make sync-version

# 3. Commit the release
git add changelog/v3.12.md application/_version.py pyproject.toml
git commit -m "Version 3.12.13"

# 4. Annotated tag
git tag -a v3.12.13 -m "Version 3.12.13"

# 5. Fast-forward the stable branch to the release commit
git branch -f stable v3.12.13

# 6. Push tag and stable branch (not main — that happens on its own cadence)
git push origin v3.12.13
git push origin stable --force-with-lease
```

### 3. Open a new `## Unreleased` section

The next commit on `main` that adds a changelog bullet re-opens an `## Unreleased` section at the top of the current `changelog/v*.md`.

### 4. Publish to PyPI

```bash
make release   # clean + build + check + upload + tag
```

(`make release` already builds from the synced version and re-pushes the tag if needed.)

## Version scheme

- `MAJOR.MINOR.PATCH` (semver-ish).
- **PATCH** — bugfixes, small features, security fixes. Bumped on every release train.
- **MINOR** — larger feature batches; bumped when the maintainer decides a release is feature-worthy.
- **MAJOR** — breaking changes to APIs, config, or storage layout.

Version bumps are **never automatic** — only when the maintainer cuts a release.
