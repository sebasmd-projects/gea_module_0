import os
from pathlib import Path
from PIL import Image

# Carpeta raíz
ROOT_DIR = Path(".")

# Extensiones de imágenes soportadas (sin incluir webp porque ese es el destino)
SUPPORTED_EXTENSIONS = [".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".mp4"]

def convert_to_webp(root_dir):
    for path in root_dir.rglob("*"):
        print(path)
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            webp_path = path.with_suffix(".webp")

            # Saltar si ya existe en .webp
            if webp_path.exists():
                print(f"✅ Ya existe: {webp_path}")
                continue

            try:
                with Image.open(path) as img:
                    img.save(webp_path, "WEBP", quality=90)
                print(f"✔ Convertido: {path} → {webp_path}")
            except Exception as e:
                print(f"❌ Error al convertir {path}: {e}")

if __name__ == "__main__":
    convert_to_webp(ROOT_DIR)
