FROM ubuntu:16.04
# If host is running squid-deb-proxy on port 8000, populate /etc/apt/apt.conf.d/30proxy
# By default, squid-deb-proxy 403s unknown sources, so apt shouldn't proxy ppa.launchpad.net
RUN awk '/^[a-z]+[0-9]+\t00000000/ { printf("%d.%d.%d.%d\n", "0x" substr($3, 7, 2), "0x" substr($3, 5, 2), "0x" substr($3, 3, 2), "0x" substr($3, 1, 2)) }' < /proc/net/route > /tmp/host_ip.txt
RUN perl -pe 'use IO::Socket::INET; chomp; $socket = new IO::Socket::INET(PeerHost=>$_,PeerPort=>"8000"); print $socket "HEAD /\n\n"; my $data; $socket->recv($data,1024); exit($data !~ /squid-deb-proxy/)' <  /tmp/host_ip.txt \
  && (echo "Acquire::http::Proxy \"http://$(cat /tmp/host_ip.txt):8000\";" > /etc/apt/apt.conf.d/30proxy) \
  && (echo "Acquire::http::Proxy::ppa.launchpad.net DIRECT;" >> /etc/apt/apt.conf.d/30proxy) \
  || echo "No squid-deb-proxy detected on docker host"
RUN dpkg --add-architecture i386 \
  && apt-get update \
  && apt-get install -y software-properties-common \
  && add-apt-repository ppa:pipelight/stable \
  && apt-get update \
  && apt-get install -y --install-recommends wine-staging cabextract wget python-dev build-essential git
RUN wget https://bootstrap.pypa.io/get-pip.py && python get-pip.py
RUN pip install --upgrade requests
RUN useradd -d /home/user -s /bin/bash -m user
WORKDIR /home/user
RUN mkdir dump_syms
ADD dump-syms.manifest /home/user/dump_syms/
ADD config.py.docker /home/user/config.py
ADD https://hg.mozilla.org/mozilla-central/raw-file/default/python/mozbuild/mozbuild/action/tooltool.py /home/user/tooltool.py
ADD start.sh /home/user/
RUN chown -R user.user /home/user
USER user
