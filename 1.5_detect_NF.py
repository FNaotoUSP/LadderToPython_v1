# 1.5_detect_NF.py
# Detecta contatos NF/NA analisando pixels abaixo das TAGs e aplica NOT() nos itens NF

import json, os
from pathlib import Path
from PIL import Image, ImageOps, ImageDraw

# ---- DIRETORIOS ----
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_FIGS_DIR = os.path.join(BASE_DIR, "02_figures")
TAGS_OUT_DIR   = os.path.join(BASE_DIR, "03_tags")
DEBUG_DIR      = os.path.join(BASE_DIR, "99_debug")

# ---- PARAMETROS ----
BW_THRESH = 140                    # Limiar de binarização (0-255)
Y_OFFSET = 30                      # Distância em pixels abaixo da TAG para analisar
CONTACT_HALF_H = 9                 # Meia-altura da caixa de análise (±9px)
CONTACT_HALF_W_NARROW = 2          # Meia-largura da caixa (±2px ou ±1px se strict)
USE_STRICT_NARROW_BOX = True       # Se True, usa largura de ±1px
FRAC_THR = 0.14                    # Fração mínima de pixels pretos para considerar NF
CONSEC_THR = 3                     # Número mínimo de pixels pretos consecutivos para NF

# Binariza a imagem (preto e branco) usando limiar fixo
def binarize_image(img, thresh=BW_THRESH):
    gray = ImageOps.grayscale(img)
    bw = gray.point(lambda p: 0 if p < thresh else 255, '1').convert('L')
    return bw

# Analisa uma caixa fixa na região do contato e decide se é NF (normally closed) ou NA
def analyze_contact_region(bw_img, cx, start_y, y_offset, contact_half_h, half_w, frac_thr, consec_thr):
    W, H = bw_img.size
    wire_y = min(H - 1, start_y + y_offset)
    lx = max(0, cx - half_w)
    rx = min(W - 1, cx + half_w)
    top = max(0, wire_y - contact_half_h)
    bottom = min(H - 1, wire_y + contact_half_h)
    pix = bw_img.load()

    black = 0
    total = 0
    max_consec = 0
    
    # Percorre a região e conta pixels pretos
    for x in range(lx, rx + 1):
        consec = 0
        for y in range(top, bottom + 1):
            total += 1
            if pix[x, y] < 128:
                black += 1
                consec += 1
                max_consec = max(max_consec, consec)
            else:
                consec = 0
    
    # Calcula fração de pixels pretos e decide se é NF
    frac = (black / total) if total else 0.0
    is_nf = (frac >= frac_thr) or (max_consec >= consec_thr)
    
    metrics = {
        'lx': lx, 'rx': rx, 'top': top, 'bottom': bottom,
        'frac': frac, 'maxc': max_consec, 'black': black, 'total': total, 'wire_y': wire_y
    }
    return is_nf, metrics

# Percorre cada TAG e decide NF/NA; pula bobinas; gera visualização de depuração
def detect_nf_and_generate_debug(image_path, tags_list):
    img = Image.open(image_path).convert("RGB")
    bw = binarize_image(img)
    
    vis = img.copy()
    draw = ImageDraw.Draw(vis)
    
    is_nf_list = []
    metrics_list = []
    
    for tag in tags_list:
        # Pula bobinas por flag
        if tag.get("is_coil", False):
            is_nf_list.append(False)
            metrics_list.append({"reason": "coil_skip"})
            continue
        
        # Calcula posição central e início da região de análise
        cx = int(tag['x'] + tag['w'] / 2)
        start_y = int(tag['y'] + tag['h'])
        y_offset_eff = int(Y_OFFSET + max(0, tag['h'] * 0.2))
        half_w = 1 if USE_STRICT_NARROW_BOX else CONTACT_HALF_W_NARROW
        
        # Analisa região abaixo da TAG
        is_nf, metrics = analyze_contact_region(
            bw, cx, start_y, y_offset_eff, CONTACT_HALF_H, half_w, FRAC_THR, CONSEC_THR
        )
        is_nf_list.append(is_nf)
        metrics_list.append(metrics)
        
        # Desenha a caixa do contato para depuração (sem texto)
        lx, rx, top, bottom = metrics['lx'], metrics['rx'], metrics['top'], metrics['bottom']
        draw.rectangle([lx, top, rx, bottom], outline=(255, 0, 0), width=2)
        draw.line([(cx, top), (cx, bottom)], fill=(255, 0, 0), width=1)
    
    # Salva a visualização
    Path(DEBUG_DIR).mkdir(parents=True, exist_ok=True)
    vis_path = Path(DEBUG_DIR) / f"{image_path.stem}_nf_vis.png"
    vis.save(vis_path)
    
    return is_nf_list, metrics_list, str(vis_path)

