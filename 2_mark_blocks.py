# 2_mark_blocks.py
# Marca e fragmenta linhas em diagramas Ladder a partir de imagens, recorta a coluna de bobinas (margem direita),
# gera retângulos a partir de horizontais fragmentadas e exporta verticais válidas. Preserva imagens de depuração.

import os, glob, cv2, csv, json
import numpy as np

# ---- DIRETORIOS ----
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_FIGS_DIR = os.path.join(BASE_DIR, "02_figures")
DEBUG_DIR      = os.path.join(BASE_DIR, "99_debug")
TAGS_DIR       = os.path.join(BASE_DIR, "03_tags")

os.makedirs(DEBUG_DIR, exist_ok=True)

# ---- PARAMETROS ----
RIGHT_MARGIN_PIXELS = 220  # Coluna de corte na margem direita (área da bobina)
OFFSET_LEFT = 25  # Deslocamento em pixels para mover a linha para a esquerda

H_MAX_PX = 700   # Horizontais: comprimento máximo
V_MIN_PX = 30    # Verticais: comprimento mínimo

GAP_MAX_PX = 35  # Fechamento de gaps em horizontais (tamanho máx. do gap)
ITER_CLOSE = 2   # Iterações de fechamento

CUT_MARGIN_X = 2  # Margem lateral de corte no cruzamento
CUT_MARGIN_Y = 2  # Margem vertical de corte no cruzamento

VERT_MIN_ASPECT = 6.0
VERT_MIN_WIDTH = 1
VERT_MIN_HEIGHT = 25

# ---- PARAMETROS DOS BLOCOS ----
RECT_PAD_Y = 50    # Expansão vertical p/ cobrir TAGs
RECT_PAD_X = 6     # Expansão lateral
RECT_MIN_WIDTH = 40  # Ignora fragmentos muito curtos
CENTER_OFFSET_Y = -6 # Move o retângulo 6 px para cima
TRIM_TOP = 10     # Corta 10 px do topo após construir a caixa
TRIM_BOTTOM = 16  # Corta 16 px da base após construir a caixa

# Mescla de retângulos (opcional; desabilitado por padrão)
ENABLE_RECT_MERGE = False
MERGE_IOU_THRESH = 0.05  # Limite de interseção p/ mesclar

# ---- FUNÇÕES UTILITÁRIAS ----

# Carrega imagens de um diretório com extensões comuns
def load_images(img_dir):
    exts = ("*.png", "*.jpg", "*.jpeg", "*.bmp", "*.tif", "*.tiff")
    files = []
    for e in exts:
        files.extend(glob.glob(os.path.join(img_dir, e)))
    return sorted(files)

# Binariza imagem em tons de cinza com limiar adaptativo
def binarize(img_gray):
    return cv2.adaptiveThreshold(
        img_gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV,
        31, 10
    )

# Extrai linhas verticais a partir da imagem binária
def extract_vertical(binary):
    h, w = binary.shape
    klen = max(10, h // 60)
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (1, klen))
    opened = cv2.morphologyEx(binary, cv2.MORPH_OPEN, k, iterations=1)
    dil = cv2.dilate(opened, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 5)), iterations=1)
    return dil

# Extrai linhas horizontais a partir da imagem binária
def extract_horizontal(binary):
    h, w = binary.shape
    klen = max(10, w // 60)
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (klen, 1))
    opened = cv2.morphologyEx(binary, cv2.MORPH_OPEN, k, iterations=1)
    dil = cv2.dilate(opened, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 3)), iterations=1)
    return dil

# Filtra componentes conectados por comprimento (mín./máx.) conforme orientação
def filter_by_length(mask, orientation="horizontal", min_len=None, max_len=None):
    if mask.max() == 0:
        return mask.copy()
    out = np.zeros_like(mask)
    num, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    for i in range(1, num):
        x, y, w, h, area = stats[i]
        length = w if orientation == "horizontal" else h
        if min_len is not None and length < min_len:
            continue
        if max_len is not None and length > max_len:
            continue
        out[labels == i] = 255
    return out

