"""Arma la versión portable de CoraNotes para Windows x64 (herramienta de desarrollo).

Resultado:
  dist/CoraNotes/                         carpeta lista para usar (Python + librerías + app)
  dist/CoraNotes-<versión>-windows-x64.zip

El Python incluido es el «Windows embeddable package» oficial de python.org (firmado por la
Python Software Foundation). Se verifica su SHA-256 antes de usarlo. Las librerías se instalan
con las versiones exactas de requirements.txt, solo desde wheels (sin compilar nada).

Uso (desde la carpeta del proyecto, con el entorno de desarrollo):
  .venv\\Scripts\\python.exe scripts\\empaquetar.py
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from email.parser import Parser
from pathlib import Path

PY_VERSION = "3.13.16"
PY_TAG = "313"
PY_URL = f"https://www.python.org/ftp/python/{PY_VERSION}/python-{PY_VERSION}-embed-amd64.zip"
PY_SHA256 = "97dae5274cc54867065e8d5a3226e48c35017ed332a0fdb0e27d5b5821961297"  # python.org, página de la versión

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
DIST = ROOT / "dist"
OUT = DIST / "CoraNotes"

COPIAR = ["coranotes", "ejemplos", "README.md", ".env.example",
          "Iniciar CoraNotes.bat", "Detener CoraNotes.bat", "Mostrar Cora.bat",
          "Demo CoraNotes.bat", "Detener Demo.bat", "Reiniciar Demo.bat"]
SCRIPTS = ["_comun.ps1", "iniciar.ps1", "detener.ps1", "mascota.ps1", "reiniciar_demo.ps1",
           "restaurar_copia.ps1", "inicio_automatico.ps1"]

LEEME = """CoraNotes {version} — versión portable para Windows 10/11 (64 bits)
=====================================================================

No hace falta instalar nada: esta carpeta ya trae Python y todas las librerías.

1. Si descargaste el zip: clic derecho sobre el zip → Propiedades → marcá «Desbloquear» → Aceptar.
   Después descomprimilo donde quieras (por ejemplo en Documentos). Evitá «Archivos de programa».
2. Doble clic en «Iniciar CoraNotes.bat». Se abre el navegador y aparece Cora en el escritorio.
3. Para probar con datos ficticios: «Demo CoraNotes.bat» (no usa internet ni Gemini).
4. Para cerrar todo: «Detener CoraNotes.bat».

Gemini es opcional: copiá «.env.example» como «.env», completá GEMINI_API_KEY y reiniciá la app.
Tus datos se guardan aparte, en %LOCALAPPDATA%\\CoraNotes: para actualizar la app, reemplazá esta
carpeta por la nueva versión y tus datos se conservan.

