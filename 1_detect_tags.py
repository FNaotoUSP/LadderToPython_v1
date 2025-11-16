# 1_detect_tags.py
# Detecta as TAGs utilizando OCR

from PIL import Image, ImageOps, ImageEnhance, ImageFilter, ImageDraw, ImageFont
import re, os, json, pytesseract 

# ---- DIRETÓRIOS ----
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR = os.path.join(BASE_DIR, "02_figures")
TAGS_OUT_DIR = os.path.join(BASE_DIR, "03_tags")
DEBUG_DIR = os.path.join(BASE_DIR, "99_debug")

# ---- PARÂMETROS ----
DEFAULT_REMOVE_TOL_X = 6
DEFAULT_REMOVE_TOL_Y = 6
COIL_X_MARGIN = 50  

# Garante que os diretórios de entrada/saída existem
for d in [INPUT_DIR, TAGS_OUT_DIR, DEBUG_DIR]:
    os.makedirs(d, exist_ok=True)

# Corrige padrões comuns do OCR e normaliza o formato das TAGs (ex.: %I0.0)
def corrigir_erros_ocr(s: str) -> str:
    if not s:
        return ""
    s = s.strip()
    s = s.replace('"', '').replace('´', "'").replace('`', "'")
    s = s.replace('—', '-').replace('–', '-').replace('¬', '').replace('·', '.')
    s = re.sub(r'\s+', ' ', s).strip()
    s = s.replace(',', '.')
    s = re.sub(r'\s*\.\s*', '.', s)

    s = re.sub(r'^(?:%?\s*)([MQI])\s*([0-9]+(?:\.[0-9]+)?)$', r'%\1\2', s, flags=re.IGNORECASE)
    s = re.sub(r'^%1([0-9](?:\.[0-9]+)?)$', r'%I\1', s)
    s = re.sub(r'^[\s]*([MQI])[\s]+([0-9]+(?:\.[0-9]+)?)$', r'%\1\2', s, flags=re.IGNORECASE)
    s = re.sub(r'^%([A-Z])0+([0-9]+(?:\.[0-9]+)?)$', r'%\1\2', s, flags=re.IGNORECASE)

    m = re.match(r'^\s*%([A-Z])\D*([0-9]*\.[0-9]+|[0-9]+)\s*$', s, flags=re.IGNORECASE)
    if m:
        letter = m.group(1).upper()
        numpart = m.group(2)
        if numpart.startswith('.'):
            numpart = '0' + numpart
        s = f"%{letter}{numpart}"

    m2 = re.match(r'^%([0-9]{2,})(\.\d+)?$', s)
    if m2:
        digits = m2.group(1)
        rest = m2.group(2) or ''
        if digits.startswith('1') and len(digits) >= 2:
            new_tag = f"%I{digits[1:]}{rest}"
            if re.match(r'^%[A-Z]\d+(?:\.\d+)?$', new_tag, re.IGNORECASE):
                s = new_tag

    s = re.sub(r'^%D(\d+)$', r'%DB\1', s, flags=re.IGNORECASE)
    s = re.sub(r'^%D8(\d+)$', r'%DB\1', s, flags=re.IGNORECASE)
    s = re.sub(r'^%08(\d+)$', r'%DB\1', s, flags=re.IGNORECASE)
    s = re.sub(r'^%0B(\d+)$', r'%DB\1', s, flags=re.IGNORECASE)
    s = re.sub(r'^%[O0]B(\d+)$', r'%DB\1', s, flags=re.IGNORECASE)

    return s.strip().strip('"').strip("'")

# Aumenta a resolução da imagem para melhorar a legibilidade do OCR
def upscale_image(img, factor=2):
    if factor <= 1:
        return img
    return img.resize((img.width * factor, img.height * factor), Image.LANCZOS)

