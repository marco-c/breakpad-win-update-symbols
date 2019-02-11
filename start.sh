#!/bin/sh

set -v -e -x

git clone https://github.com/marco-c/breakpad-win-update-symbols
cd breakpad-win-update-symbols
./run.sh
