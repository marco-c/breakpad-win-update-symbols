#!/bin/sh

set -v -e -x

base="$(realpath $(dirname $0))"

cd /home/user/dump_syms
if test -n "$LOCAL"; then
    EXTRA="--authentication-file=/home/user/luser/tooltool-download-token"
else
    EXTRA="--url=http://relengapi/tooltool/"
fi
python ../tooltool.py -v ${EXTRA} -m dump-syms.manifest fetch
/opt/wine-staging/bin/regsvr32 msdia120.dll

cd ..

mkdir artifacts
python "${base}/symsrv-fetch.py" -v artifacts/target.crashreporter-symbols.zip
