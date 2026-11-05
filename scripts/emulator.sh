#!/usr/bin/env bash
# 开发机上拉起/连接安卓模拟器当测试机（颛桥单卡机，无界面）。
# 前置：/dev/kvm 对本用户可读写（sudo setfacl -m u:$USER:rw /dev/kvm）；
#       SDK 在 ~/android-sdk（cmdline-tools/latest、emulator、system-images/android-34/google_apis/x86_64）。
# 用法：emulator.sh up | down | status | setup-hand
set -e
SDK="$HOME/android-sdk"
export ANDROID_SDK_ROOT="$SDK" ANDROID_AVD_HOME="$HOME/.android/avd"
export PATH="$SDK/platform-tools:$SDK/emulator:$PATH"
AVD=aiphone
SERIAL=emulator-5554
PKG=com.qianxun.aiphone
APK="$HOME/myproject/aiphone/hand-android/app/build/outputs/apk/debug/app-debug.apk"

case "${1:-up}" in
up)
  if adb devices | grep -q "$SERIAL"; then echo "模拟器已在运行"; exit 0; fi
  # 无界面 + swiftshader 软渲染（服务器无显卡）；-accel on 用 KVM 加速
  nohup emulator -avd "$AVD" -no-window -no-audio -no-snapshot -no-boot-anim \
    -gpu swiftshader_indirect -accel on -port 5554 > /tmp/emu.log 2>&1 &
  echo "启动中（pid $!），等待开机..."
  adb -s "$SERIAL" wait-for-device
  until [ "$(adb -s "$SERIAL" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = 1 ]; do sleep 3; done
  # 关掉虚拟 WiFi：否则 10.0.2.0/24 走 wlan0，10.0.2.2（宿主别名，只在 eth0）连不上
  adb -s "$SERIAL" shell svc wifi disable
  echo "✅ 开机完成，WiFi 已关（走 eth0，宿主=10.0.2.2）"
  ;;
setup-hand)
  # 装「手」+ 写配置（服务器用 10.0.2.2 指向宿主上的 hub）+ 启用无障碍
  adb -s "$SERIAL" install -r "$APK"
  CODE=$(cat "$HOME/.config/aiphone/code")
  adb -s "$SERIAL" shell am force-stop "$PKG" || true
  printf '<?xml version="1.0" encoding="utf-8" standalone="yes" ?>\n<map>\n<string name="server">http://10.0.2.2:8700</string>\n<string name="code">%s</string>\n</map>\n' "$CODE" \
    | adb -s "$SERIAL" shell "run-as $PKG sh -c 'cat > /data/data/$PKG/shared_prefs/cfg.xml'"
  adb -s "$SERIAL" shell settings put secure enabled_accessibility_services "$PKG/$PKG.HandService"
  adb -s "$SERIAL" shell settings put secure accessibility_enabled 1
  adb -s "$SERIAL" shell am start -n "$PKG/.MainActivity" >/dev/null
  echo "✅ 手已装好并启用无障碍，配对码 $CODE"
  ;;
status)
  adb devices; adb -s "$SERIAL" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r' | sed 's/^/boot_completed=/' ;;
down)
  adb -s "$SERIAL" emu kill 2>/dev/null || true; echo "已关闭" ;;
*) echo "用法: $0 up|setup-hand|status|down"; exit 1 ;;
esac
