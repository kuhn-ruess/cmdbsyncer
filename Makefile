PYTHON ?= venv/bin/python
VERSION_FILE := application/_version.py
VERSION := $(shell $(PYTHON) -c "import runpy; print(runpy.run_path('$(VERSION_FILE)')['__version__'])")

.PHONY: help version clean build check upload tag release

help:
	@echo "Available targets:"
	@echo "  make version      - Print the current version ($(VERSION))"
	@echo "  make clean        - Remove build artefacts (build/, dist/, *.egg-info)"
	@echo "  make build        - Build sdist and wheel into dist/"
	@echo "  make check        - twine check dist/*"
	@echo "  make upload       - twine upload dist/* (uses ./.pypirc)"
	@echo "  make tag          - Create and push git tag v$(VERSION)"
	@echo "  make release      - clean + build + check + upload + tag"

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
