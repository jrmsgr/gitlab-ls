#!/usr/bin/env bash

curr_dir=$(dirname $(realpath "$0"))

cd $curr_dir

if ! [ -f ".venv/bin/activate" ]; then
  python3 -m venv .venv &> /dev/null
  source .venv/bin/activate
  pip3 install -r ./requirements.txt &> /dev/null
else
  source .venv/bin/activate
fi
./gitlab-ls.py
