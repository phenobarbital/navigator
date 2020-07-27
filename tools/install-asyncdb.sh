#!/usr/bin/env bash
sudo apt-get install libmemcached-dev zlib1g-dev
# first: adding submodules
mkdir extensions
cd extensions
git submodule add git@bitbucket.org:mobileinsight1/asyncdb.git
git submodule init
git submodule update --init --recursive --remote
# installing
pip install -e asyncdb
# installing asyncdb requirements
pip install -r asyncdb/requirements.txt
