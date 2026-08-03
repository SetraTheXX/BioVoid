FROM eclipse-temurin:17-jdk-jammy@sha256:723151f3fc88ca2060153ee08ab8dbbea7983d6ed6f2622fe440acf178737c94

ARG P2RANK_COMMIT=9808a7723be9a94e2ffc21ab5f724cb6ae4ba01e

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates git \
    && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/rdk/p2rank.git /opt/p2rank \
    && cd /opt/p2rank \
    && git checkout --detach "${P2RANK_COMMIT}" \
    && ./gradlew --no-daemon --max-workers=1 assemble

WORKDIR /opt/p2rank

ENTRYPOINT ["/opt/p2rank/distro/prank"]
