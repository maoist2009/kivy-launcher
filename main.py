# -*- coding: utf-8 -*-
import os
import sys
import json
import hashlib
import datetime
import fcntl
from pathlib import Path

# === Step 1: Autoclass Hook for Service Redirection ===
import pyjnius
_original_autoclass = pyjnius.autoclass

# 预注册的 10 个服务槽位（与 buildozer.spec 一致）
SERVICE_SLOTS = [
    "org.maoist2009.kivylauncher.ServiceSlot0",
    "org.maoist2009.kivylauncher.ServiceSlot1",
    "org.maoist2009.kivylauncher.ServiceSlot2",
    "org.maoist2009.kivylauncher.ServiceSlot3",
    "org.maoist2009.kivylauncher.ServiceSlot4",
    "org.maoist2009.kivylauncher.ServiceSlot5",
    "org.maoist2009.kivylauncher.ServiceSlot6",
    "org.maoist2009.kivylauncher.ServiceSlot7",
    "org.maoist2009.kivylauncher.ServiceSlot8",
    "org.maoist2009.kivylauncher.ServiceSlot9",
    "org.maoist2009.kivylauncher.ServiceSlot10",
    "org.maoist2009.kivylauncher.ServiceSlot11",
    "org.maoist2009.kivylauncher.ServiceSlot12",
    "org.maoist2009.kivylauncher.ServiceSlot13",
]

# 获取应用私有目录（复用 packman）
def _get_app_files_dir():
    from packman import _get_app_files_dir as get_dir
    return get_dir()

SERVICE_JSON = Path(_get_app_files_dir()) / "service.json"

def allocate_service_slot(entrypoint: str) -> str:
    """为项目分配一个服务槽位，并更新 service.json（带文件锁）"""
    project_id = hashlib.md5(entrypoint.encode()).hexdigest()[:8]
    slot_index = int(project_id, 16) % 10
    service_class = SERVICE_SLOTS[slot_index]

    # 确保目录存在
    SERVICE_JSON.parent.mkdir(parents=True, exist_ok=True)

    # 加锁写入
    with open(SERVICE_JSON, "a+") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        f.seek(0)
        try:
            data = json.load(f)
        except:
            data = {}
        data[project_id] = {
            "entrypoint": entrypoint,
            "slot": slot_index,
            "assigned_at": str(datetime.datetime.now())
        }
        f.truncate(0)
        json.dump(data, f, indent=2)
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    print(f"[SERVICE] Project {project_id} → Slot{slot_index}")
    return service_class

def hooked_autoclass(classname):
    """劫持 autoclass，重定向服务类到预注册槽位"""
    if "Service" in classname and not classname.startswith(("android.", "java.", "javax.")):
        # 获取当前 entrypoint（优先环境变量，其次 Intent）
        entrypoint = os.environ.get("KIVYLAUNCHER_ENTRYPOINT")
        if not entrypoint:
            try:
                from jnius import autoclass
                activity = autoclass("org.kivy.android.PythonActivity").mActivity
                entrypoint = activity.getIntent().getStringExtra("entrypoint")
                if entrypoint:
                    os.environ["KIVYLAUNCHER_ENTRYPOINT"] = entrypoint
            except Exception:
                pass

        if entrypoint:
            proxy_class = allocate_service_slot(entrypoint)
            print(f"[HOOK] Redirect {classname} → {proxy_class}")
            return _original_autoclass(proxy_class)
        else:
            # 无 entrypoint 时 fallback 到 Slot0
            print(f"[HOOK] No entrypoint, fallback to Slot0")
            return _original_autoclass(SERVICE_SLOTS[0])

    return _original_autoclass(classname)

# 注入 hook（必须在导入其他模块前！）
pyjnius.autoclass = hooked_autoclass

# === Step 2: Entry Point Logic ===
def run_entrypoint(entrypoint):
    import runpy
    import sys
    import os
    # 注入项目 site-packages（由 packman 管理）
    from packman import ensure_project_site_packages
    ensure_project_site_packages()
    entrypoint_path = os.path.dirname(entrypoint)
    sys.path.insert(0, os.path.realpath(entrypoint_path))
    runpy.run_path(entrypoint, run_name="__main__")

def run_launcher(tb=None):
    from launcher.app import Launcher
    Launcher().run()

def dispatch():
    import os
    print("dispatch!")
    entrypoint = os.environ.get("KIVYLAUNCHER_ENTRYPOINT")
    if entrypoint is not None:
        return run_entrypoint(entrypoint)
    # try android
    try:
        from jnius import autoclass
        activity = autoclass("org.kivy.android.PythonActivity").mActivity
        intent = activity.getIntent()
        entrypoint = intent.getStringExtra("entrypoint")
        orientation = intent.getStringExtra("orientation")
        if orientation == "portrait":
            activity.setRequestedOrientation(0x1)
        elif orientation == "landscape":
            activity.setRequestedOrientation(0x0)
        elif orientation == "sensor":
            activity.setRequestedOrientation(0x4)
        if entrypoint is not None:
            try:
                return run_entrypoint(entrypoint)
            except Exception:
                import traceback
                traceback.print_exc()
                return
    except Exception:
        import traceback
        traceback.print_exc()
    run_launcher()

if __name__ == "__main__":
    dispatch()