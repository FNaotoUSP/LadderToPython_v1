# 5_build_python_condition.py
# Gera código Python mínimo a partir de *_converted.json, usando arquivos *__tags_info.json
# para obter bobinas (saídas/coils).
# Lê *_converted.json em CONVERTED_DIR e procura *__tags_info.json em TAGS_OUT_DIR.
# Gera arquivos .py em FINAL_DIR.

import os, json, re, argparse
from pathlib import Path
from typing import List, Optional

# ---- DIRETORIOS ----
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONVERTED_DIR = os.path.join(BASE_DIR, "03_tags", "13_pseudo_final")
TAGS_OUT_DIR  = os.path.join(BASE_DIR, "03_tags")
FINAL_DIR     = os.path.join(BASE_DIR, "04_final")

# ---- PARAMETROS ----
CONVERTED_SUFFIX = "_converted.json"
TAGS_INFO_SUFFIX = "__tags_info.json"

DEBUG = True

# Imprime mensagens de debug apenas se DEBUG=True
def dbg(*args):
    if DEBUG:
        print(" ".join(str(a) for a in args))

# ---- UTILITÁRIOS DE NOME DE TAG ----

def clean_tag_name(raw: str) -> str:
    s = str(raw).strip()
    if s.startswith('%'):
        s = s[1:]
    s = s.replace('.', '_')
    s = re.sub(r'[^0-9A-Za-z_]', '_', s)
    if re.match(r'^\d', s):
        s = 'v_' + s
    return s

def extract_tags_from_expr(expr: str) -> List[str]:
    tags = set()
    if not expr:
        return []
    for t in re.findall(r'%[A-Za-z]\d+(?:\.\d+)?', expr):
        tags.add(clean_tag_name(t))
    for t in re.findall(r'\b[IQM]\d+_\d+\b', expr, flags=re.I):
        tags.add(clean_tag_name(t))
    return sorted(tags)

def common_prefix_len(a: str, b: str) -> int:
    L = min(len(a), len(b))
    i = 0
    while i < L and a[i] == b[i]:
        i += 1
    return i

def find_tags_info(tags_dir: Path, converted_stem: str) -> Optional[Path]:
    candidates = list(tags_dir.glob(f"*{TAGS_INFO_SUFFIX}"))
    if not candidates:
        return None
    for c in candidates:
        name_no_ext = c.stem
        if name_no_ext in converted_stem or converted_stem in name_no_ext:
            return c
    best = None
    best_len = 0
    for c in candidates:
        name_no_ext = c.stem
        cp = common_prefix_len(name_no_ext, converted_stem)
        if cp > best_len:
            best_len = cp
            best = c
    if best and best_len >= 8:
        return best
    if len(candidates) == 1:
        return candidates[0]
    return None

def load_coils_from_tags_info(json_path: Path) -> List[str]:
    try:
        raw = json_path.read_text(encoding='utf-8')
        data = json.loads(raw)
    except Exception as e:
        dbg("[WARN] Failed to read tags_info JSON:", json_path.name, e)
        return []
    coils_raw = []
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            text = item.get("text") or item.get("texto") or ""
            if not isinstance(text, str):
                continue
            if item.get("is_coil") is True:
                coils_raw.append(text)
        if not coils_raw:
            for item in data:
                text = item.get("text") or ""
                if isinstance(text, str) and re.match(r'%M\d+(?:\.\d+)?', text, flags=re.I):
                    coils_raw.append(text)
    else:
        dbg("[WARN] Unexpected format in tags_info JSON (expected list of objects)")
    coils = [clean_tag_name(x) for x in coils_raw if isinstance(x, str)]
    coils = [c for c in coils if re.match(r'^[IQM]\d+_\d+$', c, flags=re.I)]
    return sorted(set(coils))

# ---- GERA CÓDIGO DO MÓDULO FINAL COM EXPRESSÃO IF E INCLUSÃO DE BOBINAS ----

def build_module_code(base_stem: str,
                      original_expr: str,
                      python_expr: str,
                      input_tags: List[str],
                      coils: List[str]) -> str:
    header = f"# {original_expr}\n"
    # Indenta a expressão lógica para usar no if
    indented_expr = "\n    ".join(python_expr.strip().splitlines())
    coils_code = ""
    if coils:
        coils_code = ""
        for coil in coils:
            coils_code += f"    if {indented_expr}:\n"
            coils_code += f"        {coil} = True\n"
            coils_code += f"    else:\n"
            coils_code += f"        {coil} = False\n\n"
    else:
        # Se não houver bobinas, só coloca a expressão
        coils_code = f"    # Expressão lógica:\n    {indented_expr}\n"

    module = f"""{header}
def main():
{coils_code}if __name__ == '__main__':
    main()
"""
    return module

def process_converted_file(path: Path, tags_dir: Path, out_dir: Path):
    dbg("[*]", path.name)
    try:
        raw = path.read_text(encoding='utf-8')
        data = json.loads(raw)
    except Exception as e:
        dbg("[ERROR] reading converted.json:", path.name, e)
        return

    original_expr = data.get("original_expression") or data.get("expression") or ""
    python_expr = data.get("python_expression")
    if not python_expr:
        dbg("[WARN] no python_expression in", path.name)
        return

    input_tags = extract_tags_from_expr(original_expr)
    base_stem = path.stem.replace("_converted", "")

    tags_info_path = find_tags_info(tags_dir, path.stem)
    if tags_info_path:
        coils = load_coils_from_tags_info(tags_info_path)
        dbg("  tags_info:", tags_info_path.name, "-> coils:", coils)
    else:
        coils = []
        dbg("  tags_info: (not found)  IMNOTSURE if there's a corresponding *__tags_info.json file")

    code = build_module_code(base_stem, original_expr, python_expr, input_tags, coils)
    out_py = out_dir / f"{base_stem}_final_if_coils.py"
    out_disp = out_dir / f"{base_stem}_final_condition_display.txt"
    out_py.write_text(code, encoding='utf-8')
    out_disp.write_text(python_expr + "\n", encoding='utf-8')

    dbg("[OK]", path.name, "->", out_py.name)
    dbg("  tags:", input_tags)

# ---- MAIN ----

def main():
    import argparse
    ap = argparse.ArgumentParser(description="Generates final modules from *_converted.json (uses *__tags_info.json for coils)")
    ap.add_argument("--converted_dir", "-c", help="Directory of *_converted.json files", default=CONVERTED_DIR)
    ap.add_argument("--tags_dir", "-t", help="Directory of *__tags_info.json files", default=TAGS_OUT_DIR)
    ap.add_argument("--out_dir", "-o", help="Output directory (Python modules)", default=FINAL_DIR)
    ap.add_argument("--file", "-f", help="Process only a specific _converted.json file")
    ap.add_argument("--no-debug", action="store_true", help="Disable debug output")
    args = ap.parse_args()

    global DEBUG
    if args.no_debug:
        DEBUG = False

    converted_dir = Path(args.converted_dir)
    tags_dir = Path(args.tags_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.file:
        p = Path(args.file)
        if not p.exists():
            raise FileNotFoundError(p)
        process_converted_file(p, tags_dir, out_dir)
        return

    files = sorted(converted_dir.glob(f"*{CONVERTED_SUFFIX}"))
    if not files:
        print("No *_converted.json files found in", converted_dir)
        return

    for f in files:
        try:
            process_converted_file(f, tags_dir, out_dir)
        except Exception as e:
            dbg("[ERROR] processing", f.name, ":", e)

if __name__ == "__main__":
    main()