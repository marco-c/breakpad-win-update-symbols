#!/bin/sh

set -v -e -x

: SCRIPT_URL              ${SCRIPT_URL:=https://hg.mozilla.org/users/tmielczarek_mozilla.com/fetch-win32-symbols/raw-file/tip/symsrv-fetch.py}

cd dump_syms
if test -n "$LOCAL"; then
    EXTRA="--authentication-file=/home/user/luser/tooltool-download-token"
else
    EXTRA="--url=http://relengapi/tooltool/"
fi
python ../tooltool.py -v ${EXTRA} -m dump-syms.manifest fetch
/opt/wine-staging/bin/regsvr32 msdia120.dll

cd ..

wget -O symsrv-fetch.py "${SCRIPT_URL}"
python symsrv-fetch.py -v $*
mkdir artifacts
mv symbols-*.zip artifacts/target.crashreporter-symbols.zip
