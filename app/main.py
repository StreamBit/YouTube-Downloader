from __future__ import annotations

import json
from html import escape
import os
import shutil
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QProcess, QSize, Qt, QTimer, QUrl, QRectF
from PySide6.QtGui import QDesktopServices, QFont, QIcon, QPainter, QPixmap, QColor
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
    QStyle, QToolButton, QToolTip, QVBoxLayout, QWidget)

from core import AUDIO_FORMATS, VIDEO_FORMATS, RESOLUTIONS, Settings, normalize_url, parse_bulk, qualities

ROOT = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[1]


def app_icon():
    image = QPixmap(64, 64)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor('#ff6b57'))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(2, 2, 60, 60, 17, 17)
    p.setPen(QColor('#ffffff'))
    p.setFont(QFont('Segoe UI', 30, QFont.Weight.Bold))
    p.drawText(image.rect(), Qt.AlignmentFlag.AlignCenter, '↓')
    p.end()
    return QIcon(image)


class Info(QToolButton):
    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.setText('i')
        self.setObjectName('info')
        self.setFixedSize(22, 22)
        self.setToolTip(f'<qt><table width="280"><tr><td>{escape(text)}</td></tr></table></qt>')
        self.setAccessibleName('Information: ' + text)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.clicked.connect(lambda: QToolTip.showText(self.mapToGlobal(self.rect().bottomLeft()), self.toolTip(), self))

    def focusInEvent(self, event):
        super().focusInEvent(event)
        QToolTip.showText(self.mapToGlobal(self.rect().bottomLeft()), self.toolTip(), self)


