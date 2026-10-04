APP_NAME   := ClaudeUsage
PROJECT    := $(APP_NAME).xcodeproj
BUILD_DIR  := build
APP_PATH   := $(BUILD_DIR)/Build/Products/Release/$(APP_NAME).app
INSTALL_TO := /Applications/$(APP_NAME).app

.PHONY: all setup project build install open clean

all: install

setup:
	@TEAM="$(TEAM)" BUNDLE_ID="$(BUNDLE_ID)" scripts/setup.sh

Local.xcconfig:
	@TEAM="$(TEAM)" BUNDLE_ID="$(BUNDLE_ID)" scripts/setup.sh

project: Local.xcconfig
	@command -v xcodegen >/dev/null || { echo "xcodegen 이 필요합니다: brew install xcodegen"; exit 1; }
	xcodegen generate

build: project
	xcodebuild -project $(PROJECT) -scheme $(APP_NAME) -configuration Release \
		-derivedDataPath $(BUILD_DIR) -allowProvisioningUpdates build

install: build
	@pkill -x $(APP_NAME) || true
	rm -rf "$(INSTALL_TO)"
	cp -R "$(APP_PATH)" "$(INSTALL_TO)"
	open "$(INSTALL_TO)"
	@echo "✅ 설치 완료. 바탕화면 우클릭 > '위젯 편집…' 에서 'Claude 사용량' 위젯을 추가하세요."

open: project
	open $(PROJECT)

clean:
	rm -rf $(BUILD_DIR) $(PROJECT)
