import sys
import os
import traceback
import logging
import webbrowser
from typing import Dict, Optional, Union, List
from dataclasses import dataclass, field
from enum import Enum

try:
    import orjson as json
    USE_ORJSON = True
except ImportError:
    import json
    USE_ORJSON = False

import requests
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QTableWidget,
    QTableWidgetItem, QPushButton, QLabel, QGroupBox, QHeaderView,
    QTreeWidget, QTreeWidgetItem, QLineEdit, QComboBox, QMessageBox
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QFont, QColor
from qfluentwidgets import (
    FluentWindow, NavigationItemPosition, FluentIcon, setTheme, Theme,
    InfoBar, InfoBarPosition, ListWidget, ProgressRing, BodyLabel,
    PushButton, PrimaryPushButton
)

API_BASE = "https://autopatch.hk4e.com/pkg_version"
API_BASE_FALLBACK = ""

GAME_CONFIG = {
    "hk4e": {"name": "原神", "short_name": "原神", "voice": ["汉语", "英语", "日语", "韩语"]},
    "hkrpg": {"name": "崩坏·星穹铁道", "short_name": "星铁", "voice": []},
    "nap": {"name": "绝区零", "short_name": "绝区零", "voice": ["汉语", "英语", "日语", "韩语"]},
    "bh3": {"name": "崩坏3", "short_name": "崩坏3", "voice": []},
}

VOICEPACK_LIST = {
    "汉语": "Audio_Chinese_pkg_version",
    "英语": "Audio_English(US)_pkg_version",
    "日语": "Audio_Japanese_pkg_version",
    "韩语": "Audio_Korean_pkg_version"
}

DEFAULT_GAME = "hk4e"

class LogLevel(Enum):
    DEBUG = logging.DEBUG
    INFO = logging.INFO
    WARNING = logging.WARNING
    ERROR = logging.ERROR
    CRITICAL = logging.CRITICAL

LOG_LEVEL = os.getenv('HOYO_LOG_LEVEL', 'ERROR').upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.ERROR),
    format='[%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)

logger = logging.getLogger('HoyoFiles')

def debug(msg: str):
    logger.debug(msg)

def info(msg: str):
    logger.info(msg)

def warning(msg: str):
    logger.warning(msg)

def error(msg: str):
    logger.error(msg)

def critical(msg: str):
    logger.critical(msg)

def perf(msg: str):
    if LOG_LEVEL in ['DEBUG', 'INFO']:
        print(f"[PERF] {msg}")

class NodeType(Enum):
    FILE = "file"
    DIRECTORY = "dir"

@dataclass
class PkgVersionFile:
    remoteName: str
    md5: str
    fileSize: int
    hash: Optional[str] = None

@dataclass
class FileNode:
    type: NodeType
    name: str
    size: int
    children: List['FileNode'] = field(default_factory=list)
    fileData: Optional[PkgVersionFile] = None

@dataclass
class FileInfo:
    name: str
    url: str
    checksum: str
    size: int
    type: str = ""

@dataclass
class ChunkInfo:
    branch: str
    package_id: str
    password: str
    tag: str

@dataclass
class ChunkManifest:
    category_id: str
    category_name: str
    manifest: Dict
    stats: Dict

@dataclass
class ChunkData:
    build_id: str
    tag: str
    manifests: List[ChunkManifest]

@dataclass
class VersionData:
    game: Dict
    voice: Dict
    update: Dict
    decompressed_path: Optional[str]
    chunk: Optional[ChunkInfo]

def format_bytes(size: Union[int, str]) -> str:
    if isinstance(size, str):
        size = int(size)
    if size < 0:
        return "未知"

    units = ['B', 'KB', 'MB', 'GB', 'TB']
    i = 0
    size_float = float(size)
    while size_float >= 1024 and i < len(units) - 1:
        size_float /= 1024
        i += 1
    return f"{size_float:.2f} {units[i]}"

def copy_to_clipboard(text: str):
    clipboard = QApplication.clipboard()
    clipboard.setText(text)

def open_link(url: str):
    webbrowser.open(url)

def show_message(parent, title: str, message: str, msg_type: str = "info"):
    if msg_type == "info":
        QMessageBox.information(parent, title, message)
    elif msg_type == "warning":
        QMessageBox.warning(parent, title, message)
    elif msg_type == "error":
        QMessageBox.critical(parent, title, message)
    elif msg_type == "success":
        QMessageBox.information(parent, "成功", message)

