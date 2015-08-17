#!/usr/bin/env python
#
# This script will read a CSV of modules from Socorro, and try to retrieve
# missing symbols from Microsoft's symbol server. It honors a blacklist
# (blacklist.txt) of symbols that are known to be from our applications,
# and it maintains its own list of symbols that the MS symbol server
# doesn't have (skiplist.txt).
#
# The script also depends on having write access to the directory it is
# installed in, to write the skiplist text file.

from __future__ import with_statement
import config
import sys
import os
import time
import datetime
import subprocess
import io
import gzip
import shutil
import ctypes
import logging
from collections import defaultdict
from tempfile import mkdtemp
import urllib
import urlparse
import zipfile
import requests

# Just hardcoded here
MICROSOFT_SYMBOL_SERVER = 'http://msdl.microsoft.com/download/symbols/'
USER_AGENT = 'Microsoft-Symbol-Server/6.3.0.0'
MOZILLA_SYMBOL_SERVER = ('https://s3-us-west-2.amazonaws.com/'
                         'org.mozilla.crash-stats.symbols-public/v1/')
UPLOAD_URL = 'https://crash-stats.mozilla.com/symbols/upload'
MISSING_SYMBOLS_URL = 'https://crash-analysis.mozilla.com/crash_analysis/{date}/{date}-missing-symbols.txt'

thisdir = os.path.dirname(__file__)
log = logging.getLogger()


def fetch_symbol(debug_id, debug_file):
    '''
    Attempt to fetch a PDB file from Microsoft's symbol server.
    '''
    url = urlparse.urljoin(MICROSOFT_SYMBOL_SERVER,
                           os.path.join(debug_file,
                                        debug_id,
                                        debug_file[:-1] + '_'))
    r = requests.get(url,
                     headers={'User-Agent': USER_AGENT})
    if r.status_code == 200:
        return r.content
    return None


def fetch_and_dump_symbols(tmpdir, debug_id, debug_file):
    pdb_bytes = fetch_symbol(debug_id, debug_file)
    if not pdb_bytes or not pdb_bytes.startswith(b'MSCF'):
        return None
    pdb_path = os.path.join(tmpdir, debug_file[:-1] + '_')
    with open(pdb_path, 'wb') as f:
        f.write(pdb_bytes)
    try:
        # Decompress it
        subprocess.check_call(['cabextract', '-d', tmpdir, pdb_path])
        pdb_path = os.path.join(tmpdir, debug_file)
        # Dump it
        return subprocess.check_output(config.dump_syms_cmd + [pdb_path])
    except subprocess.CalledProcessError:
        return None


def server_has_file(filename):
    '''
    Send the symbol server a HEAD request to see if it has this symbol file.
    '''
    try:
        r = requests.head(
            urlparse.urljoin(
                MOZILLA_SYMBOL_SERVER,
                urllib.quote(filename)))
        return r.status_code == 200
    except requests.exceptions.RequestException:
        return False


def write_skiplist(skiplist):
    try:
        with open(os.path.join(thisdir, 'skiplist.txt'), 'w') as sf:
            for (debug_id, debug_file) in skiplist.iteritems():
                sf.write('%s %s\n' % (debug_id, debug_file))
    except IOError:
        log.exception('Error writing skiplist.txt')



def fetch_missing_symbols(log):
    now = datetime.datetime.now()
    for n in range(5):
        d = now + datetime.timedelta(days=-n)
        u = MISSING_SYMBOLS_URL.format(date=d.strftime('%Y%m%d'))
        log.info('Trying missing symbols from %s' % u)
        r = requests.get(u)
        if r.status_code == 200 and len(r.text) > 0:
            return r.text
    return None


