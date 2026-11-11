PYTHON ?= python3
VENV ?= .venv

.PHONY: help install run cli lint test protocol icons package clean

help:
	@echo "install   create a venv and install the project"
	@echo "run       start the GUI"
	@echo "cli       run the simulator CLI (ADC group)"
	@echo "lint      ruff check on the application sources"
	@echo "test      run the pytest suite headless"
	@echo "protocol  regenerate the Python HWLINK bindings (needs flatc)"
	@echo "icons     render the SVG app icon sources"
	@echo "package   build the package for the current OS"

install:
	$(PYTHON) -m venv --system-site-packages $(VENV)
	$(VENV)/bin/pip install -e ".[dev,packaging]"

run:
	$(VENV)/bin/hwval-studio

cli:
	$(VENV)/bin/hwval-studio --cli --simulate hwval --group ADC --no-report

lint:
	$(VENV)/bin/python -m ruff check src scripts --exclude src/hwval_studio/protocol/generated

test:
	QT_QPA_PLATFORM=offscreen $(VENV)/bin/python -m pytest -q tests

protocol:
	$(VENV)/bin/python scripts/gen_protocol.py

icons:
	$(VENV)/bin/python scripts/make_icons.py

package:
	@if ! "$(VENV)/bin/python" -c 'import PyInstaller' >/dev/null 2>&1; then \
	  echo "Packaging dependencies are missing; running 'make install'."; \
	  $(MAKE) install; \
	fi
	@if [ "$$(uname -s)" = "Darwin" ]; then \
	   PYTHON="$(CURDIR)/$(VENV)/bin/python" packaging/build-macos.sh; \
	 elif [ "$$(uname -s)" = "Linux" ]; then \
	   PYTHON="$(CURDIR)/$(VENV)/bin/python" packaging/build-linux.sh; \
	 else echo "On Windows run packaging\\build-windows.ps1"; exit 1; fi

clean:
	rm -rf build dist .ruff_cache .mypy_cache
