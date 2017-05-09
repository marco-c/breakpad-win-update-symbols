#!/bin/sh

set -v -e -x

hg clone https://hg.mozilla.org/users/tmielczarek_mozilla.com/fetch-win32-symbols/
cd fetch-win32-symbols
./run.sh