class APIClient:

    def __init__(self):
        self.api_base = API_BASE
        self.use_fallback = False

    def _get_url(self, path: str) -> str:
        return f"{self.api_base}/{path}"

    def fetch_version_list(self, game: str) -> Dict:
        url = self._get_url(f"{game}_versions.json")
        debug(f"请求版本列表: {url}")
        try:
            response = requests.get(url, timeout=10)
            debug(f"响应状态码: {response.status_code}")
            response.raise_for_status()

            if USE_ORJSON:
                data = json.loads(response.content)
            else:
                data = response.json()

            debug(f"成功获取版本列表，共 {len(data)} 个版本")
            return data
        except Exception as e:
            error(f"请求失败: {str(e)}")
            if not self.use_fallback and API_BASE_FALLBACK:
                debug(f"尝试使用备用源: {API_BASE_FALLBACK}")
                self.use_fallback = True
                self.api_base = API_BASE_FALLBACK
                return self.fetch_version_list(game)
            raise Exception(f"版本列表加载失败: {str(e)}")

    def fetch_pkg_version(self, game: str, version: str, filename: str) -> str:
        url = self._get_url(f"{game}/{version}/{filename}")
        debug(f"请求文件: {url}")
        response = requests.get(url, timeout=30)
        debug(f"响应状态码: {response.status_code}")
        response.raise_for_status()
        debug(f"成功获取文件，大小: {len(response.text)} 字节")
        return response.text

    def fetch_chunk_data(self, game: str, version: str) -> Dict:
        url = self._get_url(f"chunk/{game}_{version}.json")
        debug(f"请求 chunk 数据: {url}")
        response = requests.get(url, timeout=10)
        debug(f"响应状态码: {response.status_code}")
        response.raise_for_status()
        data = response.json()
        debug("成功获取 chunk 数据")
        return data

class GameSelector(QWidget):
    game_selected = Signal(str)

    # 游戏对应的 emoji 图标
    GAME_EMOJI = {
        "hk4e": "🎮",
        "hkrpg": "🚂", 
        "nap": "⚡",
        "bh3": "🔥"
    }

    def __init__(self):
        super().__init__()
        self.current_game = DEFAULT_GAME
        self.buttons = {}
        self.init_ui()

    def init_ui(self):
        self.setFixedWidth(70)
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.setSpacing(8)
        layout.setContentsMargins(5, 5, 5, 5)

        for game_key, game_config in GAME_CONFIG.items():
            btn = PushButton(self.GAME_EMOJI.get(game_key, "🎮"))
            btn.setObjectName(f"gameBtn_{game_key}")
            btn.setCheckable(True)
            btn.setFixedSize(60, 60)
            btn.setToolTip(game_config['name'])
            
            font = QFont()
            font.setPointSize(18)
            btn.setFont(font)
            
            btn.clicked.connect(lambda checked, g=game_key: self.select_game(g))

            if game_key == self.current_game:
                btn.setChecked(True)

            self.buttons[game_key] = btn
            layout.addWidget(btn)

        layout.addStretch()
        self.setLayout(layout)

    def select_game(self, game: str):
        if game != self.current_game:
            for key, btn in self.buttons.items():
                btn.setChecked(key == game)

            self.current_game = game
            self.game_selected.emit(game)

class VersionList(QWidget):
    version_selected = Signal(str)

    def __init__(self):
        super().__init__()
        self.init_ui()

    def init_ui(self):
        self.setMaximumWidth(150)
        layout = QVBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)

        loading_widget = QWidget()
        loading_layout = QVBoxLayout(loading_widget)
        loading_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_ring = ProgressRing()
        self.progress_ring.setObjectName("progressRing")
        self.loading_label = BodyLabel("加载中...")
        self.loading_label.setObjectName("loadingLabel")
        loading_layout.addWidget(self.progress_ring)
        loading_layout.addWidget(self.loading_label)
        self.loading_widget = loading_widget
        self.loading_widget.setObjectName("loadingWidget")
        self.loading_widget.hide()
        layout.addWidget(self.loading_widget)

        self.list_widget = ListWidget()
        self.list_widget.setObjectName("versionListWidget")
        self.list_widget.currentTextChanged.connect(self.on_selection_changed)
        layout.addWidget(self.list_widget)

        self.setLayout(layout)

    def set_loading(self, loading: bool):
        if loading:
            self.loading_widget.show()
            self.list_widget.hide()
        else:
            self.loading_widget.hide()
            self.list_widget.show()

    def set_versions(self, versions: list):
        self.list_widget.clear()
        self.list_widget.addItems(versions)

    def select_version(self, version: str):
        items = self.list_widget.findItems(version, Qt.MatchFlag.MatchExactly)
        if items:
            self.list_widget.setCurrentItem(items[0])

    def on_selection_changed(self, version: str):
        if version:
            self.version_selected.emit(version)