# Aplica pré-processamentos (cinza, contraste, nitidez, binarização, dilatação) e gera variações
def preprocess_image(img, upscale_factor=2):
    img_up = upscale_image(img, factor=upscale_factor)
    gray = ImageOps.grayscale(img_up)
    gray = ImageEnhance.Contrast(gray).enhance(2.2)
    gray = gray.filter(ImageFilter.SHARPEN)
    bw = gray.point(lambda x: 0 if x < 140 else 255, '1').convert("L")
    bw_dilated = bw.filter(ImageFilter.MaxFilter(7))
    return {"up": img_up, "gray": gray, "bw": bw, "bw_dilated": bw_dilated}

# Executa OCR em múltiplas variações e unifica resultados mantendo maior confiança
def ocr_multi_pass(img, langs="por+eng", upscale_factor=2):
    variants = preprocess_image(img, upscale_factor=upscale_factor)
    results = {}
    passes = [
        (variants['gray'], f"--psm 6 -l {langs}"),
        (variants['bw'],   f"--psm 6 -l {langs}"),
        (variants['up'],   f"--psm 6 -l {langs}")
    ]
    
    for img_pass, cfg in passes:
        try:
            data = pytesseract.image_to_data(img_pass, output_type=pytesseract.Output.DICT, config=cfg)
        except Exception:
            continue
        
        n = len(data.get('text', []))
        for i in range(n):
            raw = (data['text'][i] or "").strip()
            if not raw:
                continue
            txt = corrigir_erros_ocr(raw)
            if not txt:
                continue
            
            try:
                l = int(data['left'][i])
                t = int(data['top'][i])
                w = int(data['width'][i])
                h = int(data['height'][i])
                conf = float(data.get('conf', [0]*n)[i] or 0)
            except Exception:
                continue
            
            # Desfaz o upscale das coordenadas
            l = int(l / upscale_factor)
            t = int(t / upscale_factor)
            w = int(max(1, w / upscale_factor))
            h = int(max(1, h / upscale_factor))
            
            # Cria chave texto@posição discretizada para mesclar duplicatas entre passagens
            key = f"{txt}@{l//4},{t//4}"
            prev = results.get(key)
            if prev is None or conf > prev['conf']:
                results[key] = {'text': txt, 'x': l, 'y': t, 'w': w, 'h': h, 'conf': conf}
    
    return list(results.values())

# Normaliza e filtra TAGs detectadas; mescla por posição e confiança
def normalize_tags(elems, tol_x=12, tol_y=8):
    if not elems:
        return []
    
    for e in elems:
        e['text'] = corrigir_erros_ocr(e.get('text', '')).strip()
    
    raw_tags = [e for e in elems if isinstance(e.get('text'), str) and e['text'].startswith('%')]
    
    kept = []
    for t in raw_tags:
        tx = t.get('text', '').replace(',', '.').strip().strip('.')
        t_x = int(t.get('x', 0))
        t_y = int(t.get('y', 0))
        t_w = int(t.get('w', 0) or 0)
        t_h = int(t.get('h', 0) or 0)
        t_conf = float(t.get('conf', 0) or 0)
        
        merged = False
        for k in kept:
            if k['text'] == tx and abs(k['x'] - t_x) <= tol_x and abs(k['y'] - t_y) <= tol_y:
                if t_conf > float(k.get('conf', 0) or 0):
                    k.update({'x': t_x, 'y': t_y, 'w': t_w, 'h': t_h, 'conf': t_conf})
                merged = True
                break
        
        if not merged:
            kept.append({'text': tx, 'x': t_x, 'y': t_y, 'w': t_w, 'h': t_h, 'conf': t_conf})
    
    kept.sort(key=lambda e: e['x'])
    return kept