class Toggle(QCheckBox):
    def sizeHint(self):
        return QSize(self.fontMetrics().horizontalAdvance(self.text()) + 49, 28)

    def hitButton(self, point):
        return self.rect().contains(point)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor('#ff745e' if self.isChecked() else '#526074'))
        painter.drawRoundedRect(QRectF(0, (self.height() - 20) / 2, 34, 20), 10, 10)
        painter.setBrush(QColor('#ffffff'))
        painter.drawEllipse(QRectF(17 if self.isChecked() else 3, (self.height() - 14) / 2, 14, 14))
        painter.setPen(self.palette().windowText().color())
        painter.drawText(self.rect().adjusted(43, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, self.text())
        if self.hasFocus():
            painter.setPen(QColor('#ff806a'))
            painter.drawLine(43, self.height() - 2, self.width(), self.height() - 2)
        painter.end()


def label(text, name=''):
    item = QLabel(text)
    if name:
        item.setObjectName(name)
    return item


def heading(text, tip=None):
    row = QHBoxLayout()
    row.setSpacing(8)
    row.addWidget(label(text, 'fieldLabel'))
    if tip:
        row.addWidget(Info(tip))
    row.addStretch()
    return row


class BulkDialog(QDialog):
    def __init__(self, urls, parent):
        super().__init__(parent)
        self.setWindowTitle('Bulk URLs')
        self.resize(630, 465)
        self.urls = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)
        layout.addLayout(heading('Add your links', 'Paste one YouTube video or playlist URL per line. Duplicate links are removed. All links use the settings in the main window.'))
        layout.addWidget(label('One URL per line. This list is cleared when you close the app.', 'muted'))
        self.editor = QPlainTextEdit('\n'.join(urls))
        self.editor.setPlaceholderText('https://www.youtube.com/watch?v=…\nhttps://youtu.be/…')
        self.editor.setAccessibleName('Bulk URLs, one per line')
        layout.addWidget(self.editor, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        self.save_button.setText('Save list')
        self.save_button.setObjectName('primary')
        self.clear_button = QPushButton('Clear list')
        self.clear_button.setAutoDefault(False)
        self.clear_button.clicked.connect(lambda: (self.editor.clear(), self.editor.setFocus()))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(self.clear_button)
        actions.addWidget(buttons)
        layout.addLayout(actions)
        self.editor.textChanged.connect(self.validate)
        self.validate()

    def validate(self):
        self.clear_button.setEnabled(bool(self.editor.toPlainText()))
        self.urls, errors, duplicates = parse_bulk(self.editor.toPlainText())
        message = f'{len(self.urls)} valid URLs · {duplicates} duplicates removed'
        if errors:
            message += '\n' + '\n'.join(errors[:3])
            if len(errors) > 3:
                message += f'\n…and {len(errors) - 3} more invalid lines.'
        self.status.setText(message)
        self.status.setObjectName('error' if errors else 'muted')
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self.save_button.setEnabled(not errors)


class Worker(QProcess):
    def __init__(self, request, callback, finished, parent):
        super().__init__(parent)
        self.buffer = b''
        self.callback = callback
        self.error_text = ''
        self.readyReadStandardOutput.connect(self.read_events)
        self.readyReadStandardError.connect(self.read_errors)
        self.finished.connect(lambda code, status: (self.read_events(), finished(code)))
        self.errorOccurred.connect(self.failed)
        if getattr(sys, 'frozen', False):
            self.setProgram(str(ROOT / 'engine' / 'engine.exe'))
        else:
            self.setProgram(sys.executable)
            self.setArguments([str(ROOT / 'app' / 'backend.py')])
        self.started.connect(lambda: (self.write((json.dumps(request) + '\n').encode()), self.closeWriteChannel()))

    def failed(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.callback({'event': 'error', 'message': 'The download engine could not start. Keep the entire portable folder together.'})
            self.finished.emit(1, QProcess.ExitStatus.CrashExit)

    def read_errors(self):
        self.error_text = (self.error_text + bytes(self.readAllStandardError()).decode('utf-8', errors='replace'))[-4000:]

    def read_events(self):
        self.buffer += bytes(self.readAllStandardOutput())
        while b'\n' in self.buffer:
            line, self.buffer = self.buffer.split(b'\n', 1)
            try:
                self.callback(json.loads(line))
            except (ValueError, UnicodeDecodeError):
                continue


class MainWindow(QMainWindow):
    def __init__(self, settings_path=None):
        super().__init__()
        self.setWindowTitle('YouTube Downloader')
        self.setWindowIcon(app_icon())
        self._initial_sizing_done = False
        self.settings_path = settings_path or ROOT / 'settings.json'
        self.settings = Settings.load(self.settings_path)
        self.bulk_urls = []
        self.failures = []
        self.retry_request = None
        self.worker = None
        self.preview_worker = None
        self.workers = set()
        self.generation = 0
        self.temp_folder = None
        self.canceled = False
        self.finished_normally = False
        self.closing = False
        self.available_resolutions = []
        self.thumbnail = None
        self.thumbnail_reply = None
        self.network = QNetworkAccessManager(self)
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(650)
        self.preview_timer.timeout.connect(self.load_preview)
        self.build_ui()
        self.restore_settings()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._initial_sizing_done:
            self._initial_sizing_done = True
            QTimer.singleShot(0, self.fit_initial_window)

    def fit_initial_window(self, available=None):
        available = available if available is not None else self.screen().availableGeometry()
        bounds = available.adjusted(12, 12, -12, -12)
        frame_width = self.frameGeometry().width() - self.width()
        frame_height = self.frameGeometry().height() - self.height()
        max_width = max(1, bounds.width() - frame_width)
        max_height = max(1, bounds.height() - frame_height)
        self.setMinimumSize(min(820, max_width), min(600, max_height))
        content = self.centralWidget().widget()
        content.ensurePolished()
        layout = content.layout()
        layout.activate()
        width = min(max(1020, layout.minimumSize().width()), max_width)
        height = max(layout.minimumSize().height(), layout.totalHeightForWidth(width)) + 24
        self.resize(width, min(height, max_height))
        frame = self.frameGeometry()
        frame.moveCenter(bounds.center())
        self.move(frame.topLeft())

    def build_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.setCentralWidget(scroll)
        container = QWidget()
        scroll.setWidget(container)
        root = QVBoxLayout(container)
        root.setContentsMargins(32, 24, 32, 24)
        root.setSpacing(18)
        top = QHBoxLayout()
        identity = QHBoxLayout()
        mark = QLabel()
        mark.setPixmap(app_icon().pixmap(42, 42))
        identity.addWidget(mark)
        titles = QVBoxLayout()
        titles.setSpacing(1)
        titles.addWidget(label('YouTube Downloader', 'appTitle'))
        titles.addWidget(label('Video & audio downloads', 'muted'))
        identity.addLayout(titles)
        top.addLayout(identity)
        top.addStretch()
        self.dark = Toggle('Dark mode')
        self.dark.setAccessibleName('Dark mode')
        top.addWidget(self.dark)
        root.addLayout(top)

        urlbox = QVBoxLayout()
        urlbox.setSpacing(7)
        urlbox.addLayout(heading('VIDEO URL'))
        self.url = QLineEdit()
        self.url.setPlaceholderText('Paste a YouTube link to get started…')
        self.url.setAccessibleName('YouTube URL')
        self.url.setMinimumHeight(48)
        self.url.setClearButtonEnabled(True)
        urlbox.addWidget(self.url)
        self.url_status = label('Video details will appear automatically.', 'muted')
        self.url_status.setWordWrap(True)
        urlbox.addWidget(self.url_status)
        root.addLayout(urlbox)

        middle = QHBoxLayout()
        middle.setSpacing(24)
        left = QVBoxLayout()
        left.setSpacing(16)
        self.preview = QLabel('▶\n\nYour video preview')
        self.preview.setObjectName('preview')
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(300, 196)
        self.preview.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        left.addWidget(self.preview, 1)
        bulkrow = QHBoxLayout()
        self.bulk = QPushButton('+  Add bulk URLs')
        self.bulk.setMinimumHeight(44)
        self.bulk.clicked.connect(self.edit_bulk)
        bulkrow.addWidget(self.bulk, 1)
        bulkrow.addWidget(Info('Add multiple URLs, one per line. Bulk Run downloads this saved list using the current settings. Links are kept only for this session.'))
        left.addLayout(bulkrow)
        folderbox = QVBoxLayout()
        folderbox.setSpacing(7)
        folderbox.addLayout(heading('OUTPUT FOLDER'))
        folderrow = QHBoxLayout()
        folderrow.setSpacing(6)
        self.folder = QLineEdit()
        self.folder.setPlaceholderText('Choose where to save…')
        self.folder.setAccessibleName('Output folder')
        self.folder.setMinimumHeight(42)
        self.browse = QPushButton()
        self.browse.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
        self.browse.setAccessibleName('Browse for output folder')
        self.browse.setToolTip('Choose an output folder')
        self.browse.setFixedSize(44, 42)
        self.browse.clicked.connect(self.choose_folder)
        folderrow.addWidget(self.folder, 1)
        folderrow.addWidget(self.browse)
        folderbox.addLayout(folderrow)
        left.addLayout(folderbox)
        middle.addLayout(left, 1)

        right = QVBoxLayout()
        right.setSpacing(13)
        self.video_title = label('Ready when you are', 'videoTitle')
        self.video_title.setWordWrap(True)
        self.video_title.setTextFormat(Qt.TextFormat.PlainText)
        right.addWidget(self.video_title)
        self.video_meta = label('Paste a link to see the title, channel, and duration.', 'muted')
        self.video_meta.setWordWrap(True)
        self.video_meta.setTextFormat(Qt.TextFormat.PlainText)
        right.addWidget(self.video_meta)
        right.addSpacing(3)
        right.addLayout(heading('DOWNLOAD AS', 'Video includes picture and high-quality audio. Audio saves only the soundtrack. Select a mode to choose its available file formats.'))
        modes = QHBoxLayout()
        modes.setSpacing(8)
        self.mode_group = QButtonGroup(self)
        self.video = QPushButton('▸  Video')
        self.audio = QPushButton('♫  Audio')
        for button in (self.video, self.audio):
            button.setCheckable(True)
            button.setMinimumHeight(43)
            self.mode_group.addButton(button)
            modes.addWidget(button)
        self.video.setAccessibleName('Video mode')
        self.audio.setAccessibleName('Audio mode')
        right.addLayout(modes)
        formatrow = QHBoxLayout()
        fbox, qbox = QVBoxLayout(), QVBoxLayout()
        fbox.addLayout(heading('FILE TYPE', 'Choose the output format. MP4 is widely compatible. WAV is the default for audio. WAV and FLAC cannot restore detail lost in the original audio.'))
        qbox.addLayout(heading('QUALITY', 'For video, choose a maximum resolution; lower-resolution sources are never upscaled. Audio choices depend on the file type. Source matched keeps the source sample rate with 16-bit PCM output.'))
        self.format = QComboBox()
        self.format.setAccessibleName('File type')
        self.quality = QComboBox()
        self.quality.setAccessibleName('Quality')
        for combo in (self.format, self.quality):
            combo.setMinimumHeight(43)
            combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        fbox.addWidget(self.format)
        qbox.addWidget(self.quality)
        formatrow.addLayout(fbox, 2)
        formatrow.addLayout(qbox, 3)
        right.addLayout(formatrow)
        self.quality_note = label('Choose video or audio to see output options.', 'muted')
        self.quality_note.setWordWrap(True)
        right.addWidget(self.quality_note)
        playrow = QHBoxLayout()
        self.playlist = Toggle('Playlist mode')
        playrow.addWidget(self.playlist)
        playrow.addWidget(Info('Off: download only the video in the URL. On: download the entire playlist when the URL includes one. Applies to both Run and Bulk Run. Playlist-only URLs require this setting.'))
        playrow.addStretch()
        right.addLayout(playrow)
        right.addWidget(label('Use the whole playlist when a link includes one.', 'muted'))
        right.addStretch()
        middle.addLayout(right, 1)
        root.addLayout(middle, 1)

        panel = QFrame()
        panel.setObjectName('progressPanel')
        progress = QVBoxLayout(panel)
        progress.setContentsMargins(18, 16, 18, 16)
        progress.setSpacing(8)
        currentrow = QHBoxLayout()
        self.current_text = label('CURRENT FILE', 'fieldLabel')
        self.stage = label('Waiting to start', 'muted')
        self.stage.setAlignment(Qt.AlignmentFlag.AlignRight)
        currentrow.addWidget(self.current_text)
        currentrow.addWidget(self.stage, 1)
        progress.addLayout(currentrow)
        self.current_bar = QProgressBar()
        self.current_bar.setObjectName('currentBar')
        self.current_bar.setRange(0, 1000)
        self.current_bar.setValue(0)
        self.current_bar.setTextVisible(False)
        self.current_bar.setFixedHeight(7)
        self.current_bar.setAccessibleName('Current file progress')
        progress.addWidget(self.current_bar)
        self.current_title = label('No downloads in progress', 'muted')
        self.current_title.setTextFormat(Qt.TextFormat.PlainText)
        self.current_title.setWordWrap(True)
        progress.addWidget(self.current_title)
        progress.addSpacing(6)
        overallrow = QHBoxLayout()
        overallrow.addWidget(label('OVERALL PROGRESS', 'fieldLabel'))
        self.overall_text = label('0%', 'fieldLabel')
        overallrow.addWidget(self.overall_text, 1, Qt.AlignmentFlag.AlignRight)
        progress.addLayout(overallrow)
        self.overall_bar = QProgressBar()
        self.overall_bar.setRange(0, 1000)
        self.overall_bar.setValue(0)
        self.overall_bar.setTextVisible(False)
        self.overall_bar.setFixedHeight(17)
        self.overall_bar.setAccessibleName('Overall run progress')
        progress.addWidget(self.overall_bar)
        self.summary = label('Ready for your next download.', 'muted')
        self.summary.setWordWrap(True)
        progress.addWidget(self.summary)
        root.addWidget(panel)

        self.validation = label('', 'error')
        self.validation.setWordWrap(True)
        root.addWidget(self.validation)
        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.open_folder = QPushButton('Open output folder')
        self.open_folder.clicked.connect(self.open_output)
        self.cancel = QPushButton('Cancel')
        self.cancel.setEnabled(False)
        self.cancel.clicked.connect(self.cancel_run)
        self.retry = QPushButton('Retry failed')
        self.retry.clicked.connect(self.retry_failed)
        self.retry.hide()
        self.bulk_run = QPushButton('Bulk Run')
        self.bulk_run.clicked.connect(lambda: self.start_run(True))
        self.run = QPushButton('↓  Run')
        self.run.setObjectName('primary')
        self.run.setMinimumWidth(120)
        self.run.clicked.connect(lambda: self.start_run(False))
        for button in (self.open_folder, self.cancel, self.retry, self.bulk_run, self.run):
            button.setMinimumHeight(43)
        actions.addWidget(self.open_folder)
        actions.addWidget(self.cancel)
        actions.addWidget(self.retry)
        actions.addStretch()
        actions.addWidget(self.bulk_run)
        actions.addWidget(Info('Bulk Run processes the URLs saved in the bulk popup. Run processes the top URL. Both include conversion and finalization. Cancel keeps completed files and removes incomplete temporary files.'))
        actions.addWidget(self.run)
        actions.addWidget(Info('Download the top URL with these settings. Playlist mode controls whether a playlist link expands to all its videos.'))
        root.addLayout(actions)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(110)
        self.details.setAccessibleName('Run details')
        self.details.hide()
        root.addWidget(self.details)
        footer = QHBoxLayout()
        footer.addWidget(label('PORTABLE  /  v1.0', 'muted'))
        footer.addStretch()
        self.show_details = QToolButton()
        self.show_details.setText('Show run details')
        self.show_details.clicked.connect(self.toggle_details)
        footer.addWidget(self.show_details)
        root.addLayout(footer)
        self.locked_controls = [self.url, self.bulk, self.folder, self.browse, self.video, self.audio, self.format, self.quality, self.playlist]

    def restore_settings(self):
        self.dark.setChecked(self.settings.dark)
        self.folder.setText(self.settings.folder)
        self.playlist.setChecked(self.settings.playlist)
        if self.settings.mode == 'Video':
            self.video.setChecked(True)
        elif self.settings.mode == 'Audio':
            self.audio.setChecked(True)
        self.update_formats(self.settings.format, self.settings.quality)
        self.apply_theme()
        self.dark.toggled.connect(lambda: (self.apply_theme(), self.save_settings()))
        self.mode_group.buttonClicked.connect(lambda: (self.update_formats(), self.save_settings()))
        self.format.currentTextChanged.connect(lambda: (self.update_qualities(), self.save_settings()))
        self.quality.currentTextChanged.connect(self.save_settings)
        self.folder.textChanged.connect(lambda: (self.validate(), self.save_settings()))
        self.playlist.toggled.connect(self.save_settings)
        self.url.textChanged.connect(self.url_changed)
        self.validate()

    def mode(self):
        return 'Audio' if self.audio.isChecked() else 'Video' if self.video.isChecked() else ''

    def update_formats(self, preferred='', quality=''):
        self.format.blockSignals(True)
        self.format.clear()
        formats = AUDIO_FORMATS if self.mode() == 'Audio' else VIDEO_FORMATS if self.mode() == 'Video' else ['Select a mode']
        self.format.addItems(formats)
        if preferred in formats:
            self.format.setCurrentText(preferred)
        self.format.blockSignals(False)
        self.update_qualities(quality)
        self.validate()

    def update_qualities(self, preferred=''):
        self.quality.blockSignals(True)
        self.quality.clear()
        self.quality.addItems(qualities(self.mode(), self.format.currentText()) if self.mode() else ['—'])
        if self.quality.findText(preferred) >= 0:
            self.quality.setCurrentText(preferred)
        self.quality.blockSignals(False)
        if not self.mode():
            self.quality_note.setText('Choose video or audio to see output options.')
        elif self.mode() == 'Video':
            self.quality_note.setText('Best available source audio is included. Resolution is a maximum.')
        elif self.format.currentText() in ('WAV', 'FLAC'):
            self.quality_note.setText('Source matched: original sample rate, 16-bit output. Higher settings do not add source detail.')
        else:
            self.quality_note.setText('Higher bitrates create larger files. Quality is limited by the source.')

    def save_settings(self, *_):
        settings = Settings(self.dark.isChecked(), self.mode(), self.format.currentText() if self.mode() else '',
                            self.quality.currentText() if self.mode() else '', self.folder.text().strip(), self.playlist.isChecked())
        try:
            settings.save(self.settings_path)
        except OSError:
            self.validation.setText('Preferences could not be saved. Move the portable app to a writable folder.')

    def set_missing(self, widget, value):
        widget.setProperty('missing', value)
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def validate(self):
        folder = Path(self.folder.text().strip())
        folder_ok = bool(self.folder.text().strip()) and folder.is_dir()
        for button in (self.video, self.audio):
            self.set_missing(button, not self.mode())
        self.set_missing(self.format, not self.mode())
        self.set_missing(self.folder, not folder_ok)
        self.open_folder.setEnabled(folder_ok)
        missing = []
        if not self.mode():
            missing.append('Choose Video or Audio')
        if not folder_ok:
            missing.append('choose an existing output folder')
        self.validation.setText(' · '.join(missing) + ('.' if missing else ''))
        return not missing

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, 'Choose output folder', self.folder.text() or str(Path.home()))
        if folder:
            self.folder.setText(folder)

    def open_output(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.folder.text().strip()))

    def edit_bulk(self):
        dialog = BulkDialog(self.bulk_urls, self)
        if dialog.exec():
            self.bulk_urls = dialog.urls
            self.bulk.setText(f'+  Bulk URLs ({len(self.bulk_urls)})' if self.bulk_urls else '+  Add bulk URLs')

    def url_changed(self):
        self.generation += 1
        self.preview_timer.stop()
        if self.preview_worker:
            self.preview_worker.kill()
            self.preview_worker = None
        if self.thumbnail_reply:
            self.thumbnail_reply.abort()
            self.thumbnail_reply = None
        self.thumbnail = None
        self.preview.setPixmap(QPixmap())
        self.preview.setText('▶\n\nYour video preview')
        self.available_resolutions = []
        self.video_title.setText('Ready when you are')
        self.video_meta.setText('Paste a link to see the title, channel, and duration.')
        if not self.url.text().strip():
            self.url_status.setText('Video details will appear automatically.')
            return
        try:
            normalize_url(self.url.text())
        except ValueError as e:
            self.url_status.setText(str(e))
            return
        self.url_status.setText('Loading video details…')
        self.preview_timer.start()

    def load_preview(self):
        generation = self.generation
        worker = Worker({'action': 'metadata', 'url': self.url.text().strip()},
                        lambda event: self.preview_event(event, generation), lambda _: self.forget_worker(worker), self)
        self.preview_worker = worker
        self.workers.add(worker)
        worker.start()

    def forget_worker(self, worker):
        self.workers.discard(worker)
        if self.preview_worker is worker:
            self.preview_worker = None
        worker.deleteLater()

    def preview_event(self, event, generation):
        if generation != self.generation:
            return
        if event['event'] == 'metadata':
            self.video_title.setText(event['title'])
            duration = event.get('duration')
            time = f'{int(duration) // 60}:{int(duration) % 60:02d}' if duration else 'Playlist' if event.get('playlist') else 'Duration unavailable'
            self.video_meta.setText(f"{event['channel']}  ·  {time}")
            self.available_resolutions = event.get('resolutions', [])
            available = ', '.join(f'{height}p' for height in self.available_resolutions)
            self.url_status.setText('Preview ready' + (f' · Available: {available}' if available else ''))
            if event.get('thumbnail'):
                request = QNetworkRequest(QUrl(event['thumbnail']))
                request.setTransferTimeout(15000)
                reply = self.network.get(request)
                self.thumbnail_reply = reply
                reply.finished.connect(lambda: self.thumbnail_loaded(reply, generation))
        elif event['event'] == 'error':
            self.url_status.setText('Could not load preview: ' + event['message'])

    def thumbnail_loaded(self, reply, generation):
        if generation == self.generation and reply.error() == QNetworkReply.NetworkError.NoError:
            pixmap = QPixmap()
            if pixmap.loadFromData(reply.readAll()):
                self.thumbnail = pixmap
                self.draw_thumbnail()
        if self.thumbnail_reply is reply:
            self.thumbnail_reply = None
        reply.deleteLater()

    def draw_thumbnail(self):
        if self.thumbnail:
            self.preview.setPixmap(self.thumbnail.scaled(self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'preview'):
            self.draw_thumbnail()

    def start_run(self, bulk=False, retry_items=None):
        if self.worker or not self.validate():
            return
        urls = self.bulk_urls if bulk else [self.url.text().strip()]
        if retry_items:
            request = dict(self.retry_request)
            request['retry_items'] = retry_items
        else:
            if not urls or not any(urls):
                self.validation.setText('Add URLs in the bulk popup first.' if bulk else 'Paste a YouTube URL first.')
                return
            try:
                urls = [normalize_url(url, self.playlist.isChecked()) for url in urls]
            except ValueError as e:
                self.validation.setText(str(e))
                return
            request = {'action': 'run', 'urls': urls, 'folder': self.folder.text().strip(), 'mode': self.mode(),
                       'format': self.format.currentText(), 'quality': self.quality.currentText(), 'playlist': self.playlist.isChecked()}
        try:
            self.temp_folder = Path(tempfile.mkdtemp(prefix='.ytd-work-', dir=request['folder']))
        except OSError as e:
            self.validation.setText(f'The output folder is not writable: {e}')
            return
        request['temp'] = str(self.temp_folder)
        self.retry_request = request.copy()
        self.failures = []
        self.canceled = False
        self.finished_normally = False
        self.details.clear()
        self.retry.hide()
        self.summary.setText('Preparing the run…')
        self.stage.setText('Preparing')
        self.current_bar.setRange(0, 0)
        self.overall_bar.setRange(0, 0)
        self.overall_text.setText('Preparing…')
        self.validation.clear()
        self.completed_counts = {'success': 0, 'skipped': 0, 'failed': 0}
        self.set_busy(True)
        self.worker = Worker(request, self.run_event, self.run_finished, self)
        self.worker.start()

    def set_busy(self, busy):
        for widget in self.locked_controls:
            widget.setEnabled(not busy)
        self.run.setEnabled(not busy)
        self.bulk_run.setEnabled(not busy)
        self.cancel.setEnabled(busy)
        self.retry.setEnabled(not busy)

    def run_event(self, event):
        if self.canceled:
            return
        kind = event['event']
        if kind == 'preparing':
            self.summary.setText(event['message'])
        elif kind == 'queue':
            self.overall_bar.setRange(0, 1000)
            self.overall_bar.setValue(0)
            self.summary.setText(f"0 of {event['total']} files completed · Overall progress is estimated.")
        elif kind == 'current':
            self.current_title.setText(event['title'])
            self.current_text.setText(f"CURRENT FILE  ·  {event['index'] + 1} / {event['total']}")
            self.current_bar.setRange(0, 0)
            self.stage.setText('Preparing')
        elif kind == 'progress':
            fraction = event['fraction']
            stage = event['stage']
            self.stage.setText(stage)
            if event.get('indeterminate') or stage in ('Preparing', 'Preparing conversion', 'Combining video and audio', 'Finalizing'):
                self.current_bar.setRange(0, 0)
            else:
                self.current_bar.setRange(0, 1000)
                local = fraction / .78 if stage == 'Downloading' else max(0, (fraction - .82) / .16)
                self.current_bar.setValue(min(1000, int(local * 1000)))
            self.set_overall((event['index'] + fraction) / event['total'])
        elif kind == 'item_done':
            self.completed_counts[event['status']] += 1
            self.current_bar.setRange(0, 1000)
            self.current_bar.setValue(1000)
            self.set_overall((event['index'] + 1) / event['total'], final=False)
            self.summary.setText(f"{event['index'] + 1} of {event['total']} files processed · {self.counts_text(self.completed_counts)}")
            self.details.appendPlainText(event['status'].upper() + ': ' + (event.get('path') or event.get('url', '') + '\n' + event.get('message', '')))
        elif kind == 'done':
            self.finished_normally = True
            self.failures = event['failures']
            self.set_overall(1, final=True)
            self.stage.setText('Finished' if not event['failed'] else 'Finished with errors')
            self.summary.setText(self.counts_text(event))
        elif kind in ('warning', 'error'):
            self.details.appendPlainText(event['message'])
            if kind == 'error':
                self.validation.setText(event['message'])
                self.summary.setText('The run could not finish. See run details.')

    @staticmethod
    def counts_text(counts):
        return f"{counts['success']} saved · {counts['skipped']} skipped · {counts['failed']} failed"

    def set_overall(self, fraction, final=False):
        value = 1000 if final else min(999, int(fraction * 1000))
        self.overall_bar.setRange(0, 1000)
        self.overall_bar.setValue(value)
        self.overall_text.setText(f'{value / 10:.0f}%' if final or value < 995 else '99%')

    def cancel_run(self):
        if self.worker:
            self.canceled = True
            self.cancel.setEnabled(False)
            self.stage.setText('Canceling…')
            self.worker.kill()

    def run_finished(self, code):
        worker = self.worker
        self.worker = None
        if worker:
            worker.deleteLater()
        self.cleanup_temp()
        self.set_busy(False)
        self.current_bar.setRange(0, 1000)
        if self.overall_bar.maximum() == 0:
            self.overall_bar.setRange(0, 1000)
            self.overall_bar.setValue(0)
            self.overall_text.setText('0%')
        if self.canceled:
            self.stage.setText('Canceled')
            self.summary.setText('Canceled · Completed files were kept. ' + self.counts_text(self.completed_counts))
        elif not self.finished_normally:
            self.stage.setText('Stopped')
            if not self.validation.text():
                self.validation.setText('The download engine stopped unexpectedly. See run details.')
        self.retry.setVisible(bool(self.failures))
        if self.closing:
            self.close()

    def cleanup_temp(self, attempt=0):
        path = self.temp_folder
        if not path:
            return
        self.temp_folder = None
        self.remove_temp(path, attempt)

    def remove_temp(self, path, attempt=0):
        try:
            shutil.rmtree(path)
        except FileNotFoundError:
            pass
        except OSError:
            if attempt < 5:
                QTimer.singleShot(300, lambda: self.remove_temp(path, attempt + 1))
            else:
                self.details.appendPlainText(f'Could not remove temporary files in {path}. They can be deleted after the app closes.')

    def retry_failed(self):
        if self.failures:
            items = [dict(item) for item in self.failures]
            for item in items:
                item.pop('error', None)
            self.start_run(retry_items=items)

    def toggle_details(self):
        visible = not self.details.isVisible()
        self.details.setVisible(visible)
        self.show_details.setText('Hide run details' if visible else 'Show run details')

    def closeEvent(self, event):
        self.preview_timer.stop()
        for worker in list(self.workers):
            worker.kill()
            worker.waitForFinished(2000)
        if self.worker:
            self.closing = True
            self.cancel_run()
            event.ignore()
            return
        self.save_settings()
        self.cleanup_temp()
        event.accept()

    def apply_theme(self):
        dark = self.dark.isChecked()
        bg, panel, field = ('#10141d', '#181e2a', '#1d2533') if dark else ('#f4f5f8', '#ffffff', '#ffffff')
        text, muted, border = ('#f2f4f8', '#9ba9bc', '#303b4e') if dark else ('#1c2738', '#58677a', '#d5dce6')
        redbg = '#322027' if dark else '#fff0ee'
        self.setStyleSheet(f'''
            QWidget {{ color: {text}; font-family: 'Segoe UI'; font-size: 13px; }}
            QMainWindow, QDialog, QScrollArea, QScrollArea > QWidget > QWidget {{ background: {bg}; }}
            QLabel {{ background: transparent; }}
            QLabel#appTitle {{ font-size: 22px; font-weight: 700; }}
            QLabel#videoTitle {{ font-size: 22px; font-weight: 600; }}
            QLabel#muted {{ color: {muted}; font-size: 12px; }}
            QLabel#fieldLabel {{ color: {muted}; font-size: 11px; font-weight: 700; letter-spacing: 1px; }}
            QLabel#error {{ color: {'#ff9a8d' if dark else '#b63025'}; font-size: 12px; }}
            QLabel#preview {{ background: {panel}; border: 1px solid {border}; border-radius: 12px; color: {muted}; font-size: 17px; }}
            QFrame#progressPanel {{ background: {panel}; border: 1px solid {border}; border-radius: 12px; }}
            QLineEdit, QComboBox, QPlainTextEdit {{ background: {field}; border: 1px solid {border}; border-radius: 7px; padding: 9px 11px; selection-background-color: #bb503f; }}
            QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus {{ border-color: #ff806a; }}
            QComboBox::drop-down {{ border: none; width: 25px; }}
            QComboBox QAbstractItemView {{ background: {field}; color: {text}; selection-background-color: #a74336; padding: 5px; }}
            QPushButton {{ background: {field}; border: 1px solid {border}; border-radius: 7px; padding: 9px 14px; font-weight: 600; }}
            QPushButton:hover {{ border-color: #ff806a; }}
            QPushButton:focus {{ border: 2px solid #ff806a; }}
            QPushButton:checked {{ background: {'#422a29' if dark else '#ffe1db'}; border-color: #ff806a; color: {'#ffb19f' if dark else '#952e20'}; }}
            QPushButton#primary {{ background: #ff745e; border-color: #ff745e; color: #1b1413; }}
            QPushButton#primary:hover {{ background: #ff917f; }}
            QPushButton:disabled, QLineEdit:disabled, QComboBox:disabled {{ color: {muted}; background: {panel}; }}
            QPushButton#primary:disabled {{ background: {panel}; border-color: {border}; color: {muted}; }}
            *[missing="true"] {{ background: {redbg}; border: 1px solid #b95850; }}
            QToolButton {{ color: {muted}; background: transparent; border: none; padding: 4px; }}
            QToolButton#info {{ border: 1px solid {border}; border-radius: 11px; padding: 0; font-size: 12px; font-weight: 600; }}
            QToolButton:hover, QToolButton:focus {{ color: #ff806a; border-color: #ff806a; }}
            QCheckBox {{ spacing: 9px; }}
            QCheckBox::indicator {{ width: 30px; height: 17px; background: {field}; border: 1px solid {border}; border-radius: 8px; }}
            QCheckBox::indicator:checked {{ background: #ff745e; border-color: #ff745e; image: none; }}
            QCheckBox:focus {{ color: #ff806a; }}
            QProgressBar {{ background: {border}; border: none; border-radius: 6px; }}
            QProgressBar::chunk {{ background: #ff806a; border-radius: 5px; }}
            QProgressBar#currentBar::chunk {{ background: #70c9ba; border-radius: 3px; }}
            QToolTip {{ background: {panel}; color: {text}; border: 1px solid {border}; padding: 9px; }}
            QScrollBar:vertical {{ background: {bg}; width: 10px; }}
            QScrollBar::handle:vertical {{ background: {border}; border-radius: 5px; min-height: 24px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        ''')


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setApplicationName('YouTube Downloader')
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