class PackageTab(QWidget):

    def __init__(self, api_client: APIClient):
        super().__init__()
        self.api_client = api_client
        self.game_packages = []
        self.update_packages = {}
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        game_group = QGroupBox("游戏包")
        game_layout = QVBoxLayout()

        game_btn_layout = QHBoxLayout()
        self.game_copy_all_btn = PushButton("复制全部链接")
        self.game_copy_all_btn.clicked.connect(self.copy_game_packages)
        game_btn_layout.addWidget(self.game_copy_all_btn)
        game_btn_layout.addStretch()
        game_layout.addLayout(game_btn_layout)

        self.game_table = self.create_package_table()
        game_layout.addWidget(self.game_table)
        game_group.setLayout(game_layout)
        layout.addWidget(game_group)

        update_group = QGroupBox("更新包")
        update_layout = QVBoxLayout()

        update_btn_layout = QHBoxLayout()
        self.update_copy_all_btn = PushButton("复制全部链接")
        self.update_copy_all_btn.clicked.connect(self.copy_update_packages)
        update_btn_layout.addWidget(self.update_copy_all_btn)
        update_btn_layout.addStretch()
        update_layout.addLayout(update_btn_layout)

        self.update_table = self.create_package_table()
        update_layout.addWidget(self.update_table)
        update_group.setLayout(update_layout)
        layout.addWidget(update_group)

        self.setLayout(layout)

    def create_package_table(self) -> QTableWidget:
        table = QTableWidget()
        table.setColumnCount(5)
        table.setHorizontalHeaderLabels(["文件名", "类型", "大小", "校验和", "操作"])

        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)

        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)

        return table

    def _set_table_empty(self, table: QTableWidget, message: str):
        """设置表格为空状态，显示提示信息"""
        for row in range(table.rowCount()):
            widget = table.cellWidget(row, 4)
            if widget:
                table.removeCellWidget(row, 4)
                widget.deleteLater()
        table.clearContents()
        table.clearSpans()
        table.setRowCount(1)
        table.setSpan(0, 0, 1, 5)
        item = QTableWidgetItem(message)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        item.setFont(QFont("", 10))
        item.setForeground(QColor(128, 128, 128))
        table.setItem(0, 0, item)

    def _extract_packages(self, data: dict, pkg_type: str) -> list:
        """从数据中提取包列表"""
        packages = []
        if data.get('game'):
            packages.append({**data['game'], 'type': pkg_type})
        for voice_pkg in data.get('voice', {}).values():
            packages.append({**voice_pkg, 'type': '语音包'})
        return packages

    def load_data(self, version_data: dict):
        # 游戏包
        self.game_packages = []
        if version_data.get('game', {}).get('full'):
            self.game_packages.append({**version_data['game']['full'], 'type': '游戏本体'})
        for segment in version_data.get('game', {}).get('segments', []):
            self.game_packages.append({**segment, 'type': '游戏本体(分卷)'})
        for voice_pkg in version_data.get('voice', {}).values():
            self.game_packages.append({**voice_pkg, 'type': '语音包'})

        if self.game_packages:
            self.game_table.clearSpans()
            self.populate_table(self.game_table, self.game_packages)
            self.game_copy_all_btn.setEnabled(True)
        else:
            self._set_table_empty(self.game_table, "该版本不提供游戏包下载信息")
            self.game_copy_all_btn.setEnabled(False)

        # 更新包
        self.update_packages = {
            ver: self._extract_packages({'game': data.get('game'), 'voice': data.get('voice', {})}, '游戏本体')
            for ver, data in version_data.get('update', {}).items()
        }
        all_updates = [
            {**pkg, 'version': ver}
            for ver, packages in self.update_packages.items()
            for pkg in packages
        ]

        if all_updates:
            self.update_table.clearSpans()
            self.populate_table(self.update_table, all_updates, show_version=True)
            self.update_copy_all_btn.setEnabled(True)
        else:
            self._set_table_empty(self.update_table, "该版本不提供更新包下载信息")
            self.update_copy_all_btn.setEnabled(False)

    def populate_table(self, table: QTableWidget, packages: list, show_version: bool = False):
        if not packages:
            return

        table.clearContents()
        table.clearSpans()
        table.setRowCount(len(packages))

        for row, pkg in enumerate(packages):
            name = f"[{pkg.get('version', '')}] {pkg.get('name', '')}" if show_version else pkg.get('name', '')
            table.setItem(row, 0, QTableWidgetItem(name))
            table.setItem(row, 1, QTableWidgetItem(pkg.get('type', '')))
            table.setItem(row, 2, QTableWidgetItem(format_bytes(pkg.get('size', 0))))
            table.setItem(row, 3, QTableWidgetItem(pkg.get('checksum', '')))

            btn_widget = QWidget()
            btn_layout = QHBoxLayout(btn_widget)
            btn_layout.setContentsMargins(2, 2, 2, 2)

            url = pkg.get('url', '')
            copy_btn = PushButton("复制")
            copy_btn.clicked.connect(lambda checked, u=url: self.copy_url(u))
            btn_layout.addWidget(copy_btn)

            download_btn = PrimaryPushButton("下载")
            download_btn.clicked.connect(lambda checked, u=url: open_link(u))
            btn_layout.addWidget(download_btn)

            table.setCellWidget(row, 4, btn_widget)

    def copy_url(self, url: str):
        copy_to_clipboard(url)
        show_message(self, "成功", "链接已复制到剪贴板", "success")

    def _copy_urls(self, urls: list):
        """复制 URL 列表到剪贴板"""
        if not urls:
            show_message(self, "提示", "没有可复制的链接", "info")
            return
        copy_to_clipboard('\n'.join(urls))
        show_message(self, "成功", f"已复制 {len(urls)} 个链接", "success")

    def copy_game_packages(self):
        self._copy_urls([pkg.get('url', '') for pkg in self.game_packages])

    def copy_update_packages(self):
        self._copy_urls([pkg.get('url', '') for pkgs in self.update_packages.values() for pkg in pkgs])

