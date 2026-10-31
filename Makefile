PYTHON ?= python3

.PHONY: test lint install clean

test:
	@echo "Running MacNetLedger automated test suite..."
	PYTHONPATH=. $(PYTHON) -m unittest discover -s tests -p "test_*.py" -v

lint:
	@echo "Checking syntax..."
	$(PYTHON) -m py_compile daemon/macnetledgerd.py tests/*.py

install:
	@echo "Running macOS system installation (requires sudo)..."
	sudo ./scripts/install.sh

clean:
	rm -rf __pycache__ daemon/__pycache__ tests/__pycache__
