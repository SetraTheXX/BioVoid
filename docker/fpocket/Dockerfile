FROM ubuntu:22.04
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc g++ make git libnetcdf-dev ca-certificates && \
    git clone --depth 1 https://github.com/Discngine/fpocket.git /opt/fpocket && \
    cd /opt/fpocket && make && make install && \
    apt-get clean && rm -rf /var/lib/apt/lists/*
ENTRYPOINT ["fpocket"]