Guía completa: README.md · Licencias de terceros: TERCEROS.txt
"""


def log(msg: str) -> None:
    print(f"[empaquetar] {msg}", flush=True)


def version_app() -> str:
    ns: dict = {}
    exec((ROOT / "coranotes" / "__init__.py").read_text(encoding="utf-8"), ns)
    return ns["__version__"]


def descargar_python() -> Path:
    BUILD.mkdir(exist_ok=True)
    destino = BUILD / f"python-{PY_VERSION}-embed-amd64.zip"
    if not destino.exists():
        log(f"Descargando {PY_URL}")
        with urllib.request.urlopen(PY_URL, timeout=120) as r, open(destino.with_suffix(".part"), "wb") as f:
            shutil.copyfileobj(r, f)
        destino.with_suffix(".part").replace(destino)
    real = hashlib.sha256(destino.read_bytes()).hexdigest()
    if real != PY_SHA256:
        destino.unlink()
        raise SystemExit(f"SHA-256 inesperado para {destino.name}: {real}. No se usa el archivo.")
    log(f"Python {PY_VERSION} verificado (SHA-256 correcto)")
    return destino


def verificar_firma(exe: Path) -> None:
    ps = (f"$s = Get-AuthenticodeSignature -LiteralPath '{exe}'; "
          "Write-Output ($s.Status.ToString() + '|' + $s.SignerCertificate.Subject)")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True).stdout.strip()
    estado, _, sujeto = out.partition("|")
    if estado != "Valid" or "Python Software Foundation" not in sujeto:
        raise SystemExit(f"Firma digital inesperada en {exe.name}: {out}")
    log(f"Firma de {exe.name} válida (Python Software Foundation)")


def preparar_runtime(zip_python: Path) -> Path:
    runtime = OUT / "runtime"
    runtime.mkdir(parents=True)
    with zipfile.ZipFile(zip_python) as zf:
        zf.extractall(runtime)
    verificar_firma(runtime / "python.exe")
    # ._pth: rutas de importación del Python embebido. «..» es la carpeta de la app (paquete coranotes).
    (runtime / f"python{PY_TAG}._pth").write_text(
        f"python{PY_TAG}.zip\n.\nLib\\site-packages\n..\nimport site\n", encoding="ascii")
    return runtime


def instalar_librerias(runtime: Path) -> None:
    destino = runtime / "Lib" / "site-packages"
    destino.mkdir(parents=True, exist_ok=True)
    log("Instalando librerías (versiones exactas, solo wheels para Windows x64)…")
    cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-warn-script-location",
           "--quiet", "--target", str(destino), "--platform", "win_amd64", "--python-version", PY_VERSION,
           "--implementation", "cp", "--only-binary=:all:", "--no-deps", "--no-compile",
           "-r", str(ROOT / "requirements.txt")]
    subprocess.run(cmd, check=True)
    # Los ejecutables de consola que crea pip (uvicorn.exe, etc.) no se usan y apuntan al Python de quien empaqueta.
    shutil.rmtree(destino / "bin", ignore_errors=True)


def copiar_app() -> None:
    ignorar = shutil.ignore_patterns("__pycache__", "*.pyc")
    for nombre in COPIAR:
        src = ROOT / nombre
        if src.is_dir():
            shutil.copytree(src, OUT / nombre, ignore=ignorar)
        else:
            shutil.copy2(src, OUT / nombre)
    (OUT / "scripts").mkdir()
    for nombre in SCRIPTS:
        shutil.copy2(ROOT / "scripts" / nombre, OUT / "scripts" / nombre)
    (OUT / "LEEME-PRIMERO.txt").write_text(LEEME.format(version=version_app()), encoding="utf-8-sig")


def licencias(runtime: Path) -> None:
    filas = []
    for meta in sorted((runtime / "Lib" / "site-packages").glob("*.dist-info/METADATA")):
        m = Parser().parsestr(meta.read_text(encoding="utf-8", errors="replace"), headersonly=True)
        lic = m.get("License-Expression") or ""
        if not lic:
            clas = [c.split("::")[-1].strip() for c in m.get_all("Classifier", []) if c.startswith("License ::")]
            lic = ", ".join(clas)
        if not lic:
            raw = (m.get("License") or "").strip()
            lic = raw.splitlines()[0][:80] if raw else "ver dist-info"
        filas.append(f"- {m['Name']} {m['Version']}: {lic}")
    texto = (
        "Componentes de terceros incluidos en CoraNotes (versión portable)\n"
        "=================================================================\n\n"
        f"- Python {PY_VERSION} (embeddable, python.org): PSF License — runtime\\LICENSE.txt\n"
        + "\n".join(filas) +
        "\n\nLos textos completos de cada licencia están en runtime\\Lib\\site-packages\\<paquete>.dist-info\\.\n\n"
        "Qt for Python (PySide6) se usa bajo la licencia LGPL-3.0: se distribuye como bibliotecas dinámicas\n"
        "sin modificar, que podés reemplazar por otra versión compatible en runtime\\Lib\\site-packages\\PySide6.\n"
        "Código fuente: https://code.qt.io/cgit/pyside/pyside-setup.git/ y https://download.qt.io/\n")
    (OUT / "TERCEROS.txt").write_text(texto, encoding="utf-8-sig")


def precompilar(runtime: Path) -> None:
    """Genera los .pyc con el mismo Python incluido: el primer inicio es mucho más rápido."""
    log("Precompilando (.pyc)…")
    subprocess.run([str(runtime / "python.exe"), "-m", "compileall", "-q", "-j", "0", "--invalidation-mode", "checked-hash",
                    str(runtime / "Lib" / "site-packages"), str(OUT / "coranotes")],
                   cwd=str(BUILD), check=True, capture_output=True)


def prueba_humo(runtime: Path) -> None:
    log("Prueba de humo con el Python incluido…")
    codigo = ("import fastapi, uvicorn, google.genai, watchdog, pypdf, docx, multipart, tzdata, sqlite3, winsound;"
              "import os; os.environ['QT_QPA_PLATFORM']='offscreen';"
              "from PySide6.QtWidgets import QApplication; app = QApplication([]);"
              "import coranotes.web.app, coranotes.mascota.app, coranotes.context;"
              "import sys; print('ok', sys.version.split()[0], sys.executable)")
    r = subprocess.run([str(runtime / "python.exe"), "-c", codigo], cwd=str(BUILD), capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.startswith("ok"):
        raise SystemExit(f"La prueba de humo falló:\n{r.stdout}\n{r.stderr}")
    log(r.stdout.strip())


def comprimir(version: str) -> Path:
    destino = DIST / f"CoraNotes-{version}-windows-x64.zip"
    if destino.exists():
        destino.unlink()
    log(f"Comprimiendo {destino.name}…")
    with zipfile.ZipFile(destino, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for f in sorted(OUT.rglob("*")):
            if f.is_file():
                zf.write(f, Path("CoraNotes") / f.relative_to(OUT))
    sha = hashlib.sha256(destino.read_bytes()).hexdigest()
    (DIST / (destino.name + ".sha256")).write_text(f"{sha}  {destino.name}\n", encoding="ascii")
    return destino


def main() -> None:
    version = version_app()
    if OUT.exists():
        shutil.rmtree(OUT)
    DIST.mkdir(exist_ok=True)
    zip_python = descargar_python()
    runtime = preparar_runtime(zip_python)
    instalar_librerias(runtime)
    copiar_app()
    licencias(runtime)
    precompilar(runtime)
    prueba_humo(runtime)
    destino = comprimir(version)
    tam_carpeta = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
    log(json.dumps({"carpeta": str(OUT), "carpeta_MB": round(tam_carpeta / 2**20),
                    "zip": str(destino), "zip_MB": round(destino.stat().st_size / 2**20)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
