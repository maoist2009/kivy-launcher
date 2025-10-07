[app]
# 应用基本信息
title = KivyLauncher Enhanced
package.name = kivylauncher
package.domain = org.maoist2009

# 源码路径（指向 launcher 根目录）
source.dir = ../..
source.include_exts = py,png,jpg,kv,atlas,json,ttf,svg,txt,mp3
source.exclude_dirs = tools,browser,__pycache__

# 版本控制
version = 1.0
android.numeric_version = 1

# Launcher 自身依赖（用户项目依赖由 packman 运行时安装）
requirements = python3,kivy,pyjnius,android,requests,urllib3

# 方向
orientation = portrait

# 预注册 10 个服务槽位（全部 foreground:sticky）
services =
    Slot0:services/service_slot.py:foreground:sticky
    Slot1:services/service_slot.py:foreground:sticky
    Slot2:services/service_slot.py:foreground:sticky
    Slot3:services/service_slot.py:foreground:sticky
    Slot4:services/service_slot.py:foreground:sticky
    Slot5:services/service_slot.py:foreground:sticky
    Slot6:services/service_slot.py:foreground:sticky
    Slot7:services/service_slot.py:foreground:sticky
    Slot8:services/service_slot.py:foreground:sticky
    Slot9:services/service_slot.py:foreground:sticky
    Slot10:services/service_slot.py:sticky
    Slot11:services/service_slot.py:sticky
    Slot12:services/service_slot.py:sticky
    Slot13:services/service_slot.py:sticky

# 图标（自动使用项目中的 icon.png，无需在此指定）
# icon.filename = %(source.dir)s/icon.png

#
# Android specific
#
fullscreen = 0
android.presplash_color = #39C5BB

# 权限（精简安全版）
android.permissions =
    INTERNET,
    MANAGE_EXTERNAL_STORAGE,
    FOREGROUND_SERVICE,
    WAKE_LOCK,
    REQUEST_IGNORE_BATTERY_OPTIMIZATIONS

# Target Android 10 (API 29)
android.api = 30
android.minapi = 21
android.ndk = 25b
android.archs = arm64-v8a, armeabi-v7a

# 其他
android.allow_backup = True
android.no-byte-compile-python = True
android.release_artifact = apk
android.debug_artifact = apk

#
# Buildozer
#
[buildozer]
log_level = 2
warn_on_root = 1