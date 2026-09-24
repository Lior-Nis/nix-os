CONFIG_FILE ?= .env
export CONFIG_FILE

.PHONY: validate init-secrets deploy upgrade status health logs restart backup restore-smoke ci

validate:
	./scripts/check-config "$(CONFIG_FILE)"

init-secrets:
	./scripts/init-secrets "$(CONFIG_FILE)"

deploy:
	./scripts/ops deploy

upgrade:
	./scripts/ops upgrade

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

restore-smoke:
	@test -n "$(BACKUP_ARTIFACT)" || { echo "Set BACKUP_ARTIFACT=/absolute/path/to/backup.tar.gz" >&2; exit 1; }
	./scripts/restore-smoke "$(BACKUP_ARTIFACT)"

ci:
	./scripts/ci
