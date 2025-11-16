# 4_group_blocks.py
# Agrupa blocos alternando operações OR e AND até restar 1 bloco ou estabilizar.
# Remove blocos vazios após algumas iterações. OR agrupa pilhas no mesmo ramal (largura similar,
# sobreposição X, mesma vertical). AND pareia blocos próximos com âncora por vertical comum.

import os, json, glob, math
from collections import deque
from typing import List, Dict, Any, Tuple, Optional

# ---- DIRETORIOS ----
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEBUG_DIR = os.path.join(BASE_DIR, "99_debug")
LOGS_DIR  = os.path.join(DEBUG_DIR, "16_logs")
FINAL_DIR = os.path.join(DEBUG_DIR, "17_final")

# ---- PARAMETROS ----
AND_GROUPS_SUFFIX_JSON = "__14_groups_AND.json"
VERTICALS_SUFFIX_JSON = "__04_vert_lenFiltered.json"

MAX_ALTERNATING_ITERS = 20    # Máximo de iterações OR/AND
REMOVE_EMPTY_AFTER_K = 2      # Remove blocos vazios após K operações
FINAL_COLLAPSE_ALL = False    # Sem colapso artificial no final

# ---- OR ----
WIDTH_REL_TOL = 0.10    # Tolerância relativa de largura
WIDTH_ABS_TOL = 12      # Tolerância absoluta de largura (px)
MIN_X_OVERLAP_RATIO = 0.40    # Sobreposição horizontal mínima
PROFILE_BINS = 10       # Bins para perfil de ramificação
PROFILE_POS_TOL = 1     # Tolerância de posição no perfil
REQUIRE_SAME_TOUCH = True    # Exige mesmo toque no barramento direito
OR_ANCHOR_TOPMOST = True     # Ancora retângulo OR no bloco mais alto
VERTICAL_X_HALO = 0     # Halo horizontal para cruzamento de verticais (px)

# ---- AND ----
WX = 1.0    # Peso da distância horizontal
WY = 2.0    # Peso da distância vertical
MAX_DX = 9999    # Distância horizontal máxima
MAX_DY = 9999    # Distância vertical máxima
MIN_V_OVERLAP_RATIO = 0.40
MIN_V_OVERLAP_RATIO_FOR_EMPTY = 0.80  # Para blocos vazios, exigir mais sobreposição
ENABLE_INTERMEDIATE_AND_BY_VERTICAL = True  # Permite AND por vertical comum
VERT_GAP_TOL = 12    # Tolerância de gap vertical (px)

# Cria diretório de logs se não existir
def ensure_logs_dir():
    os.makedirs(LOGS_DIR, exist_ok=True)

# Cria diretório final se não existir
def ensure_final_dir():
    os.makedirs(FINAL_DIR, exist_ok=True)

# Carrega arquivo JSON 
def load_json(path):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

# Salva objeto em arquivo JSON
def save_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

# Salva lista de strings em arquivo TXT
def save_txt(path, lines: List[str]):
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

# Retorna largura de um retângulo [x1,y1,x2,y2]
def rect_width(r):
    return r[2] - r[0] + 1

# Retorna altura de um retângulo [x1,y1,x2,y2]
def rect_height(r):
    return r[3] - r[1] + 1

# Retorna centro (cx, cy) de um retângulo [x1,y1,x2,y2]
def rect_center(r):
    return ((r[0] + r[2]) / 2.0, (r[1] + r[3]) / 2.0)

# Retorna união (bounding box) de uma lista de retângulos
def rect_union(rects: List[List[int]]):
    if not rects:
        return [0, 0, 0, 0]
    xs1 = [r[0] for r in rects]
    ys1 = [r[1] for r in rects]
    xs2 = [r[2] for r in rects]
    ys2 = [r[3] for r in rects]
    return [min(xs1), min(ys1), max(xs2), max(ys2)]

