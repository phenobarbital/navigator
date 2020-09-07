#!/usr/bin/env bash
sudo apt-get install libmemcached-dev zlib1g-dev
# first: install framework
python setup.py develop
# second: adding submodules
mkdir extensions
cd extensions
git submodule add git@github.com:phenobarbital/asyncdb.git
git submodule init
git submodule update --init --recursive --remote
# installing
pip install -e asyncdb
# installing asyncdb requirements
pip install -r asyncdb/requirements.txt
