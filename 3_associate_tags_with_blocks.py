# 3_associate_tags_with_blocks
# Associa TAGs (03_tags) aos retângulos (99_debug), cria expressão AND por retângulo
# e gera uma saída legível (TXT) mostrando quais tags foram "aglomeradas" em quais blocos.

import os, json, glob, re

# ---- DIRETORIOS ----
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_FIGS_DIR = os.path.join(BASE_DIR, "02_figures")
TAGS_OUT_DIR   = os.path.join(BASE_DIR, "03_tags")
CODE_DIR       = os.path.join(BASE_DIR, "04_final")
DEBUG_DIR      = os.path.join(BASE_DIR, "99_debug")

# ---- PARAMETROS ----
RECTS_SUFFIX_JSON = "__13_horiz_rects.json"   
TAGS_SUFFIX_JSON  = "__tags_with_nf.json"    

MIN_IOU_FOR_INTERSECT = 0.01

def load_json(path):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def iou(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    inter_x1, inter_y1 = max(ax1, bx1), max(ay1, by1)
    inter_x2, inter_y2 = min(ax2, bx2), min(ay2, by2)
    iw = max(0, inter_x2 - inter_x1 + 1)
    ih = max(0, inter_y2 - inter_y1 + 1)
    inter = iw * ih
    area_a = max(0, (ax2 - ax1 + 1)) * max(0, (ay2 - ay1 + 1))
    area_b = max(0, (bx2 - bx1 + 1)) * max(0, (by2 - by1 + 1))
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0

def box_center(box):
    x1, y1, x2, y2 = box
    return ((x1 + x2) // 2, (y1 + y2) // 2)

def point_in_box(pt, box):
    x, y = pt
    x1, y1, x2, y2 = box
    return (x1 <= x <= x2) and (y1 <= y <= y2)

def to_box_from_tag_pl(tag):
    """
    Converte o formato das suas TAGs:
    { "text": "...", "x": int, "y": int, "w": int, "h": int, "conf": float, "is_coil": bool }
    para uma bbox [x1,y1,x2,y2].
    """
    x1 = int(tag["x"])
    y1 = int(tag["y"])
    x2 = x1 + int(tag["w"]) - 1
    y2 = y1 + int(tag["h"]) - 1
    return [x1, y1, x2, y2]

def rect_list_from_rect_json(rect_json):
    rects = []
    if isinstance(rect_json, dict) and "rectangles" in rect_json:
        items = rect_json["rectangles"]
    else:
        items = rect_json if isinstance(rect_json, list) else [rect_json]

    for item in items:
        if isinstance(item, dict) and all(k in item for k in ("x1","y1","x2","y2")):
            rects.append([int(item["x1"]), int(item["y1"]), int(item["x2"]), int(item["y2"])])
        elif isinstance(item, dict) and "rect" in item:
            x1, y1, x2, y2 = item["rect"]
            rects.append([int(x1), int(y1), int(x2), int(y2)])
        elif isinstance(item, dict) and "rectangles" in item:
            for r in item["rectangles"]:
                rects.append([int(r["x1"]), int(r["y1"]), int(r["x2"]), int(r["y2"])])
    return rects

def build_and_expression(tags):
    # Usa 'text' como nome da tag
    names = [str(t.get("text", "")).strip() for t in tags if str(t.get("text", "")).strip()]
    if not names:
        return None
    if len(names) == 1:
        return names[0]
    names = sorted(names)
    return "AND(" + ", ".join(names) + ")"

def normalize_tags_list(tags_json):
    """
    Seus arquivos são uma lista direta de tags. Mantemos apenas não-coils.
    """
    if isinstance(tags_json, list):
        tags = tags_json
    elif isinstance(tags_json, dict) and "tags" in tags_json:
        tags = tags_json["tags"]
    else:
        tags = []

    # filtra coils
    filtered = []
    for t in tags:
        is_coil = bool(t.get("is_coil", False))
        if is_coil:
            continue
        if all(k in t for k in ("text", "x", "y", "w", "h")):
            filtered.append(t)
    return filtered

def find_tags_file_for_base(image_base_name):
    """
    Estratégia robusta para localizar o arquivo de tags.
    1) Tenta exatamente: <base> + _tags.json
    2) Se não achar, procura por: <base>*_tags.json
    3) Se não achar, tenta reduzir o base ao tronco até 'Network_<n>' e
    buscar por: <tronco>*_tags.json
    Retorna caminho encontrado ou None.
    """
    exact = os.path.join(TAGS_OUT_DIR, f"{image_base_name}{TAGS_SUFFIX_JSON}")
    if os.path.exists(exact):
        return exact

    # 2) base* _tags.json
    candidates = sorted(glob.glob(os.path.join(TAGS_OUT_DIR, f"{image_base_name}*{TAGS_SUFFIX_JSON}")))
    if candidates:
        return candidates[0]

    # 3) tronco até Network_N
    m = re.match(r"^(page\d+_network\d+_Network_\d+)", image_base_name)
    if m:
        trunk = m.group(1)
        candidates = sorted(glob.glob(os.path.join(TAGS_OUT_DIR, f"{trunk}*{TAGS_SUFFIX_JSON}")))
        if candidates:
            return candidates[0]

    return None

def associate_tags_and_rects(image_base_name):
    # Retângulos
    rect_path = os.path.join(DEBUG_DIR, f"{image_base_name}{RECTS_SUFFIX_JSON}")
    rect_json = load_json(rect_path)
    if rect_json is None:
        print(f"[AVISO] Retângulos não encontrados: {rect_path}")
        return None

    # Tags
    tags_path = find_tags_file_for_base(image_base_name)
    if tags_path is None:
        print(f"[AVISO] TAGs não encontradas para base '{image_base_name}' em {TAGS_OUT_DIR}")
        return None

    tags_json = load_json(tags_path)
    if tags_json is None:
        print(f"[AVISO] Falha ao carregar arquivo de TAGs: {tags_path}")
        return None

    # Log do arquivo de tags efetivo
    print(f"[INFO] Usando TAGs de: {tags_path}")

    rects = rect_list_from_rect_json(rect_json)
    tags = normalize_tags_list(tags_json)

    groups = [{"rect": r, "tags": []} for r in rects]

    # Associa cada tag ao retângulo
    for tag in tags:
        tbox = to_box_from_tag_pl(tag)

        # 1) IoU
        best_i, best_val = -1, 0.0
        for i, g in enumerate(groups):
            v = iou(tbox, g["rect"])
            if v > best_val:
                best_val, best_i = v, i
        if best_val >= MIN_IOU_FOR_INTERSECT:
            groups[best_i]["tags"].append(tag)
            continue

        # 2) centro dentro
        c = box_center(tbox)
        for i, g in enumerate(groups):
            if point_in_box(c, g["rect"]):
                groups[i]["tags"].append(tag)
                break

    # Estrutura final
    out_groups = []
    for g in groups:
        out_groups.append({
            "rect": g["rect"],
            "tags": g["tags"],
            "expression": build_and_expression(g["tags"])
        })

    return out_groups

def write_readable_txt(image_base_name, groups):
    out_path = os.path.join(DEBUG_DIR, f"{image_base_name}__14_groups_AND_readable.txt")
    lines = []
    lines.append(f"Imagem base: {image_base_name}")
    lines.append(f"Dirs: rects=99_debug, tags=03_tags")
    lines.append("Agrupamento: AND(tags no mesmo retângulo)")
    lines.append("")

    for idx, g in enumerate(groups, start=1):
        x1, y1, x2, y2 = g["rect"]
        names = [str(t.get("text", "")).strip() for t in g["tags"] if str(t.get("text", "")).strip()]
        tag_list_str = ", ".join(sorted(names)) if names else "(sem TAGs)"
        expr = g["expression"] if g["expression"] else "(sem expressão)"
        lines.append(f"Bloco #{idx}  rect=[x1={x1}, y1={y1}, x2={x2}, y2={y2}]  width={x2-x1+1}  height={y2-y1+1}")
        lines.append(f"  TAGs: {tag_list_str}")
        lines.append(f"  AND:  {expr}")
        lines.append("")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return out_path

# ---- MAIN ----

def main():
    rect_files = glob.glob(os.path.join(DEBUG_DIR, f"*{RECTS_SUFFIX_JSON}"))
    if not rect_files:
        print(f"[ERRO] Nenhum arquivo {RECTS_SUFFIX_JSON} encontrado em {DEBUG_DIR}")
        return

    for rfile in sorted(rect_files):
        base = os.path.basename(rfile)[:-len(RECTS_SUFFIX_JSON)]
        groups = associate_tags_and_rects(base)
        if groups is None:
            continue

        out_json = os.path.join(DEBUG_DIR, f"{base}__14_groups_AND.json")
        with open(out_json, "w", encoding="utf-8") as f:
            json.dump({
                "image_base": base,
                "logic": "AND within same rectangle",
                "groups": groups
            }, f, ensure_ascii=False, indent=2)

        out_txt = write_readable_txt(base, groups)

        print(f"[OK] {base}:")
        print(f"    - grupos JSON: {out_json}")
        print(f"    - leitura fácil: {out_txt}")

if __name__ == "__main__":
    main()