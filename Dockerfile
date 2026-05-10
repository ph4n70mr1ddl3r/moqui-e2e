# ── Stage 1: Build ────────────────────────────────────────────
FROM eclipse-temurin:21-jdk-jammy AS builder

WORKDIR /opt/moqui

# Copy Gradle wrapper and config first (leverages layer caching)
COPY gradlew .
COPY gradle/ gradle/
COPY gradle.properties .
COPY settings.gradle .
COPY init-owasp.gradle .
COPY init-quality.gradle .
COPY init-spotless.gradle .

# Copy framework source (the bulk of the build)
COPY framework/ framework/
COPY MoquiInit.properties .

# Copy runtime components
COPY runtime/ runtime/

# Build the executable WAR
RUN --mount=type=cache,target=/root/.gradle \
    chmod +x gradlew \
    && ./gradlew clean build -x test --no-daemon \
    && echo "Build complete"

# ── Stage 2: Runtime ─────────────────────────────────────────
FROM eclipse-temurin:21-jre-jammy

LABEL maintainer="headless-erp" \
      description="Headless ERP — Moqui API server with Mantle UDM/USL" \
      org.opencontainers.image.source="https://github.com/ph4n70mr1ddl3r/headless"

# Create non-root user
RUN groupadd -r moqui && useradd -r -g moqui -d /opt/moqui -s /sbin/nologin moqui

WORKDIR /opt/moqui

# Copy the executable WAR from builder
COPY --from=builder /opt/moqui/moqui.war .

# Copy runtime directory (conf, base-component, component)
COPY runtime/ runtime/

# Create writable directories with correct ownership
RUN mkdir -p runtime/db runtime/log runtime/sessions runtime/txlog runtime/classes \
    && chown -R moqui:moqui /opt/moqui

# Default environment variables — override at runtime
ENV MOQUI_CONF=conf/MoquiProductionConf.xml \
    MOQUI_RUNTIME=runtime \
    JAVA_OPTS="-server -Xms512m -Xmx1024m -XX:+UseG1GC" \
    ENTITY_DS_DB_HOST=postgres \
    ENTITY_DS_DB_PORT=5432 \
    ENTITY_DS_DB_NAME=headless_erp \
    ENTITY_DS_DB_USER=headless_erp \
    ENTITY_DS_DB_PASSWORD=headless_erp \
    ENTITY_DS_CRYPT_PASS=MoquiHeadlessERP \
    WEBAPP_HTTP_PORT=8080

EXPOSE 8080

USER moqui

# Health check — hits the headless-erp health endpoint
HEALTHCHECK --interval=10s --timeout=5s --start-period=120s --retries=3 \
    CMD curl -sf http://localhost:${WEBAPP_HTTP_PORT}/rest/s1/headless/health -u admin:admin || exit 1

ENTRYPOINT ["sh", "-c", "exec java ${JAVA_OPTS} \
    -Dmoqui.conf=${MOQUI_CONF} \
    -Dmoqui.runtime=${MOQUI_RUNTIME} \
    -Dentity_ds_host=${ENTITY_DS_DB_HOST} \
    -Dentity_ds_port=${ENTITY_DS_DB_PORT} \
    -Dentity_ds_database=${ENTITY_DS_DB_NAME} \
    -Dentity_ds_user=${ENTITY_DS_DB_USER} \
    -Dentity_ds_password=${ENTITY_DS_DB_PASSWORD} \
    -Dentity_ds_crypt_pass=${ENTITY_DS_CRYPT_PASS} \
    -jar moqui.war"]
