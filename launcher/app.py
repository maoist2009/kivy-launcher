# launcher/app.py
# -*- coding: utf-8 -*-
import os
import re
from datetime import datetime
from kivy.lang import Builder
from kivy.app import App
from kivy.utils import platform
from kivy.properties import ListProperty, BooleanProperty, DictProperty
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.uix.popup import Popup
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from glob import glob
from os.path import dirname, join, exists
import traceback

Builder.load_file("launcher/app.kv")

KIVYLAUNCHER_PATHS = os.environ.get("KIVYLAUNCHER_PATHS")


class ProjectListScreen(Screen):
    paths = ListProperty()
    logs = ListProperty()
    display_logs = BooleanProperty(False)

    def log(self, log):
        print(log)
        self.logs.append(f"{datetime.now().strftime('%X.%f')}: {log}")

    def on_pre_enter(self):
        self.refresh_entries()

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
        self.ids.rv.data = data

    def find_entries(self, path=None, paths=None):
        if paths is not None:
            for p in paths:
                yield from self.find_entries(path=p)
            return
        if path is None or not exists(path):
            return
        for filename in glob(join(path, "*/android.txt")):
            entry = self.read_android_txt(filename)
            if entry:
                yield entry
        for filename in glob(join(path, "*/buildozer.spec")):
            entry = self.read_buildozer_spec(filename)
            if entry:
                yield entry

    def read_android_txt(self, filename):
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
        data.setdefault("title", "- no title -")
        data.setdefault("author", "")
        data.setdefault("orientation", "")
        icon = join(base_dir, "icon.png")
        data["logo"] = icon if exists(icon) else "data/logo/kivy-icon-64.png"
        return data

    def read_buildozer_spec(self, filename):
        try:
            with open(filename, "r", encoding='utf-8') as fd:
                content = fd.read()
        except Exception as e:
            self.log(f"Error reading buildozer.spec {filename}: {e}")
            traceback.print_exc()
            return None
        match = re.search(r'^\s*source\.dir\s*=\s*(.+)$', content, re.MULTILINE)
        if not match:
            return None
        source_dir = match.group(1).strip()
        if '#' in source_dir:
            source_dir = source_dir.split('#', 1)[0].strip()
        if not source_dir:
            return None
        spec_dir = dirname(filename)
        main_dir = os.path.normpath(join(spec_dir, source_dir))
        main_py = join(main_dir, "main.py")
        if not exists(main_py):
            return None

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
        env = os.environ.copy()
        env["KIVYLAUNCHER_ENTRYPOINT"] = entry["entrypoint"]
        main_py = os.path.realpath(os.path.join(
            os.path.dirname(__file__), "..", "main.py"))
        Popen([sys.executable, main_py], env=env)

    def start_android_activity(self, entry):
        from jnius import autoclass
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        System = autoclass("java.lang.System")
        activity = PythonActivity.mActivity
        Intent = autoclass("android.content.Intent")
        String = autoclass("java.lang.String")
        intent = Intent(activity.getApplicationContext(), PythonActivity)
        intent.putExtra("entrypoint", String(entry["entrypoint"]))
        intent.putExtra("orientation", String(entry.get("orientation", "")))
        activity.startActivity(intent)
        System.exit(0)


class ConfigEditorScreen(Screen):
    config = DictProperty({})

    def on_pre_enter(self):
        from packman import get_config
        self.config = get_config()

    def save_config(self):
        from packman import save_config
        try:
            termux_repo = self.ids.termux_repo.text
            pypi_index = self.ids.pypi_index.text
            trusted_host = self.ids.trusted_host.text
            new_config = {
                "termux_repo": termux_repo,
                "pypi_index_url": pypi_index,
                "pypi_trusted_host": trusted_host
            }
            save_config(new_config)
            self.manager.get_screen('project_list').log("✅ Config saved")
            self.manager.current = 'project_list'
        except Exception as e:
            self.manager.get_screen('project_list').log(f"❌ Save failed: {e}")