# Aplica NOT() apenas nas ocorrências marcadas como NF, preservando os demais campos
def apply_not_to_nf_tags(tags_list, is_nf_list):
    out = []
    for tag, is_nf in zip(tags_list, is_nf_list):
        t = dict(tag)
        # Se for bobina, nunca aplica NOT
        if not tag.get("is_coil", False) and is_nf:
            t["text"] = f"NOT({tag['text']})"
        out.append(t)
    return out

# Escreve arquivos de saída: JSON de debug consolidado e JSON de TAGs transformadas
def save_outputs(base_stem, image_path, is_nf_list, metrics_list, vis_path, tags_with_nf):
    tags_out_dir = Path(TAGS_OUT_DIR)
    tags_out_dir.mkdir(parents=True, exist_ok=True)
    
    # nf.json (debug consolidado por ocorrência)
    nf_json_path = tags_out_dir / f"{base_stem}_nf.json"
    nf_json = {
        "image": str(image_path),
        "per_occurrence_is_nf": is_nf_list,
        "per_occurrence_metrics": metrics_list,
        "vis": vis_path
    }
    nf_json_path.write_text(json.dumps(nf_json, ensure_ascii=False, indent=2), encoding="utf-8")
    
    # tags_with_nf.json (lista simples)
    out_path = tags_out_dir / f"{base_stem}_tags_with_nf.json"
    out_path.write_text(json.dumps(tags_with_nf, ensure_ascii=False, indent=2), encoding="utf-8")
    
    return str(nf_json_path), str(out_path)

# Processa um arquivo *_tags_info.json, detecta NF/NA e grava saídas
def process_tags_info_file(json_path):
    json_path = Path(json_path)
    
    # Carrega JSON
    data = json.loads(json_path.read_text(encoding="utf-8"))
    
    # Extrai lista de TAGs (suporta formatos simples)
    if isinstance(data, list):
        tags_list = data
    elif isinstance(data, dict):
        tags_list = data.get("tags_left") or data.get("tags_left_objs") or data.get("tags") or []
        if isinstance(tags_list, dict) and "items" in tags_list:
            tags_list = tags_list["items"]
    else:
        raise ValueError(f"Formato não reconhecido: {json_path.name}")
    
    # Encontra imagem correspondente
    base_stem = json_path.stem.replace("_tags_info", "")
    input_figs_dir = Path(INPUT_FIGS_DIR)
    image_path = None
    for ext in [".png", ".jpg", ".jpeg"]:
        candidate = input_figs_dir / f"{base_stem}{ext}"
        if candidate.exists():
            image_path = candidate
            break
    
    if not image_path:
        raise FileNotFoundError(f"Imagem não encontrada para {json_path.name}")
    
    # Detecta NF/NA
    is_nf_list, metrics_list, vis_path = detect_nf_and_generate_debug(image_path, tags_list)
    
    # Aplica NOT()
    tags_with_nf = apply_not_to_nf_tags(tags_list, is_nf_list)
    
    # Salva saídas
    nf_json, tags_json = save_outputs(base_stem, image_path, is_nf_list, metrics_list, vis_path, tags_with_nf)
    
    print(f"[OK] {json_path.name}")
    print(f"     NF debug: {nf_json}")
    print(f"     Tags NF:  {tags_json}")
    print(f"     Visual:   {vis_path}")

# ---- MAIN ----

def main():
    import argparse
    ap = argparse.ArgumentParser(description="Detecta contatos NF/NA e aplica NOT() em NF")
    ap.add_argument("--tags", "-t", help="Arquivo *_tags_info.json específico")
    ap.add_argument("--tags_dir", help="Diretório com *_tags_info.json (padrão: TAGS_OUT_DIR)")
    args = ap.parse_args()
    
    tags_dir = Path(args.tags_dir) if args.tags_dir else Path(TAGS_OUT_DIR)
    tags_dir.mkdir(parents=True, exist_ok=True)
    
    if args.tags:
        json_path = Path(args.tags)
        if not json_path.exists():
            raise FileNotFoundError(json_path)
        process_tags_info_file(json_path)
        return
    
    files = sorted(tags_dir.glob("*_tags_info.json"))
    if not files:
        print(f"Nenhum *_tags_info.json encontrado em {tags_dir}")
        return
    
    for f in files:
        try:
            process_tags_info_file(f)
        except Exception as e:
            print(f"[ERRO] {f.name}: {e}")

if __name__ == "__main__":
    main()