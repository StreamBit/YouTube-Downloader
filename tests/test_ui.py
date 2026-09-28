import json
from pathlib import Path

import pytest
from PySide6.QtCore import Qt, QBuffer, QIODevice, QRect
from PySide6.QtTest import QTest
from PySide6.QtGui import QFontDatabase, QPixmap
from PySide6.QtNetwork import QNetworkReply
from PySide6.QtWidgets import QApplication

from main import BulkDialog, MainWindow


@pytest.fixture(scope='module')
def app():
    app = QApplication.instance() or QApplication([])
    for font in ('segoeui.ttf', 'segoeuib.ttf', 'seguisym.ttf'):
        QFontDatabase.addApplicationFont('C:/Windows/Fonts/' + font)
    return app


def test_first_launch_defaults_and_persistence(app, tmp_path):
    window = MainWindow(tmp_path / 'settings.json')
    assert window.dark.isChecked()
    assert not window.mode()
    assert window.folder.property('missing')
    window.audio.click()
    assert window.format.currentText() == 'WAV'
    assert window.quality.currentText() == 'Source matched'
    window.folder.setText(str(tmp_path))
    assert window.validate()
    window.url.setText('https://youtu.be/BaW_jenozKc')
    window.bulk_urls = ['https://youtu.be/BaW_jenozKc']
    window.close()
    saved = json.loads((tmp_path / 'settings.json').read_text())
    assert 'url' not in saved and 'bulk_urls' not in saved
    restored = MainWindow(tmp_path / 'settings.json')
    assert restored.mode() == 'Audio'
    assert not restored.url.text() and not restored.bulk_urls
    restored.close()


def test_mode_change_replaces_incompatible_formats(app, tmp_path):
    window = MainWindow(tmp_path / 'settings.json')
    window.audio.click()
    window.format.setCurrentText('MP3')
    assert 'kbps' in window.quality.currentText()
    window.video.click()
    assert window.format.currentText() == 'MP4'
    assert window.quality.currentText() == 'Best available'
    window.close()


def test_bulk_validation(app, tmp_path):
    window = MainWindow(tmp_path / 'settings.json')
    dialog = BulkDialog([], window)
    dialog.editor.setPlainText('bad\nhttps://youtu.be/BaW_jenozKc')
    assert not dialog.save_button.isEnabled()
    dialog.editor.setPlainText('https://youtu.be/BaW_jenozKc\nhttps://youtube.com/watch?v=BaW_jenozKc')
    assert dialog.save_button.isEnabled()
    assert len(dialog.urls) == 1
    dialog.close()
    window.close()


def test_progress_waits_for_finalization(app, tmp_path):
    window = MainWindow(tmp_path / 'settings.json')
    window.set_overall(1)
    assert window.overall_bar.value() < 1000
    window.set_overall(1, final=True)
    assert window.overall_bar.value() == 1000
    window.close()


def test_thumbnail_network_success_displays_image(app, tmp_path):
    window = MainWindow(tmp_path / 'settings.json')
    image = QPixmap(16, 9)
    image.fill(Qt.GlobalColor.red)
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, 'PNG')
    class Reply:
        def error(self):
            return QNetworkReply.NetworkError.NoError
        def readAll(self):
            return buffer.data()
        def deleteLater(self):
            pass
    window.thumbnail_loaded(Reply(), window.generation)
    assert window.thumbnail is not None
    assert not window.preview.pixmap().isNull()
    window.close()


def test_render_both_themes(app, tmp_path):
    window = MainWindow(tmp_path / 'settings.json')
    window.show()
    app.processEvents()
    window.fit_initial_window(QRect(0, 0, 1920, 1040))
    app.processEvents()
    artifact = Path(__file__).resolve().parents[1] / 'artifacts'
    artifact.mkdir(exist_ok=True)
    window.grab().save(str(artifact / 'dark.png'))
    window.dark.setChecked(False)
    app.processEvents()
    window.grab().save(str(artifact / 'light.png'))
    window.close()


@pytest.mark.parametrize('mode', ['', 'Audio'])
@pytest.mark.parametrize('available,needs_scroll', [
    (QRect(0, 0, 1920, 1040), False),
    (QRect(1920, 0, 1536, 824), True),
    (QRect(-800, 0, 800, 560), True),
])
def test_startup_size_fits_work_area(app, tmp_path, mode, available, needs_scroll):
    window = MainWindow(tmp_path / 'settings.json')
    if mode == 'Audio':
        window.audio.click()
    window.show()
    app.processEvents()
    window.fit_initial_window(available)
    app.processEvents()
    assert available.contains(window.frameGeometry())
    scroll = window.centralWidget()
    assert (scroll.verticalScrollBar().maximum() > 0) == needs_scroll
    if not needs_scroll:
        assert not scroll.verticalScrollBar().isVisible()
        assert not scroll.horizontalScrollBar().isVisible()
    window.close()