# Retorna sobreposição vertical (em pixels) entre dois retângulos
def v_overlap(a, b):
    top = max(a[1], b[1])
    bot = min(a[3], b[3])
    return max(0, bot - top + 1)

# Retorna razão de sobreposição vertical entre dois retângulos
def v_overlap_ratio(a, b):
    ov = v_overlap(a, b)
    ha = rect_height(a)
    hb = rect_height(b)
    base = min(ha, hb)
    return 0.0 if base <= 0 else ov / float(base)

# Retorna sobreposição horizontal (em pixels) entre dois retângulos
def x_overlap(a, b):
    left = max(a[0], b[0])
    right = min(a[2], b[2])
    return max(0, right - left + 1)

# Retorna razão de sobreposição horizontal entre dois retângulos
def x_overlap_ratio(a, b):
    ov = x_overlap(a, b)
    base = min(rect_width(a), rect_width(b))
    return 0.0 if base <= 0 else ov / float(base)

# Verifica se duas larguras são similares dentro das tolerâncias
def similar_width(w_ref, w_test, rel_tol=WIDTH_REL_TOL, abs_tol=WIDTH_ABS_TOL):
    if w_ref <= 0:
        return abs(w_test - w_ref) <= abs_tol
    rel_diff = abs(w_test - w_ref) / float(w_ref)
    return (rel_diff <= rel_tol) or (abs(w_test - w_ref) <= abs_tol)

# Constrói expressão lógica a partir de um bloco
def build_block_expr(b: Dict[str, Any]) -> str:
    expr = (b.get("expression") or "").strip()
    if expr:
        return expr
    tags = b.get("tags", [])
    names = [str(t.get("text", "")).strip() for t in tags if str(t.get("text", "")).strip()]
    if not names:
        return ""
    names = sorted(set(names))
    return names[0] if len(names) == 1 else "AND(" + ", ".join(names) + ")"

# Verifica se um bloco tem expressão não-vazia
def has_expr(b):
    return bool((b.get("expression") or "").strip())

# Retorna coordenada Y central de um bloco
def get_cy(b):
    try:
        if b.get("cy") is not None:
            return float(b["cy"])
    except Exception:
        pass
    r = b.get("rect", [0, 0, 0, 0])
    return (r[1] + r[3]) / 2.0

# Computa assinatura de ramificação de um bloco (contagem, perfil, toque direito, cy, largura)
def compute_branch_signature(b, bins=PROFILE_BINS):
    r = b["rect"]
    x1, x2 = r[0], r[2]
    w = max(1, rect_width(r))
    touches_right = bool(b.get("touches_right_bus", False))
    cy = get_cy(b)
    return {
        "count": 0,
        "profile": (),
        "touch_right": touches_right,
        "cy": cy,
        "width": w,
    }

# ---- FUNÇÕES DE VERTICAIS ----

# Carrega verticais de um arquivo JSON para uma imagem-base
def load_verticals_for_base(base: str) -> List[Dict[str, int]]:
    data = load_json(os.path.join(DEBUG_DIR, f"{base}{VERTICALS_SUFFIX_JSON}"))
    if not data or "verticals" not in data:
        return []
    out = []
    for v in data["verticals"]:
        try:
            out.append({"id": int(v["id"]), "x": int(v["x"]), "y1": int(v["y1"]), "y2": int(v["y2"])})
        except Exception:
            continue
    return out

# Verifica se uma vertical cruza um retângulo (com halo horizontal)
def vertical_crosses_rect(v, r, halo=VERTICAL_X_HALO):
    x1, y1, x2, y2 = r
    if not (x1 - halo <= v["x"] <= x2 + halo):
        return False
    top = max(y1, v["y1"])
    bot = min(y2, v["y2"])
    return (bot - top + 1) > 0

