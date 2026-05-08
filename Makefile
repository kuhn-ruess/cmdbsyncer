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
	@echo "  make release-pre  - bump pyproject pre-release counter (.devN/aN/bN/rcN),"
	@echo "                      then clean + build + check + upload (no tag)"

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

# Pre-release ship-it: bumps pyproject.toml's trailing pre-release counter
# (.devN / aN / bN / rcN) and uploads to PyPI as a pre-release. pip ignores
# pre-releases unless invoked with --pre, so this does not affect normal
# users. The bump is left uncommitted on purpose — the operator decides
# whether to commit-and-push the version bump after a successful upload.
release-pre:
	$(PYTHON) tools/bump_pre_release.py pyproject.toml
	$(MAKE) clean build check upload
	@v=$$(grep -E '^version\s*=' pyproject.toml | head -1 | sed -E 's/.*"([^"]+)".*/\1/'); \
	echo "Pre-release $$v uploaded to PyPI."; \
	echo "pyproject.toml was bumped — review and commit when ready:"; \
	echo "    git add pyproject.toml && git commit -m \"RELEASE: pre-release $$v\""