class LoadFileListWorker(QThread):
    finished = Signal(object)
    error = Signal(str)
    progress = Signal(str)

    def __init__(self, api_client: APIClient, game: str, version: str,
                 voice_packs: list, decompressed_path: str, parent=None):
        super().__init__(parent)
        self.api_client = api_client
        self.game = game
        self.version = version
        self.voice_packs = voice_packs
        self.decompressed_path = decompressed_path
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            import time
            start_time = time.time()

            if self._is_cancelled:
                return

            self.progress.emit("正在加载游戏文件列表...")

            game_data = self.api_client.fetch_pkg_version(
                self.game, self.version, 'pkg_version'
            )

            if self._is_cancelled:
                return

            if USE_ORJSON:
                file_data = [json.loads(line) for line in game_data.split('\n') if line.strip()]
            else:
                import json as json_lib
                file_data = [json_lib.loads(line) for line in game_data.split('\n') if line.strip()]

            for voice in self.voice_packs:
                if self._is_cancelled:
                    return

                if voice in VOICEPACK_LIST:
                    self.progress.emit(f"正在加载语音包: {voice}...")
                    try:
                        voice_data = self.api_client.fetch_pkg_version(
                            self.game, self.version, VOICEPACK_LIST[voice]
                        )
                        if USE_ORJSON:
                            voice_files = [json.loads(line) for line in voice_data.split('\n') if line.strip()]
                        else:
                            import json as json_lib
                            voice_files = [json_lib.loads(line) for line in voice_data.split('\n') if line.strip()]
                        file_data.extend(voice_files)
                    except Exception as e:
                        if not self._is_cancelled:
                            self.error.emit(f"语音包 [{voice}] 加载失败: {str(e)}")

            if self._is_cancelled:
                return

            self.progress.emit("正在构建文件树...")

            root = FileNode(
                type=NodeType.DIRECTORY,
                name='',
                size=0,
                children=[]
            )

            dir_cache = {'': root}

            for file in file_data:
                path_parts = file['remoteName'].replace('\\', '/').split('/')
                file_size = file['fileSize']

                current_path = ''
                for i, part in enumerate(path_parts[:-1]):
                    parent_path = current_path
                    current_path = f"{current_path}/{part}" if current_path else part

                    if current_path not in dir_cache:
                        new_dir = FileNode(
                            type=NodeType.DIRECTORY,
                            name=part,
                            size=0,
                            children=[]
                        )
                        dir_cache[parent_path].children.append(new_dir)
                        dir_cache[current_path] = new_dir

                    dir_cache[current_path].size += file_size

                parent_path = '/'.join(path_parts[:-1])
                parent_node = dir_cache.get(parent_path, root)
                parent_node.children.append(FileNode(
                    type=NodeType.FILE,
                    name=path_parts[-1],
                    size=file_size,
                    children=[],
                    fileData=PkgVersionFile(
                        remoteName=file['remoteName'],
                        md5=file['md5'],
                        fileSize=file_size,
                        hash=file.get('hash')
                    )
                ))

            self.sort_tree(root)

            elapsed = time.time() - start_time
            debug(f"文件树构建耗时: {elapsed:.2f}秒")

            if not self._is_cancelled:
                self.finished.emit({
                    'tree': root,
                    'count': len(file_data),
                    'size': root.size
                })
        except Exception as e:
            if not self._is_cancelled:
                self.error.emit(str(e))

    def sort_tree(self, node: FileNode):
        node.children.sort(key=lambda x: (x.type != NodeType.DIRECTORY, x.name))
        for child in node.children:
            if child.type == NodeType.DIRECTORY:
                self.sort_tree(child)