# Verifica se dois blocos compartilham alguma linha vertical
def share_vertical_line(A, B, verticals, halo=VERTICAL_X_HALO):
    if not verticals:
        return False
    ra, rb = A["rect"], B["rect"]
    for v in verticals:
        if vertical_crosses_rect(v, ra, halo) and vertical_crosses_rect(v, rb, halo):
            return True
    return False

# Retorna lista de verticais comuns entre dois blocos
def common_verticals(A, B, verticals, halo=VERTICAL_X_HALO):
    if not verticals:
        return []
    ra, rb = A["rect"], B["rect"]
    out = []
    for v in verticals:
        if vertical_crosses_rect(v, ra, halo) and vertical_crosses_rect(v, rb, halo):
            out.append(v)
    return out

# ---- AGRUPAMENTO OR (PILHAS) ----

# Verifica se dois blocos podem ser agrupados por OR (pilhas no mesmo ramal)
def can_or_together(A, B, verticals):
    sa = compute_branch_signature(A)
    sb = compute_branch_signature(B)
    if not similar_width(sa["width"], sb["width"]):
        return False
    if x_overlap_ratio(A["rect"], B["rect"]) < MIN_X_OVERLAP_RATIO:
        return False
    if not share_vertical_line(A, B, verticals):
        return False
    if REQUIRE_SAME_TOUCH and (sa["touch_right"] != sb["touch_right"]):
        return False
    return True

# Ajusta retângulo OR: ancora no bloco mais alto se OR_ANCHOR_TOPMOST=True
def or_group_rect_adjusted(g: List[Dict[str, Any]]) -> Tuple[List[int], List[int]]:
    rects = [b["rect"] for b in g]
    union_rect_full = rect_union(rects)
    if not OR_ANCHOR_TOPMOST:
        return union_rect_full, union_rect_full
    top_b = min(g, key=lambda b: b["rect"][1])
    h_top = rect_height(top_b["rect"])
    x1 = min(r[0] for r in rects)
    x2 = max(r[2] for r in rects)
    y1 = top_b["rect"][1]
    y2 = y1 + h_top - 1
    return union_rect_full, [x1, y1, x2, y2]

# Agrupa blocos por OR usando componentes conectados (BFS)
def group_by_OR_with_intersections(blocks, verticals):
    n = len(blocks)
    used = [False] * n
    groups = []
    for i in range(n):
        if used[i]:
            continue
        used[i] = True
        group_idx = [i]
        q = deque([i])
        while q:
            u = q.popleft()
            for v in range(n):
                if used[v]:
                    continue
                if can_or_together(blocks[u], blocks[v], verticals):
                    used[v] = True
                    group_idx.append(v)
                    q.append(v)
        groups.append([blocks[k] for k in group_idx])

    new_blocks = []
    groups_debug = []
    for g in groups:
        union_full, or_rect = or_group_rect_adjusted(g)
        exprs_all = []
        for b in g:
            e = (build_block_expr(b) or "").strip()
            if e:
                exprs_all.append(e)
        if not exprs_all:
            or_expr = ""
        elif len(exprs_all) == 1:
            or_expr = exprs_all[0]
        else:
            or_expr = "OR(" + ", ".join(exprs_all) + ")"

        touches_right = any(bool(b.get("touches_right_bus", False)) for b in g)
        cy_mean = sum(get_cy(b) for b in g) / float(len(g))
        new_blocks.append({
            "rect": or_rect,
            "rect_union_full": union_full,
            "tags": [],
            "expression": or_expr,
            "touches_right_bus": touches_right,
            "cy": cy_mean
        })
        groups_debug.append({
            "union_rect_full": union_full,
            "or_rect": or_rect,
            "members": [
                {
                    "rect": b["rect"],
                    "expr": build_block_expr(b) or "",
                    "touches_right_bus": bool(b.get("touches_right_bus", False)),
                    "cy": get_cy(b),
                    "width": rect_width(b["rect"])
                } for b in g
            ],
            "or_expression": or_expr
        })
    return new_blocks, groups_debug

