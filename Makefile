PYTHON ?= venv/bin/python
VERSION_FILE := application/_version.py
VERSION := $(shell $(PYTHON) -c "import runpy; print(runpy.run_path('$(VERSION_FILE)')['__version__'])")

.PHONY: help version clean build check upload tag release release-pre

help:
	@echo "Available targets:"
	@echo "  make version      - Print the current version ($(VERSION))"
	@echo "  make clean        - Remove build artefacts (build/, dist/, *.egg-info)"
	@echo "  make build        - Build sdist and wheel into dist/"
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
	$(PYTHON) -m build

check:
	$(PYTHON) -m twine check dist/*

upload:
	$(PYTHON) -m twine upload --config-file ./.pypirc dist/*

tag:
	@v=$$($(PYTHON) -c "import runpy; print(runpy.run_path('$(VERSION_FILE)')['__version__'])"); \
	git tag -a v$$v -m "Release $$v" && \
	git push origin v$$v

release: build check upload tag
	@v=$$($(PYTHON) -c "import runpy; print(runpy.run_path('$(VERSION_FILE)')['__version__'])"); \
	echo "Released $$v to PyPI"

# Pre-release ship-it for main: builds the next X.Y.Z.devN of the version
# in pyproject.toml (N = highest .devN already on PyPI + 1) and uploads it.
# pip ignores pre-releases unless invoked with --pre, so this does not
# affect normal users. pyproject.toml is restored afterwards, so there is
# nothing to commit.
release-pre:
	@cp pyproject.toml pyproject.toml.orig; \
	trap 'mv pyproject.toml.orig pyproject.toml' EXIT; \
	$(PYTHON) tools/bump_pre_release.py pyproject.toml && \
	v=$$(grep -E '^version\s*=' pyproject.toml | head -1 | sed -E 's/.*"([^"]+)".*/\1/') && \
	$(MAKE) clean build check upload && \
	echo "Pre-release $$v uploaded to PyPI (install with: pip install --pre cmdbsyncer)."
