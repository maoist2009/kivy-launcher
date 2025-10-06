# services/service_slot.py
from kivy.utils import platform
if platform == 'android':
    from kivy.logger import Logger
    from jnius import autoclass
    import os
    import json
    import hashlib
    from pathlib import Path

    # 获取当前服务类名（如 ServiceSlot3）
    SERVICE_NAME = os.environ.get("PYTHON_SERVICE_NAME", "UnknownService")
    SLOT_INDEX = int(SERVICE_NAME.replace("ServiceSlot", ""))

    # 读取 service.json，找到自己负责的项目
    def get_assigned_project():
        from packman import _get_app_files_dir
        service_json = Path(_get_app_files_dir()) / "service.json"
        if not service_json.exists():
            return None
        try:
            with open(service_json, "r") as f:
                data = json.load(f)
            for proj_id, info in data.items():
                if info.get("slot") == SLOT_INDEX:
                    return info
        except Exception as e:
            Logger.error(f"Failed to read service.json: {e}")
        return None

    def start(context, args="{}"):
        Logger.info(f"ServiceSlot{SLOT_INDEX} starting...")
        project = get_assigned_project()
        if project:
            Logger.info(f"Executing project: {project['entrypoint']}")
            # TODO: 在此执行项目的服务逻辑（如启动后台任务）
            # 注意：不要阻塞 on_start()
        else:
            Logger.info("No project assigned to this slot.")

    def stop(context):
        Logger.info(f"ServiceSlot{SLOT_INDEX} stopping...")