# ---- PAREAMENTO AND ----

# Calcula distância ponderada entre dois retângulos para pareamento AND
def pair_distance(a_rect, b_rect):
    ax, ay = rect_center(a_rect)
    bx, by = rect_center(b_rect)
    dx, dy = abs(bx - ax), abs(by - ay)
    if dx > MAX_DX or dy > MAX_DY:
        return float("inf")
    if v_overlap_ratio(a_rect, b_rect) < MIN_V_OVERLAP_RATIO:
        return float("inf")
    return math.sqrt((WX * dx) ** 2 + (WY * dy) ** 2)

# Calcula gap vertical mínimo ao longo de verticais comuns entre dois blocos
def vertical_gap_along_common(A, B, verticals) -> Optional[int]:
    commons = common_verticals(A, B, verticals)
    if not commons:
        return None
    gaps = []
    for v in commons:
        ay1, ay2 = A["rect"][1], A["rect"][3]
        by1, by2 = B["rect"][1], B["rect"][3]
        if ay2 < by1:
            gap = by1 - ay2 - 1
        elif by2 < ay1:
            gap = ay1 - by2 - 1
        else:
            gap = 0
        gaps.append(gap)
    return min(gaps) if gaps else None

# Pareia blocos por AND (proximidade + vertical comum com gap curto)
def pair_blocks_AND(blocks, verticals):
    if not blocks:
        return [], []
    ord_list = []
    for idx, b in enumerate(blocks):
        cx, cy = rect_center(b["rect"])
        ord_list.append((idx, cy, cx, b))
    ord_list.sort(key=lambda t: (t[1], t[2], t[0]))

    used = set()
    pairs = []
    singles = []
    for i in range(len(ord_list)):
        if ord_list[i][0] in used:
            continue
        best_j = -1
        best_d = float("inf")
        bi = ord_list[i][3]
        ri = bi["rect"]
        for j in range(i + 1, len(ord_list)):
            if ord_list[j][0] in used:
                continue
            bj = ord_list[j][3]
            rj = bj["rect"]
            ov_ratio = v_overlap_ratio(ri, rj)
            if (not has_expr(bi) or not has_expr(bj)) and ov_ratio < MIN_V_OVERLAP_RATIO_FOR_EMPTY:
                continue

            ok_pair = False
            if ENABLE_INTERMEDIATE_AND_BY_VERTICAL:
                gap = vertical_gap_along_common(bi, bj, verticals)
                if gap is not None and gap <= VERT_GAP_TOL:
                    ok_pair = True
                else:
                    ok_pair = True
            else:
                ok_pair = True

            if not ok_pair:
                continue
            d = pair_distance(ri, rj)
            if d < best_d:
                best_d = d
                best_j = j

        if best_j != -1 and best_d < float("inf"):
            used.add(ord_list[i][0])
            used.add(ord_list[best_j][0])
            pairs.append((ord_list[i][3], ord_list[best_j][3], best_d))
        else:
            singles.append(ord_list[i][3])

    if not pairs:
        return None, []

    new_blocks = []
    pairs_debug = []
    for (A, B, dist) in pairs:
        exprA = (build_block_expr(A) or "").strip()
        exprB = (build_block_expr(B) or "").strip()
        if not exprA and not exprB:
            expr = ""
        elif not exprA:
            expr = exprB
        elif not exprB:
            expr = exprA
        else:
            expr = f"AND({exprA}, {exprB})"
        urect = rect_union([A["rect"], B["rect"]])
        touches_right = bool(A.get("touches_right_bus", False) or B.get("touches_right_bus", False))
        cy_mean = (get_cy(A) + get_cy(B)) / 2.0
        new_blocks.append({
            "rect": urect,
            "tags": [],
            "expression": expr,
            "touches_right_bus": touches_right,
            "cy": cy_mean
        })
        pairs_debug.append({
            "A": {"rect": A["rect"], "expr": exprA},
            "B": {"rect": B["rect"], "expr": exprB},
            "distance": dist,
            "union_rect": urect,
            "and_expression": expr
        })

    for S in singles:
        new_blocks.append(S)
    return new_blocks, pairs_debug