# Remove duplicatas por posição, preservando o item com maior confiabilidade
def remove_duplicates_by_position(tags, tol_x=DEFAULT_REMOVE_TOL_X, tol_y=DEFAULT_REMOVE_TOL_Y):
    if not tags:
        return [], []
    
    kept, removed = [], []
    
    for t in sorted(tags, key=lambda e: (int(e.get('x', 0)), int(e.get('y', 0)), -float(e.get('conf', 0) or 0))):
        tx, ty = int(t.get('x', 0)), int(t.get('y', 0))
        conf = float(t.get('conf', 0) or 0)
        
        found = None
        for k in kept:
            kx, ky = int(k.get('x', 0)), int(k.get('y', 0))
            if abs(kx - tx) <= tol_x and abs(ky - ty) <= tol_y:
                found = k
                break
        
        if not found:
            kept.append(t.copy())
        else:
            if conf > float(found.get('conf', 0) or 0):
                kept.remove(found)
                removed.append(found)
                kept.append(t.copy())
            else:
                removed.append(t.copy())
    
    kept.sort(key=lambda e: int(e.get('x', 0)))
    return kept, removed

# Marca como bobina a TAG com maior X e todas as TAGs dentro da margem de erro
def mark_coils_by_max_x(tags, x_margin=COIL_X_MARGIN):
    if not tags:
        return tags, 0
    
    max_x = max(int(t.get('x', 0)) for t in tags)
    x_threshold = max(0, max_x - x_margin)
    
    for t in tags:
        x = int(t.get('x', 0))
        t['is_coil'] = bool(x >= x_threshold)
    
    return tags, x_threshold

# Orquestra o pipeline: OCR multi-pass, normaliza, deduplica, marca bobinas e salva artefatos
def detect_tags(image_path, langs='por+eng', upscale_factor=2, save_vis=True, save_json=True):
    base = os.path.splitext(os.path.basename(image_path))[0]
    img = Image.open(image_path).convert('RGB')
    
    W, H = img.size

    # OCR multi-pass
    ocr_raw = ocr_multi_pass(img, langs=langs, upscale_factor=upscale_factor)

    # Normalização das TAGs
    tags_objs = normalize_tags(ocr_raw)

    # Deduplicação por posição
    tags_final, _removed = remove_duplicates_by_position(tags_objs)

    # Marca bobinas
    tags_final, x_thr = mark_coils_by_max_x(tags_final, x_margin=COIL_X_MARGIN)

    # Salva visualização anotada
    vis_path = None
    if save_vis:
        vis = img.copy()
        draw = ImageDraw.Draw(vis)
        try:
            font = ImageFont.load_default()
        except Exception:
            font = None

        draw.rectangle([x_thr, 0, W - 1, H - 1], outline=(0, 200, 255), width=2)

        for t in tags_final:
            lx, ty = t['x'], t['y']
            rx, by = t['x'] + t['w'], t['y'] + t['h']
            color = (0, 170, 0) if t.get('is_coil') else (255, 0, 0)
            draw.rectangle([lx, ty, rx, by], outline=color, width=2)
            if font:
                draw.text((lx, max(0, ty - 12)), t['text'], fill=color, font=font)

        vis_path = os.path.join(DEBUG_DIR, f"{base}_tags_vis.png")
        vis.save(vis_path)

    # Salva JSON
    json_path = None
    if save_json:
        json_path = os.path.join(TAGS_OUT_DIR, f"{base}_tags_info.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(tags_final, f, ensure_ascii=False, indent=2)

    return tags_final, vis_path, json_path

# ---- MAIN ----

def main():
    images = [
        os.path.join(INPUT_DIR, f)
        for f in os.listdir(INPUT_DIR)
        if f.lower().endswith((".png", ".jpg", ".jpeg", ".tif", ".tiff"))
    ]
    
    if not images:
        print(f"No images found in: {INPUT_DIR}")
        return

    print(f"Processing {len(images)} images...\n")
    for img_path in images:
        tags, vis, jpath = detect_tags(img_path, langs="por+eng", upscale_factor=2, save_vis=True, save_json=True)
        print(f"- {os.path.basename(img_path)}: {len(tags)} tags (coils marked) -> vis: {os.path.basename(vis) if vis else 'none'}")

if __name__ == "__main__":
    main()
