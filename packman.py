"""
packman.py - Runtime Package Manager for Kivy Launcher

Features:
- Install pure Python packages from PyPI (with version specifiers)
- Install binary packages from Termux repository
- Config stored in internal storage: /data/data/<package>/files/config.json
- Smart source selection: try Termux first, fallback to PyPI
- Explicit source control via `source` parameter

Author: User
"""

import os
import sys
import json
import re
import urllib.request
import tarfile
import zipfile
import shutil
from pathlib import Path
from typing import Optional, Dict, Tuple, Literal
from urllib.parse import urljoin, quote

# === 类型定义 ===
Source = Literal["termux", "pypi", "auto"]

import os
import sys
from pathlib import Path

def _get_app_package_name() -> str:
    """
    通过 Android Java API 获取当前应用的包名。
    
    Returns:
        str: 应用包名，如 "org.kivy.pygame" 或 "org.kivy.kivy_launcher"
    
    Raises:
        RuntimeError: 无法获取包名（非 Android 环境或 API 不可用）
    """
    try:
        # 尝试使用 pyjnius 调用 Android API
        from jnius import autoclass
        PythonActivity = autoclass('org.kivy.android.PythonActivity')
        activity = PythonActivity.mActivity
        context = activity.getApplicationContext()
        return context.getPackageName()
    except Exception as e:
        # 回退方案1: 检查环境变量
        if 'ANDROID_ARGUMENT' in os.environ:
            arg = os.environ['ANDROID_ARGUMENT']
            # ANDROID_ARGUMENT 格式: /data/user/0/package.name/files
            if arg.startswith('/data/user/0/'):
                pkg_part = arg[len('/data/user/0/'):].split('/', 1)[0]
                if pkg_part and '.' in pkg_part:
                    return pkg_part
        
        # 回退方案2: 检查 sys.executable
        exe = sys.executable
        if exe and '/data/app/' in exe:
            # 路径格式: /data/app/~~xxx~~/package.name-xxx==/lib/arm64/libpython3.x.so
            parts = exe.split('/data/app/')
            if len(parts) > 1:
                pkg_part = parts[1].split('/')[0]
                # 移除随机后缀: package.name-xxx== → package.name
                if '-' in pkg_part:
                    pkg_part = pkg_part.split('-')[0]
                if '.' in pkg_part:
                    return pkg_part
        
        raise RuntimeError(f"Cannot determine Android package name: {e}")


def _get_app_files_dir() -> str:
    """
    获取 Kivy Launcher 的私有 files 目录。
    
    使用 Java API 获取准确的包名，确保路径正确。
    
    Returns:
        str: 应用私有目录路径，例如 "/data/data/org.kivy.pygame/files"
    
    Raises:
        RuntimeError: 无法确定应用目录
    """
    try:
        package_name = _get_app_package_name()
        return f"/data/data/{package_name}/files"
    except Exception as e:
        # 最后的回退：尝试常见包名
        for pkg in ["org.kivy.pygame", "org.kivy.kivy_launcher"]:
            fallback = f"/data/data/{pkg}/files"
            if os.path.exists(fallback):
                return fallback
        raise RuntimeError(f"Cannot determine app private directory: {e}")

def _load_config() -> Dict:
    """
    从内部存储加载配置文件 config.json。
    
    配置文件路径: /data/data/<package>/files/config.json
    
    Returns:
        dict: 配置字典，包含默认值
    """
    default_config = {
        "termux_repo": "https://packages.termux.dev/apt/termux-main",
        "pypi_index_url": "https://pypi.org/simple",
        "pypi_trusted_host": "pypi.org"
    }
    
    config_path = Path(_get_app_files_dir()) / "config.json"
    if config_path.exists():
        try:
            with open(config_path, 'r') as f:
                user_config = json.load(f)
            # 合并默认配置
            config = default_config.copy()
            config.update(user_config)
            return config
        except Exception as e:
            print(f"⚠️  Warning: Failed to load config.json: {e}")
    
    return default_config


