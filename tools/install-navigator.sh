#!/usr/bin/env bash
# ================================================================================
# Environment Installation
# for use in TROC Navigator
#
# Copyright © 2020 Jesús Lara Giménez (phenobarbital) <jesuslarag@gmail.com>
# Version: 0.1
#
#    Developed by Jesus Lara (phenobarbital) <jesuslara@phenobarbital.info>
#
#    License: GNU GPL version 3  <http://gnu.org/licenses/gpl.html>.
#    This is free software: you are free to change and redistribute it.
#    There is NO WARRANTY, to the extent permitted by law.
# ================================================================================
#
sudo apt install -y  $(cat INSTALL)
# creating environment
python3.8 -m venv .venv
# updating pip
source .venv/bin/activate -m
pip install --upgrade wheel setuptools pip
# first: install dependencies:
pip install git+https://github.com/phenobarbital/asyncdb.git#egg=asyncdb
pip install git+https://github.com/phenobarbital/NavConfig.git@main#egg=navconfig
# second: install framework
pip install -e .
# third: creating directories
mkdir static