# Fecha pequenos gaps em linhas horizontais ao longo de múltiplas iterações
def close_horizontal_gaps(mask, gap_max=35, iters=2):
    if mask.max() == 0:
        return mask.copy()
    h, w = mask.shape
    m = mask.copy()

    def fill_once(src):
        dst = src.copy()
        for y in range(h):
            row = src[y]
            xs = np.where(row > 0)[0]
            if xs.size == 0:
                continue
            splits = np.where(np.diff(xs) > 1)[0]
            starts = np.r_[xs[0], xs[splits + 1]]
            ends = np.r_[xs[splits], xs[-1]]
            for i in range(len(starts) - 1):
                s1, e1 = starts[i], ends[i]
                s2, e2 = starts[i + 1], ends[i + 1]
                gap = s2 - e1 - 1
                if 0 < gap <= gap_max:
                    dst[y, e1 + 1: s2] = 255
                    if y - 1 >= 0: 
                        dst[y - 1, e1 + 1: s2] = 255
                    if y + 1 < h: 
                        dst[y + 1, e1 + 1: s2] = 255
        return dst

    for _ in range(iters):
        m = fill_once(m)

    m = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 1)), iterations=1)
    return m

# Reprenha componentes conectados como linhas “esticadas” (visualização)
def stretch_components(mask, orientation="horizontal", thickness=3):
    if mask.max() == 0:
        return mask.copy()
    out = np.zeros_like(mask)
    num, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    for i in range(1, num):
        x, y, w, h, area = stats[i]
        if area < 20:
            continue
        if orientation == "horizontal":
            cy = y + h // 2
            cv2.line(out, (x, cy), (x + w, cy), 255, thickness)
        else:
            cx = x + w // 2
            cv2.line(out, (cx, y), (cx, y + h), 255, thickness)
    return out

# Seleciona verticais “verdadeiras” com base em razão de aspecto e tamanho
def select_true_verticals(vert_mask):
    if vert_mask.max() == 0:
        return vert_mask.copy(), []
    out = np.zeros_like(vert_mask)
    num, labels, stats, _ = cv2.connectedComponentsWithStats(vert_mask, 8)
    valid_boxes = []
    for i in range(1, num):
        x, y, w, h, area = stats[i]
        if h < max(V_MIN_PX, VERT_MIN_HEIGHT):
            continue
        if w < VERT_MIN_WIDTH:
            continue
        aspect = h / max(1, w)
        if aspect < VERT_MIN_ASPECT:
            continue
        out[labels == i] = 255
        valid_boxes.append((x, y, w, h))
    return out, valid_boxes

# Fragmenta horizontais cortando regiões que cruzam as caixas dos verticais válidos
def fragment_horizontals_by_vertical_bboxes(horiz_mask, vert_mask, cut_margin_x=2, cut_margin_y=2):
    H = horiz_mask.copy()
    Vf, boxes = select_true_verticals(vert_mask)
    if H.max() == 0 or len(boxes) == 0:
        return H, Vf
    h, w = H.shape
    for (x, y, bw, bh) in boxes:
        x1 = max(0, x - cut_margin_x)
        x2 = min(w - 1, x + bw - 1 + cut_margin_x)
        y1 = max(0, y - cut_margin_y)
        y2 = min(h - 1, y + bh - 1 + cut_margin_y)
        H[y1:y2+1, x1:x2+1] = 0
    return H, Vf

# Sobrepõe máscaras de linhas na imagem RGB (depuração)
def overlay_lines(rgb, vert_mask, horiz_mask):
    out = rgb.copy()
    v = vert_mask > 0
    h = horiz_mask > 0
    out[v] = (0, 0, 255)    # Vermelho p/ verticais
    out[h] = (0, 255, 0)    # Verde p/ horizontais
    out[v & h] = (0, 255, 255) # Amarelo p/ interseções
    return out

# ---- INJEÇÃO DE COLUNA DE CORTE NA MARGEM DIREITA ----

# Injeta uma coluna branca na posição x = W - RIGHT_MARGIN_PIXELS para forçar corte na área de bobina
def inject_coil_boundary_cut(vert_mask, image_width, right_margin_px=RIGHT_MARGIN_PIXELS):
    h, w = vert_mask.shape
    x_thr = max(0, image_width - int(right_margin_px))
    x_thr = min(w - 1, x_thr)
    out = vert_mask.copy()
    out[:, x_thr:x_thr+1] = 255
    return out, x_thr

