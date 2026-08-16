IMAGE_NAME=taurus_x_monitor
CONTAINER_NAME=taurus_x_container
WORKDIR=$(shell pwd)

export DOCKER_BUILDKIT=0

.PHONY: build run stop logs restart clean freeze_reqs

# Динамический поиск pipreqs: в системе или в локальной папке пользователя
PIPREQS_BIN := $(shell which pipreqs 2>/dev/null || echo "$$HOME/.local/bin/pipreqs")

freeze_reqs:
	@echo "🔄 Scanning project imports to generate minimal requirements.txt..."
	@$(PIPREQS_BIN) . --force
	@echo "✅ requirements.txt updated cleanly."

build: stop freeze_reqs
	docker build -t $(IMAGE_NAME) .

# run:
# 	docker run -d \
# 		--name $(CONTAINER_NAME) \
# 		--restart unless-stopped \
# 		--memory="256m" \
# 		--dns 8.8.8.8 --dns 1.1.1.1 \
# 		-v $(WORKDIR):/app \
# 		$(IMAGE_NAME)

run:
	docker run -d \
		--name $(CONTAINER_NAME) \
		--restart unless-stopped \
		--memory="256m" \
		--dns 8.8.8.8 --dns 1.1.1.1 \
		--log-driver json-file \
		--log-opt max-size=100m \
		--log-opt max-file=3 \
		-v $(WORKDIR):/app \
		$(IMAGE_NAME)

stop:
	@docker stop $(CONTAINER_NAME) 2>/dev/null || true
	@docker rm $(CONTAINER_NAME) 2>/dev/null || true

logs:
	docker logs -f $(CONTAINER_NAME)

restart: stop run

clean:
	docker system prune -f
