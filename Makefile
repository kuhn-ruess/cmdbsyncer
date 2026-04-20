PYTHON ?= venv/bin/python
VERSION_FILE := application/_version.py
VERSION := $(shell $(PYTHON) -c "import runpy; print(runpy.run_path('$(VERSION_FILE)')['__version__'])")

.PHONY: help sync sync-version sync-deps version clean build check upload tag release

help:
	@echo "Available targets:"
	@echo "  make sync         - Sync version and dependencies into pyproject.toml"
	@echo "  make sync-version - Sync version into $(VERSION_FILE) and pyproject.toml from changelog/v*.md"
	@echo "  make sync-deps    - Sync [project.dependencies] in pyproject.toml from requirements.txt"
	@echo "  make version      - Print the current version ($(VERSION))"
	@echo "  make clean        - Remove build artefacts (build/, dist/, *.egg-info)"
	@echo "  make build        - sync + build sdist and wheel into dist/"
	@echo "  make check        - twine check dist/*"
	@echo "  make upload       - twine upload dist/* (uses ./.pypirc)"
	@echo "  make tag          - Create and push git tag v$(VERSION)"
	@echo "  make release      - clean + build + check + upload + tag"

version:
	@echo $(VERSION)

sync-version:
	@$(PYTHON) tools/sync_version.py

sync-deps:
	@$(PYTHON) tools/sync_deps.py

sync: sync-version sync-deps

clean:
	rm -rf build/ dist/ *.egg-info

build: clean sync
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
