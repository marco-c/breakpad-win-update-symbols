#!/bin/sh

set -v -e -x

base="$(realpath $(dirname $0))"

cd /home/user/dump_syms
if test -n "$LOCAL"; then
    EXTRA="--authentication-file=/home/user/luser/tooltool-download-token"
else
    EXTRA="--url=http://taskcluster/tooltool.mozilla-releng.net/"
fi
python ../tooltool.py -v ${EXTRA} -m dump-syms.manifest fetch
/opt/wine-staging/bin/regsvr32 msdia120.dll

cd ..

mkdir -p artifacts
PYTHONPATH=$PWD python "${base}/symsrv-fetch.py" artifacts/target.crashreporter-symbols.zip