class FileBrowserTab(QWidget):

    def __init__(self, api_client: APIClient):
        super().__init__()
        self.api_client = api_client
        self.file_tree = None
        self.decompressed_path = None
        self.current_game = ""
        self.current_version = ""
        self.available_voices = []
        self.worker = None
        self.load_timer = None
        self.file_cache = {}

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        toolbar = QHBoxLayout()

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索文件名...")
        self.search_input.textChanged.connect(self.on_search)
        toolbar.addWidget(QLabel("搜索:"))
        toolbar.addWidget(self.search_input)

        self.voice_combo = QComboBox()
        self.voice_combo.addItem("不加载语音包", [])
        self.voice_combo.currentIndexChanged.connect(self.on_voice_changed)
        toolbar.addWidget(QLabel("语音包:"))
        toolbar.addWidget(self.voice_combo)

        self.refresh_btn = PushButton("刷新")
        self.refresh_btn.clicked.connect(self.refresh_file_list)
        toolbar.addWidget(self.refresh_btn)

        toolbar.addStretch()
        layout.addLayout(toolbar)

        self.stats_label = QLabel("文件数量: 0 | 总大小: 0 B")
        self.stats_label.setStyleSheet("padding: 5px; background-color: #f0f0f0; border-radius: 3px;")
        layout.addWidget(self.stats_label)

        self.tree_widget = QTreeWidget()
        self.tree_widget.setHeaderLabels(["名称", "大小", "操作"])
        self.tree_widget.setColumnWidth(0, 400)
        self.tree_widget.setColumnWidth(1, 120)
        self.tree_widget.itemExpanded.connect(self.on_item_expanded)
        self.tree_widget.setUniformRowHeights(True)
        self.tree_widget.setAnimated(False)

        header = self.tree_widget.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)

        layout.addWidget(self.tree_widget)

        self.setLayout(layout)

    def load_data(self, game: str, version: str, version_data: dict, available_voices: list):
        is_same = (self.current_game == game and self.current_version == version)
        voices_changed = (self.available_voices != available_voices)

        self.current_game = game
        self.current_version = version
        self.decompressed_path = version_data.get('decompressed_path')
        self.available_voices = available_voices

        # 只在语音包列表变化时重建 combo
        if voices_changed:
            self.voice_combo.blockSignals(True)
            current_selection = self.voice_combo.currentIndex()
            self.voice_combo.clear()
            self.voice_combo.addItem("不加载语音包", [])
            for voice in available_voices:
                self.voice_combo.addItem(voice, [voice])
            if len(available_voices) > 1:
                self.voice_combo.addItem("全部语音包", available_voices)
            # 恢复之前的选择
            if current_selection < self.voice_combo.count():
                self.voice_combo.setCurrentIndex(current_selection)
            self.voice_combo.blockSignals(False)

        if is_same and not voices_changed:
            print(f"[INFO] 相同的游戏和版本，跳过加载")
            return

        if self.load_timer:
            self.load_timer.stop()
            self.load_timer.deleteLater()
            self.load_timer = None

        self.load_timer = QTimer(self)
        self.load_timer.setSingleShot(True)
        self.load_timer.timeout.connect(self.refresh_file_list)
        self.load_timer.start(300)

    def refresh_file_list(self):
        if not self.current_game or not self.current_version:
            return

        voice_packs = self.voice_combo.currentData() or []
        voice_packs_tuple = tuple(sorted(voice_packs))
        cache_key = (self.current_game, self.current_version, voice_packs_tuple)

        if cache_key in self.file_cache:
            print(f"[INFO] 从缓存加载文件列表: {cache_key}")
            self.on_file_list_loaded(self.file_cache[cache_key])
            return

        if self.worker and self.worker.isRunning():
            print("[INFO] 取消之前的文件加载任务")
            self.worker.cancel()
            self.worker.wait(2000)
            self.worker.deleteLater()
            self.worker = None

        self.stats_label.setText("正在加载文件列表...")
        self.tree_widget.clear()

        self.worker = LoadFileListWorker(
            self.api_client,
            self.current_game,
            self.current_version,
            voice_packs,
            self.decompressed_path,
            self
        )
        self.worker.finished.connect(lambda data: self.on_file_list_loaded(data, cache_key))
        self.worker.error.connect(self.on_load_error)
        self.worker.progress.connect(self.on_progress)
        self.worker.start()

    def on_progress(self, message: str):
        self.stats_label.setText(message)

    def on_file_list_loaded(self, data: dict, cache_key=None):
        print(f"[INFO] 文件列表加载完成，共 {data['count']} 个文件")

        if cache_key:
            self.file_cache[cache_key] = data
            print(f"[INFO] 缓存文件列表: {cache_key}")

        self.file_tree = data['tree']
        self.stats_label.setText(
            f"文件数量: {data['count']} | 总大小: {format_bytes(data['size'])}"
        )

        self.populate_tree()

    def on_load_error(self, error: str):
        print(f"[ERROR] 文件列表加载失败: {error}")
        self.stats_label.setText(f"加载失败: {error}")

    def on_voice_changed(self, index: int):
        pass

    def on_search(self, text: str):
        self.populate_tree(text)

    def populate_tree(self, search_text: str = ""):
        import time
        start_time = time.time()

        self.tree_widget.clear()

        if not self.file_tree:
            return

        self.tree_widget.setUpdatesEnabled(False)
        self.tree_widget.setSortingEnabled(False)

        try:
            if search_text:
                results = self.search_files(self.file_tree, search_text.lower())
                max_results = 500

                items = []
                for i, (path, node) in enumerate(results):
                    if i >= max_results:
                        item = QTreeWidgetItem()
                        item.setText(0, f"... 还有 {len(results) - max_results} 个结果未显示")
                        items.append(item)
                        break
                    item = self.create_search_result_item(path, node)
                    items.append(item)

                self.tree_widget.addTopLevelItems(items)
            else:
                items = []
                for child in self.file_tree.children:
                    item = self.create_tree_item(child, "", lazy=True)
                    items.append(item)

                self.tree_widget.addTopLevelItems(items)
        finally:
            self.tree_widget.setSortingEnabled(True)
            self.tree_widget.setUpdatesEnabled(True)

            elapsed = time.time() - start_time
            debug(f"UI 渲染耗时: {elapsed:.2f}秒")

    def search_files(self, node: FileNode, keyword: str, path: str = "") -> list:
        results = []
        current_path = f"{path}/{node.name}" if path else node.name

        if node.type == NodeType.FILE:
            if keyword in node.name.lower() or keyword in current_path.lower():
                results.append((current_path, node))
        else:
            for child in node.children:
                results.extend(self.search_files(child, keyword, current_path))

        return results

    def create_search_result_item(self, path: str, node: FileNode) -> QTreeWidgetItem:
        item = QTreeWidgetItem()
        item.setText(0, f"{path}")
        item.setText(1, format_bytes(node.size))

        if node.type == NodeType.FILE and node.fileData:
            item.setData(2, Qt.ItemDataRole.UserRole, node.fileData)

        return item

    def create_tree_item(self, node: FileNode, path: str, lazy: bool = False) -> QTreeWidgetItem:
        item = QTreeWidgetItem()

        if node.type == NodeType.DIRECTORY:
            item.setText(0, f"📁 {node.name} ({len(node.children)})")
            item.setData(0, Qt.ItemDataRole.UserRole, (node, path))
        else:
            item.setText(0, f"📄 {node.name}")

        item.setText(1, format_bytes(node.size))

        if node.type == NodeType.FILE and node.fileData:
            item.setData(2, Qt.ItemDataRole.UserRole, node.fileData)

        if node.type == NodeType.DIRECTORY:
            if lazy and len(node.children) > 0:
                placeholder = QTreeWidgetItem()
                placeholder.setText(0, "加载中...")
                item.addChild(placeholder)
                item.setExpanded(False)
            else:
                for child in node.children:
                    child_item = self.create_tree_item(child, f"{path}/{node.name}" if path else node.name, lazy=False)
                    item.addChild(child_item)

        return item

    def add_file_buttons(self, item: QTreeWidgetItem, file_data: PkgVersionFile):
        btn_widget = QWidget()
        btn_layout = QHBoxLayout(btn_widget)
        btn_layout.setContentsMargins(2, 2, 2, 2)

        if self.decompressed_path:
            download_btn = QPushButton("下载")
            url = f"{self.decompressed_path}/{file_data.remoteName}"
            download_btn.clicked.connect(lambda: open_link(url))
            btn_layout.addWidget(download_btn)

        if file_data.md5:
            md5_btn = QPushButton("MD5")
            md5_btn.clicked.connect(lambda: self.copy_hash(file_data.md5, "MD5"))
            btn_layout.addWidget(md5_btn)

        if file_data.hash:
            hash_btn = QPushButton("Hash")
            hash_btn.clicked.connect(lambda: self.copy_hash(file_data.hash, "Hash"))
            btn_layout.addWidget(hash_btn)

        self.tree_widget.setItemWidget(item, 2, btn_widget)

    def copy_hash(self, hash_value: str, hash_type: str):
        copy_to_clipboard(hash_value)
        show_message(self, "成功", f"{hash_type} 已复制到剪贴板", "success")

    def on_item_expanded(self, item: QTreeWidgetItem):
        if item.childCount() == 1:
            first_child = item.child(0)
            if first_child.text(0) == "加载中...":
                item.removeChild(first_child)

                data = item.data(0, Qt.ItemDataRole.UserRole)
                if data:
                    node, path = data
                    for child in node.children:
                        child_item = self.create_tree_item(child, f"{path}/{node.name}" if path else node.name, lazy=True)
                        item.addChild(child_item)