class LauncherApp(App):
    def build(self):
        if KIVYLAUNCHER_PATHS:
            paths = KIVYLAUNCHER_PATHS.split(",")
        elif platform == 'android':
            from jnius import autoclass
            Environment = autoclass('android.os.Environment')
            sdcard = Environment.getExternalStorageDirectory().getAbsolutePath()
            paths = [f"{sdcard}/Download/kivy"]
        else:
            paths = [os.path.expanduser("~/kivy")]

        sm = ScreenManager()
        project_screen = ProjectListScreen(name='project_list')
        project_screen.paths = paths
        sm.add_widget(project_screen)
        sm.add_widget(ConfigEditorScreen(name='config_editor'))
        self.root = sm

        if platform == 'android':
            # 先请求 READ_EXTERNAL_STORAGE（用于 legacy 模式）
            from android.permissions import request_permissions, Permission
            def perm_callback(permissions, grants):
                if all(grants):
                    self.check_all_files_access()
                else:
                    self.show_popup("Storage Permission Required", "Please grant storage permission to scan projects.")
            request_permissions([Permission.READ_EXTERNAL_STORAGE,Permission.WRITE_EXTERNAL_STORAGE], perm_callback)
        else:
            project_screen.refresh_entries()

        return self.root

    def check_all_files_access(self):
        from jnius import autoclass
        PythonActivity = autoclass('org.kivy.android.PythonActivity')
        Environment = autoclass('android.os.Environment')
        if Environment.isExternalStorageManager():
            self.request_battery_optimization()
        else:
            # 直接跳转 —— 在 targetSdk=28/29 下会弹窗（Android 11–13）
            # Android 14 会跳设置，但权限仍可手动开启
            Settings = autoclass('android.provider.Settings')
            Intent = autoclass('android.content.Intent')
            Uri = autoclass('android.net.Uri')
            intent = Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION)
            uri = Uri.parse(f"package:{PythonActivity.mActivity.getPackageName()}")
            intent.setData(uri)
            PythonActivity.mActivity.startActivity(intent)
            self.show_popup(
                "All Files Access",
                "Please enable 'Allow access to manage all files' to scan /Download/kivy.\n\nOn Android 14, you may need to enable it manually in Settings."
            )

    def is_battery_optimization_ignored(self):
        from jnius import autoclass, cast
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        Context = autoclass("android.content.Context")
        PowerManager = autoclass("android.os.PowerManager")
        context = PythonActivity.mActivity.getApplicationContext()
        power_manager = cast(PowerManager, context.getSystemService(Context.POWER_SERVICE))
        if power_manager:
            package_name = context.getPackageName()
            return power_manager.isIgnoringBatteryOptimizations(package_name)
        return False

    def show_battery_optimization_popup(self):
        from jnius import autoclass
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        Intent = autoclass("android.content.Intent")
        Settings = autoclass("android.provider.Settings")
        Uri = autoclass("android.net.Uri")
        intent = Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS)
        package_uri = Uri.fromParts("package", PythonActivity.mActivity.getPackageName(), None)
        intent.setData(package_uri)
        PythonActivity.mActivity.startActivity(intent)

    def request_battery_optimization(self):
        if not self.is_battery_optimization_ignored():
            self.show_popup(
                "Keep Alive",
                "Please enable 'Ignore battery optimizations' to keep services running in background.",
                self.show_battery_optimization_popup,
            )
        else:
            self.root.get_screen('project_list').refresh_entries()

    def show_popup(self, title, message, callback=None):
        content = BoxLayout(orientation='vertical', padding=10, spacing=10)
        content.add_widget(Label(text=message, size_hint_y=0.8))
        btn_layout = BoxLayout(size_hint_y=0.2, spacing=10)
        if callback:
            btn_layout.add_widget(Button(text='OK', on_release=lambda x: [callback(), popup.dismiss()]))
        else:
            btn_layout.add_widget(Button(text='OK', on_release=lambda x: popup.dismiss()))
        content.add_widget(btn_layout)
        popup = Popup(title=title, content=content, size_hint=(0.8, 0.6))
        popup.open()

    def open_config_editor(self):
        self.root.current = 'config_editor'

    def go_back(self):
        self.root.current = 'project_list'