# ---- LOGGING DE ITERAÇÕES ----

# Escreve saídas JSON e TXT de uma iteração (OR ou AND)
def write_iter_outputs(base, iter_idx, phase, subpass, blocks, debug_info):
    iter_str = f"{iter_idx:04d}"
    sub_str = f"{subpass:02d}"
    json_path = os.path.join(LOGS_DIR, f"{base}__16_iter{iter_str}_{sub_str}_{phase}.json")
    payload = {
        "image_base": base,
        "iteration": iter_idx,
        "phase": phase,
        "subpass": subpass,
        "blocks": blocks,
        "debug": debug_info
    }
    save_json(json_path, payload)

    txt_path = os.path.join(LOGS_DIR, f"{base}__16_iter{iter_str}_{sub_str}_{phase}_readable.txt")
    lines = [
        f"Imagem base: {base}",
        f"Iteração: {iter_idx} | Fase: {phase} | Subpass: {subpass}",
        f"Blocos: {len(blocks)}",
        ""
    ]
    if phase == "OR":
        for gi, g in enumerate((debug_info or []), start=1):
            xr = g.get("or_rect", g.get("union_rect_full", [0, 0, 0, 0]))
            x1, y1, x2, y2 = xr
            lines.append(f"[OR] Grupo #{gi} | or_rect=[{x1},{y1},{x2},{y2}] width={x2-x1+1}")
            if "union_rect_full" in g:
                fx1, fy1, fx2, fy2 = g["union_rect_full"]
                lines.append(f"    union_rect_full=[{fx1},{fy1},{fx2},{fy2}]")
            for m in g["members"]:
                rx1, ry1, rx2, ry2 = m["rect"]
                lines.append(f"  - rect=[{rx1},{ry1},{rx2},{ry2}] width={rx2-rx1+1} touchR={m.get('touches_right_bus', False)} cy={m.get('cy'):.1f}")
                lines.append(f"    expr: {m.get('expr','') or '(vazio)'}")
            lines.append(f"  OR: {g.get('or_expression','') or '(vazio)'}")
            lines.append("")
    else:
        for pi, p in enumerate((debug_info or []), start=1):
            Ax1, Ay1, Ax2, Ay2 = p.get("A", {}).get("rect", [0, 0, 0, 0])
            Bx1, By1, Bx2, By2 = p.get("B", {}).get("rect", [0, 0, 0, 0])
            Ux1, Uy1, Ux2, Uy2 = p.get("union_rect", [0, 0, 0, 0])
            lines.append(f"[AND] Par #{pi} | dist={p.get('distance',0):.2f}")
            lines.append(f"  A rect=[{Ax1},{Ay1},{Ax2},{Ay2}] expr: {p.get('A',{}).get('expr','') or '(vazio)'}")
            lines.append(f"  B rect=[{Bx1},{By1},{Bx2},{By2}] expr: {p.get('B',{}).get('expr','') or '(vazio)'}")
            lines.append(f"  -> union_rect=[{Ux1},{Uy1},{Ux2},{Uy2}] AND: {p.get('and_expression','') or '(vazio)'}")
            lines.append("")
    lines.append("Resumo dos blocos após a fase:")
    for i, b in enumerate(blocks, start=1):
        x1, y1, x2, y2 = b["rect"]
        w = x2 - x1 + 1
        lines.append(f"  #{i:03d} rect=[{x1},{y1},{x2},{y2}] width={w} touchR={bool(b.get('touches_right_bus', False))} cy={get_cy(b):.1f} expr: {(b.get('expression','') or '(vazio)')}")
    save_txt(txt_path, lines)

# Variável global para armazenar verticais (usada em logging/AND)
verticals_global: List[Dict[str, int]] = []

