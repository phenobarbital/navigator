venv:
	python3.9 -m venv .venv
	echo 'run `source .venv/bin/activate` to start develop Navigator'

develop:
	pip install wheel==0.37.0
	pip install extensions/asyncdb
	pip install navconfig==0.3.8
	pip install -e .
	python -m pip install -Ur requirements/requirements-dev.txt
	echo 'start develop Navigator'

setup:
	python -m pip install -Ur requirements/requirements-dev.txt

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

distclean:
	rm -rf .venv
