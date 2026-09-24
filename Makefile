CONFIG_FILE ?= .env
export CONFIG_FILE

.PHONY: vps-preflight validate init-secrets initialize-paperclip deploy upgrade bootstrap-ceo status health logs restart backup backup-config restore-config restore-smoke ci

vps-preflight:
	./scripts/vps-preflight

validate:
	./scripts/check-config "$(CONFIG_FILE)"

init-secrets:
	./scripts/init-secrets "$(CONFIG_FILE)"

initialize-paperclip:
	./scripts/initialize-paperclip "$(CONFIG_FILE)"

deploy:
	./scripts/ops deploy

upgrade:
	./scripts/ops upgrade

bootstrap-ceo:
	./scripts/ops bootstrap-ceo

status:
	./scripts/ops status

health:
	./scripts/ops health

logs:
	./scripts/ops logs

restart:
	./scripts/ops restart

backup:
	./scripts/backup "$(CONFIG_FILE)"

backup-config:
	./scripts/backup-config "$(CONFIG_FILE)"

restore-config:
	@test -n "$(CONFIG_BACKUP_ARTIFACT)" || { echo "Set CONFIG_BACKUP_ARTIFACT=/absolute/path/to/config-pack.tar.gz.age" >&2; exit 1; }
	./scripts/restore-config "$(CONFIG_BACKUP_ARTIFACT)" "$(abspath $(CONFIG_FILE))"

restore-smoke:
	@test -n "$(BACKUP_ARTIFACT)" || { echo "Set BACKUP_ARTIFACT=/absolute/path/to/backup.tar.gz" >&2; exit 1; }
	./scripts/restore-smoke "$(BACKUP_ARTIFACT)"

ci:
	./scripts/ci