# Função para carregar o valor "x" das bobinas do JSON correspondente
def load_coil_x_from_json(base_name):
    # Ajusta nome para buscar JSON correspondente
    json_pattern = os.path.join(TAGS_DIR, f"{base_name}*_tags_with_nf.json")
    json_files = glob.glob(json_pattern)
    if not json_files:
        print(f"[WARN] JSON file not found for base name: {base_name}")
        return None
    json_path = json_files[0]
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # data é uma lista de objetos, cada um com 'x' e 'is_coil'
        x_values = [item['x'] for item in data if item.get('is_coil', False) and 'x' in item]
        if not x_values:
            print(f"[WARN] No 'x' values found in JSON: {json_path}")
            return None
        return min(x_values)
    except Exception as e:
        print(f"[ERROR] Failed to load or parse JSON: {json_path} | {e}")
        return None

# ---- RETÂNGULOS A PARTIR DE HORIZONTAIS FRAGMENTADAS ----

# Converte componentes horizontais fragmentados em retângulos expandidos
def horizontals_to_rectangles(
    horiz_mask,
    pad_x=RECT_PAD_X,
    pad_y=RECT_PAD_Y,
    min_width=RECT_MIN_WIDTH,
    center_offset_y=CENTER_OFFSET_Y,
    trim_top=TRIM_TOP,
    trim_bottom=TRIM_BOTTOM
):
    h, w = horiz_mask.shape
    rect_mask = np.zeros_like(horiz_mask)
    rects = []

    if horiz_mask.max() == 0:
        return rect_mask, rects

    num, labels, stats, _ = cv2.connectedComponentsWithStats(horiz_mask, 8)
    for i in range(1, num):
        x, y, bw, bh, area = stats[i]
        if bw < min_width:
            continue

        cy = y + bh // 2
        cy = int(np.clip(cy + center_offset_y, 0, h - 1))

        x1 = max(0, x - pad_x)
        x2 = min(w - 1, x + bw - 1 + pad_x)
        y1 = max(0, cy - pad_y)
        y2 = min(h - 1, cy + pad_y)

        y1 = min(y1 + int(max(0, trim_top)), y2)
        y2 = max(y2 - int(max(0, trim_bottom)), y1)

        rect_mask[y1:y2+1, x1:x2+1] = 255
        rects.append([int(x1), int(y1), int(x2), int(y2)])

    return rect_mask, rects

