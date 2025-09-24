# transcribe.py
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from tqdm import tqdm
from openai import OpenAI

"""
Transcripción bilingüe con OpenAI Audio API.
- Español (transcripción) y traducción al inglés.
- Soporta archivos .mp4, .mp3, .wav, .m4a, etc.

Modelo por defecto: gpt-4o-transcribe (alta precisión).
Si buscas más velocidad/costo, prueba: gpt-4o-mini-transcribe.

"gpt-4o-transcribe"

api_key = ''
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from tqdm import tqdm
from openai import OpenAI

MODEL_TRANSCRIBE = os.getenv("OA_AUDIO_MODEL", "gpt-4o-transcribe")
MODEL_TRANSLATE = os.getenv("OA_TEXT_MODEL", "gpt-4o")

def human_size(num_bytes: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if num_bytes < 1024.0:
            return f"{num_bytes:.1f}{unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f}TB"

def main():
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY", "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")
    if not api_key:
        print("ERROR: falta OPENAI_API_KEY en .env o en variables de entorno.")
        sys.exit(1)

    if len(sys.argv) < 2:
        print("Uso: python transcribe.py <ruta_audio_o_video>")
        sys.exit(1)

    media_path = Path(sys.argv[1]).expanduser().resolve()
    if not media_path.exists():
        print(f"ERROR: no existe el archivo: {media_path}")
        sys.exit(1)

    print(f"Archivo: {media_path.name} ({human_size(media_path.stat().st_size)})")
    client = OpenAI(api_key=api_key)

    # --- Transcripción en inglés ---
    print("\n1) Transcribiendo en inglés…")
    with open(media_path, "rb") as f:
        en = client.audio.transcriptions.create(
            model=MODEL_TRANSCRIBE,
            file=f,
            language="en"
        )

    en_text = getattr(en, "text", "")
    if not en_text:
        print("ADVERTENCIA: No llegó texto de la transcripción.")
        en_text = ""

    # --- Traducción al español ---
    print("2) Traduciendo al español…")
    tr = client.chat.completions.create(
        model=MODEL_TRANSLATE,
        messages=[
            {"role": "system", "content": "You are a translator from English to Spanish."},
            {"role": "user", "content": en_text}
        ]
    )

    es_text = tr.choices[0].message.content.strip()

    # --- Guardado ---
    out_en = media_path.with_name("transcription_en.txt")
    out_es = media_path.with_name("translation_es.txt")

    with open(out_en, "w", encoding="utf-8") as f:
        f.write(en_text.strip() + "\n")
    with open(out_es, "w", encoding="utf-8") as f:
        f.write(es_text.strip() + "\n")

    print("\n✅ Listo.")
    print(f"- Inglés:  {out_en}")
    print(f"- Español: {out_es}")

    def preview(s):
        s = (s or "").strip().replace("\n", " ")
        return s if len(s) <= 300 else s[:300] + "…"

    print("\nPreview EN:", preview(en_text))
    print("\nVista previa ES:", preview(es_text))

if __name__ == "__main__":
    for _ in tqdm(range(5), desc="Preparando", leave=False):
        pass
    main()
