# -*- coding: utf-8 -*-
import os
import re
from datetime import datetime
from kivy.lang import Builder
from kivy.app import App
from kivy.utils import platform
from kivy.properties import ListProperty, BooleanProperty
from glob import glob
from os.path import dirname, join, exists
import traceback

KIVYLAUNCHER_PATHS = os.environ.get("KIVYLAUNCHER_PATHS")


class Launcher(App):
    paths = ListProperty()
    logs = ListProperty()
    display_logs = BooleanProperty(False)

    def log(self, log):
        print(log)
        self.logs.append(f"{datetime.now().strftime('%X.%f')}: {log}")

    def build(self):
        self.log('start of log')

        if KIVYLAUNCHER_PATHS:
            self.paths.extend(KIVYLAUNCHER_PATHS.split(","))

        if platform == 'android':
            from jnius import autoclass
            Environment = autoclass('android.os.Environment')
            sdcard_path = Environment.getExternalStorageDirectory().getAbsolutePath()
            self.paths = [sdcard_path + "/kivy"]
        else:
            self.paths = [os.path.expanduser("~/kivy")]

        self.root = Builder.load_file("launcher/app.kv")
        self.refresh_entries()

        if platform == 'android':
            from android.permissions import request_permissions, Permission
            request_permissions([Permission.READ_EXTERNAL_STORAGE])

    def refresh_entries(self):
        data = []
        self.log('starting refresh')
        for entry in self.find_entries(paths=self.paths):
            self.log(f'found entry {entry}')
            data.append({
                "data_title": entry.get("title", "- no title -"),
                "data_path": entry.get("path"),
                "data_logo": entry.get("logo", "data/logo/kivy-icon-64.png"),
                "data_orientation": entry.get("orientation", ""),
                "data_author": entry.get("author", ""),
                "data_entry": entry
            })
        self.root.ids.rv.data = data

    def find_entries(self, path=None, paths=None):
        self.log(f'looking for entries in paths={paths}, path={path}')
        if paths is not None:
            for p in paths:
                yield from self.find_entries(path=p)
            return

        if path is None or not exists(path):
            self.log(f'{path} does not exist')
            return

        try:
            self.log(f'listing dir: {os.listdir(path)}')
        except Exception as e:
            self.log(f'cannot list {path}: {e}')
            return

        # 查找 android.txt
        for filename in glob(join(path, "*/android.txt")):
            self.log(f'found android.txt: {filename}')
            entry = self.read_android_txt(filename)
            if entry:
                yield entry

        # 查找 buildozer.spec
        for filename in glob(join(path, "*/buildozer.spec")):
            self.log(f'found buildozer.spec: {filename}')
            entry = self.read_buildozer_spec(filename)
            if entry:
                yield entry

    def read_android_txt(self, filename):
        """从 android.txt 读取 entry"""
        data = {}
        try:
            with open(filename, "r", encoding='utf-8') as fd:
                for line in fd:
                    line = line.strip()
                    if not line or '=' not in line:
                        continue
                    k, v = line.split("=", 1)
                    data[k.strip()] = v.strip()
        except Exception as e:
            self.log(f"Error reading android.txt {filename}: {e}")
            traceback.print_exc()
            return None

        base_dir = dirname(filename)
        data["entrypoint"] = join(base_dir, "main.py")
        data["path"] = base_dir
        # 确保关键字段有默认值
        data.setdefault("title", "- no title -")
        data.setdefault("author", "")
        data.setdefault("orientation", "")
        icon = join(base_dir, "icon.png")
        if exists(icon):
            data["logo"] = icon
        else:
            data["logo"] = "data/logo/kivy-icon-64.png"
        return data

    def read_buildozer_spec(self, filename):
        """从 buildozer.spec 读取 entry，解析 source.dir"""
        try:
            with open(filename, "r", encoding='utf-8') as fd:
                content = fd.read()
        except Exception as e:
            self.log(f"Error reading buildozer.spec {filename}: {e}")
            traceback.print_exc()
            return None

        # 提取 source.dir
        match = re.search(r'^\s*source\.dir\s*=\s*(.+)$', content, re.MULTILINE)
        if not match:
            self.log(f"buildozer.spec {filename} missing source.dir")
            return None

        source_dir = match.group(1).strip()
        # 去除行尾注释（如 # (str) Source code...）
        if '#' in source_dir:
            source_dir = source_dir.split('#', 1)[0].strip()

        if not source_dir:
            self.log(f"empty source.dir in {filename}")
            return None

        spec_dir = dirname(filename)
        main_dir = os.path.normpath(join(spec_dir, source_dir))
        main_py = join(main_dir, "main.py")

        if not exists(main_py):
            self.log(f"main.py not found at {main_py} (resolved from buildozer.spec)")
            return None

        # 尝试提取 title, author, orientation（可选）
        def get_spec_value(key):
            m = re.search(rf'^\s*{key}\s*=\s*(.+)$', content, re.MULTILINE)
            if m:
                val = m.group(1).strip()
                if '#' in val:
                    val = val.split('#', 1)[0].strip()
                return val
            return ""

        data = {
            "title": get_spec_value("title") or "- no title -",
            "author": get_spec_value("author"),
            "orientation": get_spec_value("orientation"),
            "entrypoint": main_py,
            "path": main_dir
        }

        icon = join(main_dir, "icon.png")
        data["logo"] = icon if exists(icon) else "data/logo/kivy-icon-64.png"
        return data

    def start_activity(self, entry):
        if platform == "android":
            self.start_android_activity(entry)
        else:
            self.start_desktop_activity(entry)

    def start_desktop_activity(self, entry):
        import sys
        from subprocess import Popen
        entrypoint = entry["entrypoint"]
        env = os.environ.copy()
        env["KIVYLAUNCHER_ENTRYPOINT"] = entrypoint
        main_py = os.path.realpath(os.path.join(
            os.path.dirname(__file__), "..", "main.py"))
        cmd = Popen([sys.executable, main_py], env=env)
        cmd.communicate()

    def start_android_activity(self, entry):
        self.log('starting activity')
        from jnius import autoclass
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        System = autoclass("java.lang.System")
        activity = PythonActivity.mActivity
        Intent = autoclass("android.content.Intent")
        String = autoclass("java.lang.String")

        j_entrypoint = String(entry.get("entrypoint"))
        j_orientation = String(entry.get("orientation", ""))

        self.log('creating intent')
        intent = Intent(
            activity.getApplicationContext(),
            PythonActivity
        )
        intent.putExtra("entrypoint", j_entrypoint)
        intent.putExtra("orientation", j_orientation)
        self.log(f'ready to start intent {j_entrypoint} {j_orientation}')
        activity.startActivity(intent)
        self.log('activity started')
        System.exit(0)


if __name__ == '__main__':
    Launcher().run()