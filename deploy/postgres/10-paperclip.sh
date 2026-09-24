#!/usr/bin/env sh
set -eu

: "${PAPERCLIP_DB_PASSWORD:?PAPERCLIP_DB_PASSWORD is required}"

psql --set ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  --set paperclip_password="$PAPERCLIP_DB_PASSWORD" <<'SQL'
CREATE ROLE paperclip
  LOGIN
  NOSUPERUSER
  NOCREATEDB
  NOCREATEROLE
  NOINHERIT
  NOREPLICATION
  PASSWORD :'paperclip_password';
CREATE DATABASE paperclip OWNER paperclip;
SQL