class LoadVersionWorker(QThread):
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, api_client: APIClient, game: str, parent=None):
        super().__init__(parent)
        self.api_client = api_client
        self.game = game
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            if self._is_cancelled:
                return
            data = self.api_client.fetch_version_list(self.game)
            if not self._is_cancelled:
                self.finished.emit(data)
        except Exception as e:
            if not self._is_cancelled:
                self.error.emit(str(e))

class MainWindow(FluentWindow):

    def __init__(self, api_client=None, test_mode=False):
        super().__init__()
        self.api_client = api_client or APIClient()
        self.test_mode = test_mode
        self.current_game = DEFAULT_GAME
        self.current_version = ""
        self.version_data = {}
        self.version_list_data = {}
        self.version_worker = None
        self.load_timer = None

        self.version_cache = {}
        self.preload_workers = []
        self.is_initial_loading = True
        self.preload_total = 0
        self.preload_completed = 0
        
        # 文件浏览器懒加载标志
        self.file_browser_visited = False
        self.file_browser_needs_refresh = False

        self.init_ui()

        if not test_mode:
            self.load_game_versions(self.current_game)
            QTimer.singleShot(1000, self.preload_all_games)

    def init_ui(self):
        self.setWindowTitle("HoyoFiles - 米哈游游戏文件浏览器")
        self.setMinimumSize(1200, 800)
        self.setObjectName("mainWindow")

        setTheme(Theme.AUTO)

        self.home_interface = QWidget()
        self.home_interface.setObjectName("homeInterface")
        home_layout = QHBoxLayout(self.home_interface)
        home_layout.setContentsMargins(5, 10, 10, 10)
        home_layout.setSpacing(5)

        self.game_selector = GameSelector()
        self.game_selector.setObjectName("gameSelector")
        self.game_selector.game_selected.connect(self.on_game_selected)
        home_layout.addWidget(self.game_selector)

        self.version_list = VersionList()
        self.version_list.setObjectName("versionList")
        self.version_list.version_selected.connect(self.on_version_selected)
        home_layout.addWidget(self.version_list)

        content_widget = QWidget()
        content_widget.setObjectName("contentWidget")
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)

        self.package_tab = PackageTab(self.api_client)
        self.package_tab.setObjectName("packageTab")
        content_layout.addWidget(self.package_tab)

        self.file_browser_tab = FileBrowserTab(self.api_client)
        self.file_browser_tab.setObjectName("fileBrowserTab")

        home_layout.addWidget(content_widget, stretch=1)

        self.addSubInterface(self.home_interface, FluentIcon.HOME, "主页")
        self.addSubInterface(self.file_browser_tab, FluentIcon.DOCUMENT, "文件浏览器")

        self.navigationInterface.addItem(
            routeKey='github',
            icon=FluentIcon.GITHUB,
            text='GitHub',
            onClick=self.open_github,
            selectable=False,
            position=NavigationItemPosition.BOTTOM
        )
        
        # 监听标签切换事件
        self.stackedWidget.currentChanged.connect(self.on_tab_changed)

        self.version_list.set_loading(True)
        self.game_selector.setEnabled(False)
        self.version_list.setEnabled(False)
        self.package_tab.setEnabled(False)

        if not self.test_mode:
            QTimer.singleShot(100, lambda: self.show_info("正在初始化", "正在加载游戏数据..."))

    def load_game_versions(self, game: str):
        if self.load_timer:
            self.load_timer.stop()
            self.load_timer.deleteLater()
            self.load_timer = None

        if self.version_worker is not None and self.version_worker.isRunning():
            debug("取消之前的加载任务")
            self.version_worker.cancel()
            self.version_worker.wait(2000)
            self.version_worker.deleteLater()
            self.version_worker = None

        self.load_timer = QTimer(self)
        self.load_timer.setSingleShot(True)
        self.load_timer.timeout.connect(lambda: self._do_load_game_versions(game))
        self.load_timer.start(300)

        self.version_list.set_loading(True)

    def _do_load_game_versions(self, game: str):
        if game in self.version_cache:
            print(f"[INFO] 从缓存加载游戏版本列表: {game}")
            self.on_versions_loaded(self.version_cache[game], game, from_cache=True)
            return

        print(f"[INFO] 开始加载游戏版本列表: {game}")
        self.version_worker = LoadVersionWorker(self.api_client, game, self)
        self.version_worker.finished.connect(lambda data: self.on_versions_loaded(data, game))
        self.version_worker.error.connect(self.on_load_error)
        self.version_worker.start()

    def on_versions_loaded(self, data: dict, game: str = None, from_cache: bool = False):
        if from_cache:
            print(f"[INFO] 从缓存加载版本列表成功，共 {len(data)} 个版本")
        else:
            print(f"[INFO] 版本列表加载成功，共 {len(data)} 个版本")

        if game and not from_cache:
            self.version_cache[game] = data

        self.version_list_data = data
        versions = list(data.keys())
        versions.reverse()
        self.version_list.set_versions(versions)
        
        if not self.is_initial_loading:
            self.version_list.set_loading(False)
            self.game_selector.setEnabled(True)
            self.version_list.setEnabled(True)
            self.package_tab.setEnabled(True)

        if versions:
            self.current_version = versions[0]
            debug(f"当前版本: {self.current_version}")
            self.version_list.select_version(self.current_version)
            # load_version_data() 会通过 version_selected 信号自动调用，无需手动调用

            if game == self.current_game and not from_cache and not self.test_mode and not self.is_initial_loading:
                self.show_success("加载完成", f"已加载 {len(versions)} 个版本")

    def on_load_error(self, error: str):
        error(f"加载失败: {error}")
        if not self.is_initial_loading:
            self.version_list.set_loading(False)
            self.game_selector.setEnabled(True)
            self.version_list.setEnabled(True)
            self.package_tab.setEnabled(True)
        if not self.test_mode:
            self.show_error("加载失败", error)

    def _show_bar(self, bar_type: str, title: str, content: str, duration: int = 3000):
        """显示 InfoBar 通知"""
        bar_func = getattr(InfoBar, bar_type)
        bar_func(
            title=title, content=content,
            orient=Qt.Orientation.Horizontal, isClosable=True,
            position=InfoBarPosition.TOP_RIGHT, duration=duration, parent=self
        )

    def show_info(self, title: str, content: str):
        self._show_bar('info', title, content)

    def show_success(self, title: str, content: str):
        self._show_bar('success', title, content)

    def show_warning(self, title: str, content: str):
        self._show_bar('warning', title, content)

    def show_error(self, title: str, content: str):
        self._show_bar('error', title, content, 5000)

    def open_github(self):
        open_link("https://github.com/orilights/hoyo-files")

    def preload_all_games(self):
        debug("开始预加载所有游戏版本列表...")
        self.preload_total = 0
        self.preload_completed = 0

        for game_key in GAME_CONFIG.keys():
            if game_key in self.version_cache:
                continue

            self.preload_total += 1
            debug(f"预加载游戏: {game_key}")
            worker = LoadVersionWorker(self.api_client, game_key, self)
            worker.finished.connect(lambda data, g=game_key: self.on_preload_finished(data, g))
            worker.error.connect(lambda err, g=game_key: self.on_preload_error(err, g))
            self.preload_workers.append(worker)
            worker.start()

        if self.preload_total > 0 and not self.test_mode:
            self.show_info("预加载中", f"正在预加载其他游戏数据... (0/{self.preload_total})")
        elif self.preload_total == 0:
            debug("所有游戏都已缓存")
            self.enable_ui_after_preload()

    def on_preload_finished(self, data: dict, game: str):
        print(f"[INFO] 预加载完成: {game}, 共 {len(data)} 个版本")
        self.version_cache[game] = data
        self.preload_completed += 1

        game_name = GAME_CONFIG.get(game, {}).get('name', game)

        if self.preload_completed >= self.preload_total:
            print("[INFO] 所有游戏版本列表预加载完成")
            self.enable_ui_after_preload()
            if not self.test_mode:
                self.show_success("初始化完成", "所有游戏数据已加载")
        else:
            if not self.test_mode:
                self.show_info(f"正在预加载: {game_name}", f"进度: {self.preload_completed}/{self.preload_total}")

    def on_preload_error(self, err: str, game: str):
        error(f"预加载 {game} 失败: {err}")
        self.preload_completed += 1

        game_name = GAME_CONFIG.get(game, {}).get('name', game)

        if self.preload_completed >= self.preload_total:
            self.enable_ui_after_preload()
            if not self.test_mode:
                self.show_warning("初始化完成", "部分游戏加载失败")
        else:
            if not self.test_mode:
                self.show_warning(f"预加载失败: {game_name}", f"进度: {self.preload_completed}/{self.preload_total}")

    def enable_ui_after_preload(self):
        """预加载完成后启用UI"""
        print("[INFO] 启用UI交互")
        self.is_initial_loading = False
        self.version_list.set_loading(False)
        self.game_selector.setEnabled(True)
        self.version_list.setEnabled(True)
        self.package_tab.setEnabled(True)

    def on_game_selected(self, game: str):
        if game != self.current_game:
            self.current_game = game
            self.load_game_versions(game)

    def on_version_selected(self, version: str):
        if version and version != self.current_version:
            self.current_version = version
            self.load_version_data()

    def load_version_data(self):
        if not self.current_version or self.current_version not in self.version_list_data:
            return

        version_data = self.version_list_data[self.current_version]
        game_config = GAME_CONFIG[self.current_game]

        self.setWindowTitle(
            f"{game_config['name']} {self.current_version} - HoyoFiles"
        )

        # 加载游戏包数据（主页需要）
        QTimer.singleShot(0, lambda: self.package_tab.load_data(version_data))

        # 只在文件浏览器标签当前激活时才加载文件树
        if self.is_file_browser_active():
            QTimer.singleShot(50, lambda: self.file_browser_tab.load_data(
                self.current_game,
                self.current_version,
                version_data,
                game_config['voice']
            ))
        else:
            # 标记需要刷新，等用户切换到文件浏览器时再加载
            self.file_browser_needs_refresh = True
            print("[INFO] 文件浏览器未激活，延迟加载文件树")
    
    def is_file_browser_active(self):
        """检查文件浏览器标签是否当前激活"""
        current_widget = self.stackedWidget.currentWidget()
        return current_widget == self.file_browser_tab
    
    def on_tab_changed(self, index: int):
        """标签切换事件处理"""
        current_widget = self.stackedWidget.widget(index)
        
        # 检查是否切换到文件浏览器
        if current_widget == self.file_browser_tab:
            if not self.file_browser_visited:
                print("[INFO] 首次访问文件浏览器")
                self.file_browser_visited = True
            
            # 如果有待加载的数据，立即加载
            if self.file_browser_needs_refresh and self.current_version:
                print(f"[INFO] 加载文件树: {GAME_CONFIG[self.current_game]['name']} {self.current_version}")
                self.file_browser_needs_refresh = False
                version_data = self.version_list_data[self.current_version]
                game_config = GAME_CONFIG[self.current_game]
                
                self.file_browser_tab.load_data(
                    self.current_game,
                    self.current_version,
                    version_data,
                    game_config['voice']
                )

