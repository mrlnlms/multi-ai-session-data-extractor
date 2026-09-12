#!/usr/bin/env python
"""Deduplicador de assets — converte copias fisicas em hardlinks.

Varre data/raw e data/merged em busca de arquivos identicos (mesmo path relativo,
mesmo tamanho e mesmo hash) que nao compartilham o mesmo inode. Substitui
a copia em 'merged' por um hardlink para o original em 'raw'.

Uso:
    PYTHONPATH=. .venv/bin/python scripts/deduplicate-assets.py
"""

import hashlib
import logging
import os
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

def get_file_hash(path: Path) -> str:
    """Calcula MD5 do arquivo em chunks."""
    hash_md5 = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def deduplicate():
    raw_dir = DATA_DIR / "raw"
    merged_dir = DATA_DIR / "merged"
    
    if not (raw_dir.exists() and merged_dir.exists()):
        logger.error("Pastas data/raw ou data/merged nao encontradas.")
        return

    saved_bytes = 0
    processed_files = 0
    linked_files = 0

    # Focamos em NotebookLM que eh o maior, mas o script eh generico
    for raw_file in raw_dir.rglob("*"):
        if not raw_file.is_file():
            continue
        
        # Path relativo a data/raw
        rel_path = raw_file.relative_to(raw_dir)
        merged_file = merged_dir / rel_path
        
        if not merged_file.exists() or not merged_file.is_file():
            continue
            
        processed_files += 1
        
        # Se ja tem o mesmo inode, ja eh um hardlink
        raw_stat = raw_file.stat()
        merged_stat = merged_file.stat()
        
        if raw_stat.st_ino == merged_stat.st_ino:
            continue
            
        # Verifica se sao identicos (tamanho primeiro, depois hash)
        if raw_stat.st_size != merged_stat.st_size:
            continue
            
        if get_file_hash(raw_file) == get_file_hash(merged_file):
            # Identicos mas inodes diferentes -> Deleta merged e linka
            size = merged_stat.st_size
            try:
                # Operacao atomica: linka pra um temp e renomeia
                temp_link = merged_file.with_suffix(merged_file.suffix + ".tmp_link")
                os.link(raw_file, temp_link)
                os.replace(temp_link, merged_file)
                
                saved_bytes += size
                linked_files += 1
                if size > 1024 * 1024: # Loga so arquivos > 1MB pra nao poluir
                    logger.info(f"Linked: {rel_path} ({size / 1024 / 1024:.1f} MB)")
            except Exception as e:
                logger.error(f"Erro ao linkar {rel_path}: {e}")

    logger.info("-" * 40)
    logger.info(f"Concluido!")
    logger.info(f"Arquivos analisados: {processed_files}")
    logger.info(f"Novos links criados: {linked_files}")
    logger.info(f"Espaço recuperado: {saved_bytes / 1024 / 1024:.1f} MB")

if __name__ == "__main__":
    deduplicate()