# ---- MAIN ----

def main():
    ensure_logs_dir()
    ensure_final_dir()
    files = sorted(glob.glob(os.path.join(DEBUG_DIR, f"*{AND_GROUPS_SUFFIX_JSON}")))
    if not files:
        print(f"[ERRO] Nenhum arquivo {AND_GROUPS_SUFFIX_JSON} em {DEBUG_DIR}")
        return

    global verticals_global
    for f in files:
        base = os.path.basename(f)[:-len(AND_GROUPS_SUFFIX_JSON)]
        data = load_json(f)
        if not data or "groups" not in data:
            print(f"[AVISO] Estrutura inesperada em {f}")
            continue

        verticals_global = load_verticals_for_base(base)
        raw_blocks = data["groups"]
        blocks = []
        for b in raw_blocks:
            blocks.append({
                "rect": b.get("rect", [0, 0, 0, 0]),
                "tags": b.get("tags", []),
                "expression": (b.get("expression") or "").strip(),
                "touches_right_bus": bool(b.get("touches_right_bus", False)),
                "cy": get_cy(b)
            })

        iter_idx = 0
        op_count = 0
        changed = True

        while changed and iter_idx < MAX_ALTERNATING_ITERS:
            changed = False
            iter_idx += 1

            # 1) OR (pilhas) — repetir até estabilizar
            subpass = 0
            while True:
                subpass += 1
                op_count += 1
                new_blocks, debug_or = group_by_OR_with_intersections(blocks, verticals_global)
                write_iter_outputs(base, iter_idx, "OR", subpass, new_blocks, debug_or)

                # Limpeza de vazios após algumas operações
                if op_count >= REMOVE_EMPTY_AFTER_K:
                    before = len(new_blocks)
                    new_blocks = [b for b in new_blocks if has_expr(b)]
                    if len(new_blocks) != before:
                        pass

                if len(new_blocks) < len(blocks):
                    blocks = new_blocks
                    changed = True
                    if len(blocks) <= 1:
                        break
                    continue
                else:
                    blocks = new_blocks
                    break

            if len(blocks) <= 1:
                break

            # 2) AND — tentar pareamento
            subpass_and = 1
            op_count += 1
            new_blocks, debug_and = pair_blocks_AND(blocks, verticals_global)

            # Limpeza de vazios após algumas operações
            if op_count >= REMOVE_EMPTY_AFTER_K and new_blocks:
                before = len(new_blocks)
                new_blocks = [b for b in new_blocks if has_expr(b)]

            if new_blocks is not None and len(new_blocks) < len(blocks):
                blocks = new_blocks
                write_iter_outputs(base, iter_idx, "AND", subpass_and, blocks, debug_and)
                changed = True
            else:
                write_iter_outputs(base, iter_idx, "AND", subpass_and, blocks, debug_and)

            if len(blocks) <= 1:
                break

        # Resultado final (sem colapso artificial)
        ensure_final_dir()
        final_json = os.path.join(FINAL_DIR, f"{base}__17_final.json")
        final_txt = os.path.join(FINAL_DIR, f"{base}__17_final_readable.txt")
        save_json(final_json, {"image_base": base, "final_blocks": blocks})
        lines = [f"Imagem base: {base}", f"Blocos finais: {len(blocks)}", ""]
        for i, b in enumerate(blocks, start=1):
            x1, y1, x2, y2 = b["rect"]
            w = x2 - x1 + 1
            lines.append(f"  #{i:03d} rect=[{x1},{y1},{x2},{y2}] width={w} touchR={bool(b.get('touches_right_bus', False))} cy={get_cy(b):.1f} expr: {(b.get('expression','') or '(vazio)')}")
        save_txt(final_txt, lines)
        print(f"[DONE] {base}: Final salvo em {FINAL_DIR} (sem colapso artificial).")

if __name__ == "__main__":
    main()