def main():
    try:
        print("=" * 60)
        print("HoyoFiles GUI - 米哈游游戏文件浏览器")
        print("=" * 60)

        app = QApplication(sys.argv)
        app.setApplicationName("HoyoFiles")
        app.setOrganizationName("HoyoFiles")

        demo_mode = os.getenv('HOYO_DEMO_MODE', '').lower() == 'true'
        demo_duration = int(os.getenv('HOYO_DEMO_DURATION', '5000'))

        debug("正在启动主窗口...")
        window = MainWindow()
        window.show()
        debug("主窗口已显示")

        if demo_mode:
            info(f"演示模式：将在 {demo_duration}ms 后自动关闭")
            def cleanup_and_quit():
                debug("演示模式结束，正在关闭...")
                if hasattr(window, 'version_worker') and window.version_worker:
                    window.version_worker.cancel()
                    window.version_worker.wait(1000)
                for worker in window.preload_workers:
                    if worker.isRunning():
                        worker.cancel()
                        worker.wait(1000)
                window.close()
                app.quit()

            QTimer.singleShot(demo_duration, cleanup_and_quit)

        return app.exec()
    except Exception as e:
        error("程序崩溃:")
        error(traceback.format_exc())
        return 1

if __name__ == "__main__":
    sys.exit(main())