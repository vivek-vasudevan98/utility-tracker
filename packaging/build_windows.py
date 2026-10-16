"""
Builds a self-contained Windows package of Utility Tracker: a folder (and a
zip of it) holding its own Python, the libraries, the app and the install
scripts. Nothing needs to be installed on the target computer.

Run from the project root on any computer with Python 3.9+, pip and internet
access to nuget.org and pypi.org (it doesn't have to be Windows):

    python packaging/build_windows.py

Output: dist/UtilityTracker/ and dist/UtilityTracker-windows.zip

The Python it bundles is the official python.org Windows build, taken from
its NuGet package and checked against a pinned SHA-256.
"""
import hashlib
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
PACKAGING = os.path.join(ROOT, 'packaging')
BUILD = os.path.join(ROOT, 'build')
DIST = os.path.join(ROOT, 'dist')
OUT = os.path.join(DIST, 'UtilityTracker')

PYTHON_VERSION = '3.12.10'
PYTHON_URL = f'https://api.nuget.org/v3-flatcontainer/python/{PYTHON_VERSION}/python.{PYTHON_VERSION}.nupkg'
PYTHON_SHA256 = '0eb85c2dfccccf1b17352de4c397f69194035b7d37149eacc16f1147d93de3b8'


def step(message):
    print(f'== {message}', flush=True)


def fetch_python():
    os.makedirs(BUILD, exist_ok=True)
    path = os.path.join(BUILD, f'python.{PYTHON_VERSION}.nupkg')
    if not os.path.exists(path):
        step(f'Downloading Python {PYTHON_VERSION} for Windows')
        urllib.request.urlretrieve(PYTHON_URL, path)
    digest = hashlib.sha256(open(path, 'rb').read()).hexdigest()
    if digest != PYTHON_SHA256:
        os.remove(path)
        sys.exit(f'Python package checksum mismatch ({digest}); download removed, nothing built.')
    return path


def extract_python(nupkg):
    step('Unpacking Python')
    target = os.path.join(OUT, 'python')
    with zipfile.ZipFile(nupkg) as z:
        for member in z.namelist():
            if not member.startswith('tools/') or member.endswith('/'):
                continue
            dest = os.path.join(target, *member[len('tools/'):].split('/'))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with z.open(member) as src, open(dest, 'wb') as out:
                shutil.copyfileobj(src, out)


def install_libraries():
    step('Installing libraries (Windows builds)')
    site_packages = os.path.join(OUT, 'python', 'Lib', 'site-packages')
    major_minor = ''.join(PYTHON_VERSION.split('.')[:2])
    subprocess.run([
        sys.executable, '-m', 'pip', 'install', '--quiet', '--disable-pip-version-check',
        '--target', site_packages, '--platform', 'win_amd64', '--implementation', 'cp',
        '--python-version', PYTHON_VERSION.rsplit('.', 1)[0], '--abi', f'cp{major_minor}',
        '--only-binary=:all:', '--no-compile',
        '-r', os.path.join(PACKAGING, 'requirements-windows.txt'),
    ], check=True)
    # Command-line wrappers pip writes for the build machine aren't needed
    shutil.rmtree(os.path.join(site_packages, 'bin'), ignore_errors=True)


def copy_app():
    step('Copying the app')
    app = os.path.join(OUT, 'app')
    shutil.copytree(os.path.join(ROOT, 'utility_app'), os.path.join(app, 'utility_app'),
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copy2(os.path.join(ROOT, 'serve.py'), app)


def copy_scripts():
    step('Adding install scripts')
    windows = os.path.join(OUT, 'windows')
    os.makedirs(windows, exist_ok=True)
    for name in os.listdir(os.path.join(PACKAGING, 'windows')):
        text = open(os.path.join(PACKAGING, 'windows', name), encoding='utf-8').read()
        # Windows scripts need CRLF line endings
        text = text.replace('\r\n', '\n').replace('\n', '\r\n')
        dest = OUT if name == 'Install Utility Tracker.bat' else windows
        with open(os.path.join(dest, name), 'w', encoding='utf-8', newline='') as f:
            f.write(text)
    text = open(os.path.join(PACKAGING, 'README-windows.txt'), encoding='utf-8').read()
    with open(os.path.join(OUT, 'README.txt'), 'w', encoding='utf-8', newline='') as f:
        f.write(text.replace('\r\n', '\n').replace('\n', '\r\n'))
    os.makedirs(os.path.join(OUT, 'data'), exist_ok=True)


def make_zip():
    step('Zipping')
    archive = shutil.make_archive(os.path.join(DIST, 'UtilityTracker-windows'), 'zip', DIST, 'UtilityTracker')
    size = os.path.getsize(archive) / 1e6
    print(f'Built {archive} ({size:.0f} MB)')


def main():
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT)
    extract_python(fetch_python())
    install_libraries()
    copy_app()
    copy_scripts()
    make_zip()


if __name__ == '__main__':
    main()
