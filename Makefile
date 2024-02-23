venv:
	python3.10 -m venv .venv
	echo 'run `source .venv/bin/activate` to start develop Navigator'

install:
	pip install wheel==0.42.0
	pip install -e .
	echo 'start Navigator'

develop:
	pip install wheel==0.42.0
	pip install -e .
	python -m pip install -Ur requirements/requirements-dev.txt
	# add other dependencies:
	pip install --upgrade navigator-session navigator-auth
	pip install -e services/aiohttp-cors
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
