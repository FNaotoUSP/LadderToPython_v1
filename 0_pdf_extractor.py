# 0_pdf_extractor.py
# Extrai figuras das Networks do relatório do TIA Portal em pdf
# Versão modificada usando pdfplumber (MIT) + pdf2image (MIT) no lugar de PyMuPDF (AGPL)

import os, re, tempfile, shutil, json
from PIL import Image
import pdfplumber
from pdf2image import convert_from_path

# ---- CONFIGURAÇÕES ----
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR = os.path.join(BASE_DIR, "01_pdf_input")
OUTPUT_DIR = os.path.join(BASE_DIR, "02_figures")

ZOOM = 2.0    
MARGIN_TOP = 8    
MARGIN_BOTTOM = 0    
CROP_RIGHT_PX = 140   

# Padrões de busca para identificar blocos
NETWORK_RE = re.compile(r'\bNetwork\s*\d+\b', re.IGNORECASE)
SYMBOL_RE = re.compile(r'\bSymbol\b', re.IGNORECASE)

# Cria diretório de saída se não existir
def create_output_directory(path):
    os.makedirs(path, exist_ok=True)

# Extrai blocos de texto da página e retorna ordenados por posição vertical
def extract_text_blocks(page):
    words = page.extract_words(x_tolerance=3, y_tolerance=3)
    
    # Agrupa palavras em linhas (mesma altura aproximada)
    lines = {}
    for word in words:
        y_key = round(word['top'], 1)  # Agrupa por posição vertical
        if y_key not in lines:
            lines[y_key] = []
        lines[y_key].append(word)
    
    # Cria blocos a partir das linhas
    blocks = []
    for y_key in sorted(lines.keys()):
        line_words = sorted(lines[y_key], key=lambda w: w['x0'])
        if not line_words:
            continue
        
        x0 = min(w['x0'] for w in line_words)
        y0 = min(w['top'] for w in line_words)
        x1 = max(w['x1'] for w in line_words)
        y1 = max(w['bottom'] for w in line_words)
        text = ' '.join(w['text'] for w in line_words)
        
        blocks.append((x0, y0, x1, y1, text.strip()))
    
    return blocks

# Extrai blocos Network de um PDF e salva como imagens PNG
def extract_network_blocks(pdf_path, output_dir, zoom=2.0):
    create_output_directory(output_dir)
    results = []
    
    # Renderiza todas as páginas do PDF como imagens (DPI = 72 * zoom)
    dpi = int(72 * zoom)
    images = convert_from_path(pdf_path, dpi=dpi)
    
    # Abre PDF com pdfplumber para extração de texto
    with pdfplumber.open(pdf_path) as pdf:
        # Processa cada página do PDF
        for page_index, page in enumerate(pdf.pages):
            # Extrai blocos de texto
            blocks = extract_text_blocks(page)
            network_blocks = [b for b in blocks if NETWORK_RE.search(b[4])]
            symbol_blocks = [b for b in blocks if SYMBOL_RE.search(b[4])]

            # Se não encontrar blocos Network, pula para próxima página
            if not network_blocks:
                continue

            # Obtém imagem renderizada da página
            image = images[page_index]
            page_width_px = image.width
            page_height_px = image.height
            
            # Dimensões da página em pontos (pdfplumber usa pontos)
            page_width_pt = page.width
            page_height_pt = page.height

            # Processa cada bloco Network encontrado
            for network_index, network_block in enumerate(network_blocks):
                nx0, ny0, nx1, ny1, network_text = network_block
                
                # Determina limite inferior do bloco
                bottom_y = page_height_pt
                for symbol_block in symbol_blocks:
                    sx0, sy0, sx1, sy1, symbol_text = symbol_block
                    if sy0 > ny0:
                        bottom_y = sy0
                        break
                
                # Se não encontrou Symbol, tenta usar próximo Network
                if bottom_y == page_height_pt and len(network_blocks) > network_index + 1:
                    bottom_y = network_blocks[network_index + 1][1]

                # Converte coordenadas PDF (pontos) para pixels
                px_x0 = max(0, int(round(nx0 * zoom)))
                page_right_px = int(round(page_width_pt * zoom))
                px_x1 = page_right_px - CROP_RIGHT_PX
                px_x1 = min(page_width_px, int(px_x1))
                px_x1 = max(px_x1, px_x0 + 4)
                px_y0 = max(0, int(round(ny0 * zoom)) - MARGIN_TOP)
                px_y1 = min(page_height_px, int(round(bottom_y * zoom)) + MARGIN_BOTTOM)

                # Recorta e salva imagem
                crop = image.crop((px_x0, px_y0, px_x1, px_y1))
                safe_label = re.sub(r'[^\w\-_\.]', '_', network_text.strip())[:60]
                filename = f"page{page_index+1:03d}_network{network_index+1:02d}_{safe_label}.png"
                output_path = os.path.join(output_dir, filename)
                crop.save(output_path, format="PNG")

                # Armazena informações do bloco extraído
                results.append({
                    "page": page_index,
                    "network_index_on_page": network_index,
                    "network_text": network_text,
                    "pdf_bbox": (nx0, ny0, nx1, ny1),
                    "pixel_bbox": (px_x0, px_y0, px_x1, px_y1),
                    "file": output_path
                })

    return results

if __name__ == "__main__":
    # Localiza PDF para processar
    pdf_files = [os.path.join(INPUT_DIR, f) for f in os.listdir(INPUT_DIR) if f.lower().endswith(".pdf")]

    # Processa PDF
    pdf_path = pdf_files[0]
    print(f"Processando PDF: {pdf_path}")
    extracted_blocks = extract_network_blocks(pdf_path, OUTPUT_DIR, zoom=ZOOM)

    # Salva lista de arquivos extraídos
    image_list = [block["file"] for block in extracted_blocks]
    list_path = os.path.join(OUTPUT_DIR, "extracted_list.json")
    with open(list_path, "w", encoding="utf-8") as f:
        json.dump(image_list, f, indent=2, ensure_ascii=False)
    
    print(f"Lista de arquivos salva em: {list_path}")