def _save_config(config: Dict) -> None:
    """
    保存配置到内部存储（供外部配置编辑器使用）。
    
    Args:
        config (dict): 要保存的配置
    """
    config_path = Path(_get_app_files_dir()) / "config.json"
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)


# === 工具函数 ===
def _parse_requirement(req: str) -> Tuple[str, str, str]:
    """
    解析包需求字符串。
    
    Args:
        req (str): 包需求，如 "requests", "scipy==1.10.0", "numpy>=1.20"
    
    Returns:
        tuple: (package_name, operator, version)
    
    Raises:
        ValueError: 无效的需求格式
    """
    req = req.strip()
    # 匹配包名（允许字母、数字、连字符、下划线）
    match = re.match(r'^([a-zA-Z0-9_-]+)', req)
    if not match:
        raise ValueError(f"Invalid package name in requirement: {req}")
    
    package_name = match.group(1).lower().replace('_', '-')
    remaining = req[len(package_name):].strip()
    
    if not remaining:
        return package_name, "", ""
    
    # 匹配操作符和版本
    op_match = re.match(r'^([<>=!]=?|~=)', remaining)
    if op_match:
        operator = op_match.group(1)
        version = remaining[len(operator):].strip()
        if not version:
            raise ValueError(f"Version missing in requirement: {req}")
        return package_name, operator, version
    
    raise ValueError(f"Invalid requirement format: {req}")


def _version_satisfies(installed: str, operator: str, required: str) -> bool:
    """
    检查已安装版本是否满足版本约束。
    
    Args:
        installed (str): 已安装的版本号
        operator (str): 操作符，如 "==", ">=", "<="
        required (str): 要求的版本号
    
    Returns:
        bool: 是否满足约束
    """
    if not operator:
        return True
    
    def normalize_version(v: str) -> list:
        """将版本字符串转换为可比较的列表"""
        # 移除预发布标识等
        v = re.sub(r'[^0-9.]+.*', '', v)
        parts = v.split('.')
        return [int(p) if p.isdigit() else 0 for p in parts]
    
    try:
        inst_parts = normalize_version(installed)
        req_parts = normalize_version(required)
        
        # 补齐较短的版本列表
        max_len = max(len(inst_parts), len(req_parts))
        inst_parts.extend([0] * (max_len - len(inst_parts)))
        req_parts.extend([0] * (max_len - len(req_parts)))
        
        if operator == '==':
            return inst_parts == req_parts
        elif operator == '>=':
            return inst_parts >= req_parts
        elif operator == '<=':
            return inst_parts <= req_parts
        elif operator == '>':
            return inst_parts > req_parts
        elif operator == '<':
            return inst_parts < req_parts
        elif operator == '!=':
            return inst_parts != req_parts
        elif operator == '~=':  # 兼容版本
            if len(req_parts) >= 2:
                # ~=1.4.5 等价于 >=1.4.5, ==1.4.*
                base = req_parts[:-1]
                inst_base = inst_parts[:len(base)]
                return inst_base == base and inst_parts >= req_parts
            return inst_parts >= req_parts
    except Exception:
        pass
    
    return False


def _get_project_name() -> str:
    """获取当前项目名称（基于 main.py 所在目录名）"""
    main_path = os.path.abspath(sys.argv[0])
    return os.path.basename(os.path.dirname(main_path))


# === Termux 包管理 ===
def _termux_package_exists(package_name: str) -> bool:
    """
    检查包是否存在于 Termux 仓库。
    
    Args:
        package_name (str): 包名（如 "scipy"）
    
    Returns:
        bool: 包是否存在
    """
    config = _load_config()
    ARCH = "aarch64"  # TODO: 检测实际架构
    deb_url = f"{config['termux_repo']}/{ARCH}/python-{package_name}_{ARCH}.deb"
    
    try:
        req = urllib.request.Request(deb_url, method='HEAD')
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.getcode() == 200
    except:
        return False


