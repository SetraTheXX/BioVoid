FROM ubuntu:22.04@sha256:0e0a0fc6d18feda9db1590da249ac93e8d5abfea8f4c3c0c849ce512b5ef8982
ARG FPOCKET_COMMIT=4bb0d8447f62fee77e2c3c29f54b5fcaf5e2c066
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc g++ make git libnetcdf-dev ca-certificates && \
    git clone https://github.com/Discngine/fpocket.git /opt/fpocket && \
    cd /opt/fpocket && git checkout --detach "${FPOCKET_COMMIT}" && \
    make && make install && \
    apt-get clean && rm -rf /var/lib/apt/lists/*
LABEL org.opencontainers.image.version="fpocket-4.2.3"
ENTRYPOINT ["fpocket"]
