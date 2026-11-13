PYTHON ?= venv/bin/python
VERSION_FILE := application/_version.py
# Build the next X.Y.Z.devN (N from PyPI) while the changelog still has an
# open "## Unreleased" section, the plain version otherwise.
DEV ?= $(shell $(PYTHON) -c "import runpy; print(1 if runpy.run_path('$(VERSION_FILE)')['_has_unreleased_entries']() else '')")
VERSION := $(shell $(PYTHON) -c "import runpy; print(runpy.run_path('$(VERSION_FILE)')['__version__'])")

.PHONY: help version clean build check upload tag release release-pre

help:
	@echo "Available targets:"
	@echo "  make version      - Print the current version ($(VERSION))"
	@echo "  make clean        - Remove build artefacts (build/, dist/, *.egg-info)"
	@echo "  make build        - Build sdist and wheel into dist/, as the next"
	@echo "                      X.Y.Z.devN while ## Unreleased is open"
	@echo "  make check        - twine check dist/*"
	@echo "  make upload       - twine upload dist/* (uses ./.pypirc)"
	@echo "  make tag          - Create and push git tag v$(VERSION)"
	@echo "  make release      - clean + build + check + upload + tag"
	@echo "  make release-pre  - upload the next X.Y.Z.devN pre-release to PyPI"
	@echo "                      (N from PyPI, pyproject.toml unchanged, no tag)"

version:
	@echo $(VERSION)

clean:
	rm -rf build/ dist/ *.egg-info

build: clean
	@if [ -z "$(DEV)" ]; then $(PYTHON) -m build; exit $$?; fi; \
	cp pyproject.toml pyproject.toml.orig; \
	trap 'mv pyproject.toml.orig pyproject.toml' EXIT; \
	$(PYTHON) tools/bump_pre_release.py pyproject.toml && \
	$(PYTHON) -m build

check:
	$(PYTHON) -m twine check dist/*

upload:
	$(PYTHON) -m twine upload --config-file ./.pypirc dist/*

tag:
	@v=$$($(PYTHON) -c "import runpy; print(runpy.run_path('$(VERSION_FILE)')['__version__'])"); \
	git tag -a v$$v -m "Release $$v" && \
	git push origin v$$v

# A final release never becomes a .devN, even with Unreleased still open.
release: DEV :=
release: build check upload tag
	@v=$$($(PYTHON) -c "import runpy; print(runpy.run_path('$(VERSION_FILE)')['__version__'])"); \
	echo "Released $$v to PyPI"

# Pre-release ship-it for main: builds the next X.Y.Z.devN of the version
# in pyproject.toml (N = highest .devN already on PyPI + 1) and uploads it.
# pip ignores pre-releases unless invoked with --pre, so this does not
# affect normal users. pyproject.toml is restored afterwards, so there is
# nothing to commit.
release-pre:
	@$(MAKE) build check upload DEV=1 && \
	echo "Pre-release $$(ls dist/*.whl | sed -E 's/.*-([^-]+)-py3.*/\1/') uploaded to PyPI (install with: pip install --pre cmdbsyncer)."