def _install_from_termux(package_name: str) -> bool:
    """
    从 Termux 仓库安装包（忽略版本，只安装最新版）。
    
    Args:
        package_name (str): 包名
    
    Returns:
        bool: 是否成功
    """
    config = _load_config()
    ARCH = "aarch64"
    PYTHON_VERSION = "3.11"  # TODO: 检测实际 Python 版本
    
    cache_dir = Path(_get_app_files_dir()) / "cache"
    pkg_cache = cache_dir / package_name
    if pkg_cache.exists():
        return True
    
    try:
        print(f"📥 Downloading {package_name} from Termux...")
        deb_url = f"{config['termux_repo']}/{ARCH}/python-{package_name}_{ARCH}.deb"
        deb_path = cache_dir / f"{package_name}.deb"
        cache_dir.mkdir(parents=True, exist_ok=True)
        
        urllib.request.urlretrieve(deb_url, deb_path)
        
        # 提取 data.tar.xz 从 .deb (ar 格式)
        data_tar = cache_dir / f"{package_name}_data.tar.xz"
        with open(deb_path, 'rb') as f:
            magic = f.read(8)
            if magic != b'!<arch>\n':
                raise ValueError("Invalid .deb file format")
            
            while True:
                header = f.read(60)
                if len(header) < 60:
                    break
                
                # 解析文件名（16字节）
                fname_bytes = header[:16]
                fname = fname_bytes.rstrip(b' \x00').decode('utf-8', errors='ignore')
                size = int(header[48:58].strip())
                
                if 'data.tar' in fname:
                    content = f.read(size)
                    with open(data_tar, 'wb') as out:
                        out.write(content)
                    break
                
                # 跳过文件内容和可能的填充字节
                f.read(size)
                if size % 2 == 1:
                    f.read(1)  # ar 格式要求偶数对齐
        
        # 解压 data.tar.xz
        temp_extract = cache_dir / f".tmp_{package_name}"
        temp_extract.mkdir()
        
        try:
            with tarfile.open(data_tar) as tar:
                tar.extractall(temp_extract)
            
            # 定位 Python 模块目录
            src_path = temp_extract / "data/data/com.termux/files/usr/lib" / f"python{PYTHON_VERSION}" / "site-packages"
            if not src_path.exists():
                # 尝试其他可能的 Python 版本
                lib_dir = temp_extract / "data/data/com.termux/files/usr/lib"
                for py_dir in lib_dir.glob("python*"):
                    site_pkgs = py_dir / "site-packages"
                    if site_pkgs.exists():
                        src_path = site_pkgs
                        break
                else:
                    raise FileNotFoundError(f"Python site-packages not found in package")
            
            # 复制到缓存
            shutil.copytree(src_path, pkg_cache, dirs_exist_ok=True)
            
        finally:
            # 清理临时文件
            if temp_extract.exists():
                shutil.rmtree(temp_extract)
            data_tar.unlink(missing_ok=True)
        
        deb_path.unlink(missing_ok=True)
        return True
        
    except Exception as e:
        print(f"❌ Termux installation failed: {e}")
        return False