def main():    
    verbose = False
    if len(sys.argv) > 1 and sys.argv[1] == '-v':
        verbose = True
        sys.argv.pop(1)

    log.setLevel(logging.DEBUG)
    urllib3_logger = logging.getLogger('urllib3')
    urllib3_logger.setLevel(logging.ERROR)
    formatter = logging.Formatter(fmt='%(asctime)-15s %(message)s',
                                  datefmt='%Y-%m-%d %H:%M:%S')
    filelog = logging.FileHandler(filename=os.path.join(thisdir,
                                                        'symsrv-fetch.log'))
    filelog.setLevel(logging.INFO)
    filelog.setFormatter(formatter)
    log.addHandler(filelog)

    if verbose:
        handler = logging.StreamHandler()
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(formatter)
        log.addHandler(handler)
        verboselog = logging.FileHandler(filename=os.path.join(thisdir,
                                                               'verbose.log'))
        log.addHandler(verboselog)

    log.info('Started')

    # Symbols that we know belong to us, so don't ask Microsoft for them.
    try:
        blacklist = set(
            l.rstrip() for l in open(
                os.path.join(
                    thisdir,
                    'blacklist.txt'),
                'r').readlines())
    except IOError:
        blacklist = set()
    log.debug('Blacklist contains %d items' % len(blacklist))

    # Symbols that we know belong to Microsoft, so don't skiplist them.
    try:
        known_ms_symbols = set(
            l.rstrip() for l in open(
                os.path.join(
                    thisdir,
                    'known-microsoft-symbols.txt'),
                'r').readlines())
    except IOError:
        known_ms_symbols = set()
    log.debug('Known Microsoft symbols contains %d items'
              % len(known_ms_symbols))

    # Symbols that we've asked for in the past unsuccessfully
    skiplist = {}
    skipcount = 0
    try:
        sf = file(os.path.join(thisdir, 'skiplist.txt'), 'r')
        for line in sf:
            line = line.strip()
            if line == '':
                continue
            s = line.split(None, 1)
            if len(s) != 2:
                continue
            (debug_id, debug_file) = s
            skiplist[debug_id] = debug_file.lower()
            skipcount += 1
        sf.close()
    except IOError:
        pass
    log.debug('Skiplist contains %d items' % skipcount)

    modules = defaultdict(set)
    if len(sys.argv) > 1:
        url = sys.argv[1]
        log.debug("Loading missing symbols URL %s" % url)
        fetch_error = False
        try:
            req = requests.get(url)
        except requests.exceptions.RequestException as e:
            fetch_error = True
        if fetch_error or req.status_code != 200:
            log.exception("Error fetching symbols")
            sys.exit(1)
        missing_symbols = req.text
    else:
        missing_symbols = fetch_missing_symbols(log)

    lines = iter(missing_symbols.splitlines())
    # Skip header
    next(lines)
    for line in lines:
        line = line.rstrip().encode('ascii', 'replace')
        bits = line.split(',')
        if len(bits) < 2:
            continue
        pdb, uuid = bits[:2]
        if pdb and uuid and pdb.endswith('.pdb'):
            modules[pdb].add(uuid)

    symbol_path = mkdtemp('symsrvfetch')
    temp_path = mkdtemp(prefix='symtmp')

    log.debug("Fetching symbols (%d pdb files)" % len(modules))
    total = sum(len(ids) for ids in modules.values())
    current = 0
    blacklist_count = 0
    skiplist_count = 0
    existing_count = 0
    not_found_count = 0
    file_index = []
    # Now try to fetch all the unknown modules from the symbol server
    for filename, ids in modules.iteritems():
        if filename.lower() in blacklist:
            # This is one of our our debug files from Firefox/Thunderbird/etc
            current += len(ids)
            blacklist_count += len(ids)
            continue
        for id in ids:
            current += 1
            if verbose:
                sys.stdout.write('[%6d/%6d] %3d%% %-20s\r' %
                                 (current, total, int(100 *
                                                      current /
                                                      total), filename[:20]))
            if id in skiplist and skiplist[id] == filename.lower():
                # We've asked the symbol server previously about this,
                # so skip it.
                log.debug('%s/%s already in skiplist', filename, id)
                skiplist_count += 1
                continue
            rel_path = os.path.join(filename, id,
                                    filename.replace('.pdb', '') + '.sym')
            if server_has_file(rel_path):
                log.debug('%s/%s already on server', filename, id)
                existing_count += 1
                continue
            # Not in the blacklist, skiplist, and we don't already have it, so
            # ask the symbol server for it.
            sym_output = fetch_and_dump_symbols(temp_path,
                                                id, filename)
            if sym_output is None:
                not_found_count += 1
                # Figure out how to manage the skiplist later...
                log.debug(
                    'Couldn\'t fetch %s/%s, but not skiplisting',
                    filename,
                    id)
            else:
                log.debug('Successfully downloaded %s/%s', filename, id)
                file_index.append(rel_path.replace('\\', '/'))
                sym_file = os.path.join(symbol_path, rel_path)
                try:
                    os.makedirs(os.path.dirname(sym_file))
                except OSError:
                    pass
                # TODO: just add to in-memory zipfile
                open(sym_file, 'w').write(sym_output)

    if verbose:
        sys.stdout.write('\n')

    if not file_index:
        log.info(
            'No symbols downloaded: %d considered, '
            '%d already present, %d in blacklist, %d skipped, %d not found' %
            (total,
             existing_count,
             blacklist_count,
             skiplist_count,
             not_found_count))
        write_skiplist(skiplist)
        sys.exit(0)

    # Write an index file
    buildid = time.strftime('%Y%m%d%H%M%S', time.localtime())
    index_filename = 'microsoftsyms-1.0-WINNT-%s-symbols.txt' % buildid
    log.debug('Adding %s' % index_filename)
    success = False
    zipname = "symbols-%s.zip" % buildid
    with zipfile.ZipFile(zipname, 'w', zipfile.ZIP_DEFLATED) as z:
        for f in file_index:
            z.write(os.path.join(symbol_path, f), f)
        z.writestr(index_filename, '\n'.join(file_index))
    # Upload zip file
    if hasattr(config, 'upload_url'):
        os.environ['SOCORRO_SYMBOL_UPLOAD_URL'] = config.upload_url
    from upload_symbols import upload_symbol_zip
    success = upload_symbol_zip(zipname, config.auth_token, log) == 0
    if not success:
        log.info('Failed to upload, wrote zip as %s' % tmpzip)

    shutil.rmtree(symbol_path, True)

    # Write out our new skip list
    write_skiplist(skiplist)

    if success:
        log.info('Uploaded %d symbol files' % len(file_index))
    log.info('Finished, exiting')

if __name__ == '__main__':
    main()