# Calcula IoU (Intersection over Union) entre dois retângulos
def iou(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    inter_x1, inter_y1 = max(ax1, bx1), max(ay1, by1)
    inter_x2, inter_y2 = min(ax2, bx2), min(ay2, by2)
    iw = max(0, inter_x2 - inter_x1 + 1)
    ih = max(0, inter_y2 - inter_y1 + 1)
    inter = iw * ih
    area_a = (ax2 - ax1 + 1) * (ay2 - ay1 + 1)
    area_b = (bx2 - bx1 + 1) * (by2 - by1 + 1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0

# Mescla retângulos com base em um limite de IoU
def merge_rectangles(rects, iou_thresh=MERGE_IOU_THRESH):
    if not rects:
        return rects
    rects = sorted(rects, key=lambda r: (r[1], r[0]))
    merged = []
    for r in rects:
        if not merged:
            merged.append(r)
            continue
        merged_flag = False
        for j in range(len(merged)):
            if iou(r, merged[j]) >= iou_thresh:
                ax1, ay1, ax2, ay2 = merged[j]
                bx1, by1, bx2, by2 = r
                merged[j] = [min(ax1, bx1), min(ay1, by1), max(ax2, bx2), max(ay2, by2)]
                merged_flag = True
                break
        if not merged_flag:
            merged.append(r)
    return merged

# Desenha retângulos na imagem BGR (depuração)
def draw_rectangles_on_image(img_bgr, rects, color=(255, 255, 0), thickness=2):
    out = img_bgr.copy()
    for (x1, y1, x2, y2) in rects:
        cv2.rectangle(out, (x1, y1), (x2, y2), color, thickness)
    return out

# ---- EXPORTAÇÃO: VERTICAIS VÁLIDAS COM IDs ----

# Exporta verticais válidas (sem a coluna de corte) em JSON com IDs e gera PNG auxiliar com IDs
def export_verticals_with_ids(base_name, img_shape, vert_mask_no_cut, out_dir=DEBUG_DIR):
    H, W = img_shape[:2]

    # Seleciona verticais válidas (sem a coluna de corte)
    vert_true, boxes = select_true_verticals(vert_mask_no_cut)
    verticals = []
    for idx, (x, y, w, h) in enumerate(boxes):
        cx = int(x + w // 2)
        y1 = int(y)
        y2 = int(y + h - 1)
        verticals.append({"id": idx, "x": cx, "y1": y1, "y2": y2})

    # Salva JSON
    out_json = os.path.join(out_dir, f"{base_name}__04_vert_lenFiltered.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump({"verticals": verticals}, f, ensure_ascii=False, indent=2)

    # Gera imagem auxiliar com IDs plotados
    canvas = np.zeros((H, W, 3), dtype=np.uint8)
    for v in verticals:
        x, y1, y2, vid = v["x"], v["y1"], v["y2"], v["id"]
        cv2.line(canvas, (x, y1), (x, y2), (255, 255, 255), 2)
        yy = max(0, y1 - 6)
        cv2.putText(canvas, str(vid), (x + 3, yy), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 255), 1, cv2.LINE_AA)

    out_png = os.path.join(out_dir, f"{base_name}__04_vert_lenFiltered_ids.png")
    cv2.imwrite(out_png, canvas)

    return out_json

# ---- PIPELINE POR IMAGEM ----

# Executa o pipeline completo para uma única imagem e salva artefatos de depuração
def process_image(path):
    name = os.path.splitext(os.path.basename(path))[0]
    img = cv2.imread(path)
    if img is None:
        print(f"[WARN] Failed to open: {path}")
        return

    cv2.imwrite(os.path.join(DEBUG_DIR, f"{name}__00_original.png"), img)

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    bin_img = binarize(gray)
    cv2.imwrite(os.path.join(DEBUG_DIR, f"{name}__01_binary.png"), bin_img)

    # Extração de linhas
    vert_raw = extract_vertical(bin_img)
    horiz_raw = extract_horizontal(bin_img)
    cv2.imwrite(os.path.join(DEBUG_DIR, f"{name}__02_vert_raw.png"), vert_raw)
    cv2.imwrite(os.path.join(DEBUG_DIR, f"{name}__03_horiz_raw.png"), horiz_raw)

    # Filtro por comprimento
    vert_len = filter_by_length(vert_raw, "vertical", min_len=V_MIN_PX, max_len=None)
    horiz_len = filter_by_length(horiz_raw, "horizontal", min_len=None, max_len=H_MAX_PX)
    cv2.imwrite(os.path.join(DEBUG_DIR, f"{name}__04_vert_lenFiltered.png"), vert_len)

    # Exporta verticais válidas (sem o corte), com IDs, antes de injetar a coluna
    export_verticals_with_ids(base_name=name, img_shape=img.shape, vert_mask_no_cut=vert_len, out_dir=DEBUG_DIR)

    # Injeta a coluna de corte na margem direita e salva
    H_img, W_img = img.shape[:2]
    # Carrega valor dinâmico de x das bobinas do JSON
    coil_x = load_coil_x_from_json(name)
    if coil_x is not None:
        right_margin_px = max(0, W_img - coil_x + OFFSET_LEFT)
    else:
        right_margin_px = RIGHT_MARGIN_PIXELS
    vert_len_with_cut, x_thr = inject_coil_boundary_cut(vert_len, W_img, right_margin_px=right_margin_px)
    cv2.imwrite(os.path.join(DEBUG_DIR, f"{name}__05_vert_lenFiltered_with_coil_cut.png"), vert_len_with_cut)

    # Para referência, salva horizontais filtradas por comprimento
    cv2.imwrite(os.path.join(DEBUG_DIR, f"{name}__05_horiz_lenFiltered.png"), horiz_len)

    # Completa horizontais (fecha gaps)
    horiz_completed = close_horizontal_gaps(horiz_len, gap_max=GAP_MAX_PX, iters=ITER_CLOSE)
    cv2.imwrite(os.path.join(DEBUG_DIR, f"{name}__06_horiz_completed.png"), horiz_completed)

    # Fragmenta horizontais usando exatamente as verticais com corte
    horiz_fragmented, vert_true = fragment_horizontals_by_vertical_bboxes(
        horiz_mask=horiz_completed,
        vert_mask=vert_len_with_cut,   # chave: usa a máscara com a coluna de corte
        cut_margin_x=CUT_MARGIN_X,
        cut_margin_y=CUT_MARGIN_Y
    )
    cv2.imwrite(os.path.join(DEBUG_DIR, f"{name}__07_horiz_fragmented_base.png"), horiz_fragmented)
    cv2.imwrite(os.path.join(DEBUG_DIR, f"{name}__08_vert_trueOnly.png"), vert_true)

    # Estica componentes (visualização)
    vert_final = stretch_components(vert_true, orientation="vertical", thickness=3)
    horiz_final = stretch_components(horiz_fragmented, orientation="horizontal", thickness=3)
    cv2.imwrite(os.path.join(DEBUG_DIR, f"{name}__09_vert_stretched.png"), vert_final)
    cv2.imwrite(os.path.join(DEBUG_DIR, f"{name}__10_horiz_stretched.png"), horiz_final)

    annotated = overlay_lines(img, vert_final, horiz_final)
    cv2.imwrite(os.path.join(DEBUG_DIR, f"{name}__11_annotated_fragmented.png"), annotated)

    # ---- RETÂNGULOS A PARTIR DAS HORIZONTAIS FRAGMENTADAS ----
    rect_mask, rects = horizontals_to_rectangles(
        horiz_mask=horiz_fragmented,
        pad_x=RECT_PAD_X,
        pad_y=RECT_PAD_Y,
        min_width=RECT_MIN_WIDTH,
        center_offset_y=CENTER_OFFSET_Y,
        trim_top=TRIM_TOP,
        trim_bottom=TRIM_BOTTOM
    )

    if ENABLE_RECT_MERGE:
        rects = merge_rectangles(rects, iou_thresh=MERGE_IOU_THRESH)

    # Máscara e anotação
    cv2.imwrite(os.path.join(DEBUG_DIR, f"{name}__12_horiz_rect_mask.png"), rect_mask)
    img_rects = draw_rectangles_on_image(img, rects, color=(255, 255, 0), thickness=2)

    # Desenha a margem direita (mesmo x_thr do corte) na anotação final
    out13 = img_rects.copy()
    cv2.rectangle(out13, (x_thr, 0), (W_img - 1, H_img - 1), (255, 200, 0), 2)
    cv2.imwrite(os.path.join(DEBUG_DIR, f"{name}__13_horiz_rects_on_original.png"), out13)

    # Exporta retângulos (CSV/JSON)
    csv_path = os.path.join(DEBUG_DIR, f"{name}__13_horiz_rects.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["x1", "y1", "x2", "y2", "width", "height"])
        for (x1, y1, x2, y2) in rects:
            writer.writerow([x1, y1, x2, y2, x2 - x1 + 1, y2 - y1 + 1])

    json_path = os.path.join(DEBUG_DIR, f"{name}__13_horiz_rects.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(
            [{"x1": x1, "y1": y1, "x2": x2, "y2": y2, "width": (x2 - x1 + 1), "height": (y2 - y1 + 1)}
             for (x1, y1, x2, y2) in rects],
            f, ensure_ascii=False, indent=2
        )

    print(f"[OK] Processed: {name} | Rectangles (fragments): {len(rects)}")

# ---- MAIN ----

def main():
    files = load_images(INPUT_FIGS_DIR)
    if not files:
        print(f"No images found in: {INPUT_FIGS_DIR}")
        return
    for f in files:
        process_image(f)

if __name__ == "__main__":
    main()