# === PyPI 包管理 ===
def _install_from_pypi(package_name: str, operator: str = "", version: str = "") -> bool:
    """
    从 PyPI 安装纯 Python 包。
    
    注意：由于 Android 环境限制，只支持下载源码包（.tar.gz, .zip）并解压，
    不支持编译 C 扩展。
    
    Args:
        package_name (str): 包名
        operator (str): 版本操作符
        version (str): 版本号
    
    Returns:
        bool: 是否成功
    """
    config = _load_config()
    
    try:
        print(f"📦 Downloading {package_name} from PyPI...")
        index_url = config['pypi_index_url'].rstrip('/')
        package_index = f"{index_url}/{quote(package_name.lower())}/"
        
        # 获取包索引页面
        req = urllib.request.Request(package_index)
        req.add_header('User-Agent', 'packman/1.0')
        with urllib.request.urlopen(req, timeout=15) as response:
            html = response.read().decode('utf-8')
        
        # 查找源码包链接（.tar.gz 优先，然后 .zip）
        import re
        tar_links = re.findall(r'href=[\'"]?([^\'" >]+\.tar\.gz)[\'"]', html)
        zip_links = re.findall(r'href=[\'"]?([^\'" >]+\.zip)[\'"]', html)
        all_links = tar_links + zip_links
        
        if not all_links:
            raise ValueError("No source distributions found")
        
        # 如果指定了确切版本，优先匹配
        selected_link = None
        if operator == "==" and version:
            version_escaped = re.escape(version)
            for link in all_links:
                if re.search(f'{version_escaped}(?:\.post\d+)?\.(?:tar\.gz|zip)', link):
                    selected_link = link
                    break
        
        # 否则使用第一个链接（通常是最新版）
        if selected_link is None:
            selected_link = all_links[0]
        
        download_url = urljoin(package_index, selected_link)
        cache_dir = Path(_get_app_files_dir()) / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        
        # 下载包
        pkg_file = cache_dir / f"{package_name}_source{Path(selected_link).suffix}"
        urllib.request.urlretrieve(download_url, pkg_file)
        
        # 解压到缓存目录
        pkg_cache = cache_dir / package_name
        pkg_cache.mkdir(exist_ok=True)
        
        if pkg_file.suffix == '.gz':  # .tar.gz
            with tarfile.open(pkg_file) as tar:
                members = tar.getmembers()
                if not members:
                    raise ValueError("Empty archive")
                
                # 确定根目录名
                root_dir = members[0].name.split('/')[0]
                for member in members:
                    if member.name.startswith(root_dir + '/') and len(member.name) > len(root_dir):
                        # 移除根目录前缀
                        relative_path = '/'.join(member.name.split('/')[1:])
                        if relative_path:
                            target = pkg_cache / relative_path
                            target.parent.mkdir(parents=True, exist_ok=True)
                            if member.isfile():
                                tar.extract(member, pkg_cache)
                                # 重命名以移除根目录
                                extracted = pkg_cache / member.name
                                if extracted.exists():
                                    shutil.move(str(extracted), str(target))
        
        else:  # .zip
            with zipfile.ZipFile(pkg_file) as zf:
                namelist = zf.namelist()
                if not namelist:
                    raise ValueError("Empty archive")
                
                root_dir = namelist[0].split('/')[0]
                for name in namelist:
                    if name.startswith(root_dir + '/') and len(name) > len(root_dir) + 1:
                        relative_path = '/'.join(name.split('/')[1:])
                        target = pkg_cache / relative_path
                        target.parent.mkdir(parents=True, exist_ok=True)
                        if not name.endswith('/'):
                            with zf.open(name) as src, open(target, 'wb') as dst:
                                dst.write(src.read())
        
        pkg_file.unlink()
        return True
        
    except Exception as e:
        print(f"❌ PyPI installation failed: {e}")
        return False


# === 公共 API ===
def get_config() -> dict:
    """
    获取当前配置。
    
    Returns:
        dict: 配置字典
    """
    return _load_config()


def save_config(config: dict) -> None:
    """
    保存配置（供外部配置编辑器使用）。
    
    Args:
        config (dict): 要保存的配置
    """
    _save_config(config)


def get_cache_dir() -> str:
    """
    获取全局包缓存目录路径。
    
    Returns:
        str: 缓存目录路径
    """
    return str(Path(_get_app_files_dir()) / "cache")


