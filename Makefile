IMAGE_NAME=taurus_x_monitor
CONTAINER_NAME=taurus_x_container
WORKDIR=$(shell pwd)

# Enable older Docker builder syntax if strictly required by environment
export DOCKER_BUILDKIT=0

.PHONY: build run stop logs restart clean freeze_reqs

# Detect the correct pip path inside virtual environment (supports both Windows & Linux venv paths)
PIP_BIN := $(if $(wildcard venv/Scripts/pip),venv/Scripts/pip,$(if $(wildcard venv/bin/pip),venv/bin/pip,pip))

# Automatically dump current venv dependencies to requirements.txt
freeze_reqs:
	@echo "🔄 Freezing active virtual environment dependencies..."
	@$(PIP_BIN) freeze > requirements.txt
	@echo "✅ requirements.txt updated successfully."

# Build the image after auto-updating requirements.txt and cleaning old instances
build: stop freeze_reqs
	docker build -t $(IMAGE_NAME) .

# Run the container with optimized strict memory limits
run:
	docker run -d \
		--name $(CONTAINER_NAME) \
		--restart unless-stopped \
		--memory="256m" \
		--dns 8.8.8.8 --dns 1.1.1.1 \
		-v $(WORKDIR):/app \
		$(IMAGE_NAME)

# Stop and remove the existing container instance safely
stop:
	@docker stop $(CONTAINER_NAME) 2>/dev/null || true
	@docker rm $(CONTAINER_NAME) 2>/dev/null || true

# View real-time streaming output logs
logs:
	docker logs -f $(CONTAINER_NAME)

# Full rebuild and deployment cycle
restart: build run

# Wipe unused docker cache to save system disk space
clean:
	docker system prune -f