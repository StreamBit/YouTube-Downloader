import importlib.metadata
from pathlib import Path
import shutil

root = Path(__file__).resolve().parents[1]
destination = root / 'licenses'
destination.mkdir(exist_ok=True)
for distribution in importlib.metadata.distributions():
    name = distribution.metadata['Name']
    for file in distribution.files or []:
        if '.dist-info/' in str(file) and any(word in file.name.upper() for word in ('LICENSE', 'COPYING')):
            target = destination / name / Path(str(file)).name
            target.parent.mkdir(exist_ok=True)
            source = Path(distribution.locate_file(file))
            if source.is_file():
                shutil.copy2(source, target)
shutil.copy2('C:/Python314/LICENSE.txt', destination / 'Python.txt')