def get_project_site_packages(project_name: Optional[str] = None) -> str:
    """
    获取项目专属 site-packages 目录路径。
    
    Args:
        project_name (str, optional): 项目名称，默认为当前项目
    
    Returns:
        str: site-packages 目录路径
    """
    if project_name is None:
        project_name = _get_project_name()
    
    site_dir = Path(_get_app_files_dir()) / "projects" / project_name / "site-packages"
    site_dir.mkdir(parents=True, exist_ok=True)
    return str(site_dir)


def ensure_project_site_packages() -> str:
    """
    确保当前项目的 site-packages 目录在 sys.path 中。
    
    Returns:
        str: site-packages 目录路径
    """
    site_dir = get_project_site_packages()
    if site_dir not in sys.path:
        sys.path.insert(0, site_dir)
    return site_dir


def is_installed(requirement: str, project_name: Optional[str] = None) -> bool:
    """
    检查包是否已安装并满足版本要求。
    
    Args:
        requirement (str): 包需求字符串
        project_name (str, optional): 项目名称
    
    Returns:
        bool: 是否满足要求
    """
    try:
        pkg_name, op, ver = _parse_requirement(requirement)
        site_dir = Path(get_project_site_packages(project_name))
        
        # 临时添加到 sys.path 进行检查
        original_path = sys.path[:]
        sys.path.insert(0, str(site_dir))
        try:
            mod = __import__(pkg_name)
            installed_ver = getattr(mod, '__version__', '0.0.0')
            return _version_satisfies(installed_ver, op, ver)
        except ImportError:
            return False
        finally:
            sys.path[:] = original_path
    except Exception:
        return False


def install(
    requirement: str,
    project_name: Optional[str] = None,
    source: Source = "auto"
) -> bool:
    """
    安装包到指定项目。
    
    Args:
        requirement (str): 包需求，如 "requests", "scipy==1.10.0"
        project_name (str, optional): 项目名称，默认当前项目
        source (str): 安装源，可选 "termux", "pypi", "auto"
                     - "auto": 先检查 Termux 是否存在，存在则用 Termux，否则用 PyPI
                     - "termux": 强制从 Termux 安装
                     - "pypi": 强制从 PyPI 安装
    
    Returns:
        bool: 是否成功安装
    
    Examples:
        install("scipy")                           # auto
        install("scipy", source="termux")          # 强制 Termux
        install("requests", source="pypi")         # 强制 PyPI
        install("numpy>=1.20", project_name="myapp")
    """
    pkg_name, op, ver = _parse_requirement(requirement)
    
    # 检查是否已满足
    if is_installed(requirement, project_name):
        print(f"✅ {requirement} already satisfied")
        return True
    
    success = False
    
    if source == "termux":
        success = _install_from_termux(pkg_name)
    elif source == "pypi":
        success = _install_from_pypi(pkg_name, op, ver)
    else:  # auto
        # 先检查 Termux 是否有这个包
        if _termux_package_exists(pkg_name):
            print(f"🔍 Found {pkg_name} in Termux repository")
            success = _install_from_termux(pkg_name)
        else:
            print(f"🔍 {pkg_name} not in Termux, using PyPI")
            success = _install_from_pypi(pkg_name, op, ver)
    
    if not success:
        print(f"❌ Failed to install {requirement}")
        return False
    
    # 创建符号链接到项目目录
    cache_dir = Path(get_cache_dir())
    pkg_cache = cache_dir / pkg_name
    if pkg_cache.exists():
        site_dir = Path(get_project_site_packages(project_name))
        for item in pkg_cache.iterdir():
            link_path = site_dir / item.name
            if not link_path.exists():
                try:
                    link_path.symlink_to(item, target_is_directory=item.is_dir())
                except OSError:
                    # 如果符号链接失败，复制文件（兼容性）
                    if item.is_dir():
                        shutil.copytree(item, link_path)
                    else:
                        shutil.copy2(item, link_path)
    
    print(f"✅ Successfully installed {requirement}")
    return True