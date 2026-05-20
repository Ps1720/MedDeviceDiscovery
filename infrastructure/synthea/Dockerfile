FROM eclipse-temurin:17-jre

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates bash \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /synthea-work

# seed.sh is also bind-mounted at runtime; copying it keeps the image runnable standalone.
COPY seed.sh /usr/local/bin/seed.sh
RUN chmod +x /usr/local/bin/seed.sh

CMD ["bash", "/synthea-work/seed.sh"]
