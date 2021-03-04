.venv:
	python3.8 -m venv .venv
	source .venv/bin/activate && make setup dev
	echo 'run `source .venv/bin/activate` to start develop Navigator'

develop:
	source .venv/bin/activate && make setup dev
	echo 'start develop Navigator'

venv: .venv

setup:
	python -m pip install -Ur docs/requirements-dev.txt

dev:
	flit install --symlink

release: lint test clean
	flit publish

format:
	python -m black navigator

lint:
	python -m pylint --rcfile .pylint navigator/*.py
	python -m pylint --rcfile .pylint navigator/libs/*.py
	python -m black --check navigator

test:
	python -m coverage run -m navigator.tests
	python -m coverage report
	python -m mypy navigator/*.py

distclean: clean
	rm -rf .venv
