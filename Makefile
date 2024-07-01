# HWVAL Studio - developer Makefile.
#
# Linux/macOS: run GNU make from the shell.
# Windows:     run GNU make from Git Bash (MSYS2), where OS=Windows_NT is set.
#
# The virtualenv layout differs per OS: <venv>/bin/python on POSIX and
# <venv>/Scripts/python.exe on Windows.  Select the interpreter from $(OS)
# rather than from `uname -s`, which reports MINGW64_NT-10.0 under Git Bash.

# Windows: run every recipe under Git's POSIX sh, also from cmd.exe or
# PowerShell with only Git\cmd on PATH. Otherwise native make falls back to
# cmd.exe, which cannot run the recipes (quotes, pipes, find, rm -rf), and
# `sh scripts/...` is not found. Git's usr\bin goes first on PATH so find,
# sort and friends are the POSIX tools, not the Windows ones of the same name.
ifeq ($(OS),Windows_NT)
ifneq ($(origin SHELL),command line)
GIT_USR_BIN := $(firstword \
  $(if $(wildcard C:/Program?Files/Git/usr/bin/sh.exe),C:/Program?Files/Git/usr/bin) \
  $(if $(wildcard $(subst \,/,$(LOCALAPPDATA))/Programs/Git/usr/bin/sh.exe),$(subst \,/,$(LOCALAPPDATA))/Programs/Git/usr/bin) \
  $(if $(wildcard C:/msys64/usr/bin/sh.exe),C:/msys64/usr/bin))
ifneq ($(GIT_USR_BIN),)
SHELL := $(subst ?, ,$(GIT_USR_BIN))/sh.exe
export PATH := $(subst /,\,$(subst ?, ,$(GIT_USR_BIN)));$(PATH)
endif
endif
endif

VENV ?= .venv

ifeq ($(OS),Windows_NT)
# `python3` is only the Store alias on Windows; `python` is the real launcher.
PYTHON ?= python
VENV_BIN := $(VENV)/Scripts
PY := $(VENV_BIN)/python.exe
else
PYTHON ?= python3
VENV_BIN := $(VENV)/bin
PY := $(VENV_BIN)/python
endif
PIP := $(PY) -m pip

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
	@echo
	@echo "Variables: PYTHON=$(PYTHON) VENV=$(VENV) -> $(PY)"

install:
	$(PYTHON) -m venv --system-site-packages $(VENV)
	$(PIP) install -e ".[dev,packaging]"

run:
	$(PY) -m hwval_studio

cli:
	$(PY) -m hwval_studio --cli --simulate hwval --group ADC --no-report

lint:
	$(PY) -m ruff check src scripts --exclude src/hwval_studio/protocol/generated

test:
	QT_QPA_PLATFORM=offscreen $(PY) -m pytest -q tests

protocol:
	$(PY) scripts/gen_protocol.py

icons:
	$(PY) scripts/make_icons.py

# Windows runs the PowerShell packaging script (an MSI when WiX is installed,
# the one-folder dist/hwval-studio/ otherwise); macOS and Linux run their build
# scripts.  $(OS) is checked first because `uname -s` cannot distinguish Git
# Bash (MINGW64_NT-10.0) from a POSIX host.
package:
	@if ! $(PY) -c 'import PyInstaller' >/dev/null 2>&1; then \
	  echo "Packaging dependencies are missing; running 'make install'."; \
	  "$(MAKE)" install; \
	fi
	@if [ "$(OS)" = "Windows_NT" ]; then \
	   echo "Package: Windows one-folder build and MSI (WiX) via packaging/build-windows.ps1"; \
	   powershell -ExecutionPolicy Bypass -File packaging/build-windows.ps1; \
	 elif [ "$$(uname -s)" = "Darwin" ]; then \
	   PYTHON="$(CURDIR)/$(PY)" packaging/build-macos.sh; \
	 elif [ "$$(uname -s)" = "Linux" ]; then \
	   PYTHON="$(CURDIR)/$(PY)" packaging/build-linux.sh; \
	 else echo "package: unsupported OS ($$(uname -s)); on Windows run packaging/build-windows.ps1"; exit 1; fi

clean:
	rm -rf build dist .ruff_cache .mypy_cache
