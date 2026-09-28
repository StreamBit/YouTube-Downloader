import json
import os
from pathlib import Path
import sys
import tempfile

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'app'))

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication
import main


class PackagedWorker(main.Worker):
    def __init__(self, *args):
        super().__init__(*args)
        self.setProgram(str(root / 'dist/YouTube Downloader/engine/engine.exe'))
        self.setArguments([])


main.Worker = PackagedWorker
app = QApplication([])
for font in ('segoeui.ttf', 'segoeuib.ttf', 'seguisym.ttf'):
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/' + font)
with tempfile.TemporaryDirectory(prefix='ytd-gui-', dir=root / 'artifacts') as work:
    window = main.MainWindow(Path(work) / 'settings.json')
    window.show()
    window.audio.click()
    window.folder.setText(work)
    window.url.setText('https://www.youtube.com/watch?v=jNQXAC9IVRw')
    started = False
    elapsed = 0
    result = {}
    def check():
        global started, elapsed, result
        elapsed += 1
        if not started and window.video_title.text() == 'Me at the zoo':
            started = True
            window.start_run()
        if (started and window.finished_normally and window.worker is None) or elapsed >= 60:
            result = {'preview': window.video_title.text(), 'thumbnail': window.thumbnail is not None,
                      'summary': window.summary.text(), 'output_count': len(list(Path(work).glob('*.wav'))),
                      'temp_cleaned': not list(Path(work).glob('.ytd-work-*')), 'details': window.details.toPlainText()}
            window.grab().save(str(root / 'artifacts/completed.png'))
            timer.stop()
            window.close()
            app.quit()
    timer = QTimer()
    timer.timeout.connect(check)
    timer.start(1000)
    app.exec()
    print(json.dumps(result, indent=2))
    (root / 'artifacts/gui-smoke.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    raise SystemExit(0 if result.get('output_count') == 1 and result.get('thumbnail') and result.get('temp_cleaned') else 1)
