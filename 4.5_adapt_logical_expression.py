# 4.5_adapt_logical_expression.py
# Converte expressões lógicas (OR/AND/NOT) de arquivos finais em expressões Python válidas.
# Lê arquivos TXT com expressões, faz parsing para AST e gera código Python equivalente.

import os, json, re

# ---- DIRETORIOS ----
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR  = os.path.join(BASE_DIR, "99_debug", "17_final")
OUTPUT_DIR = os.path.join(BASE_DIR, "03_tags", "13_pseudo_final")

# ---- PARAMETROS ----
DEBUG = True  # Define como False para silenciar saída de debug

# Imprime mensagens de debug apenas se DEBUG=True
def dbg(*args):
    if DEBUG:
        print(" ".join(str(a) for a in args))

# ---- PARSER RECURSIVO ----

# Constrói uma AST (Abstract Syntax Tree) a partir de uma string como: OR(AND(%A, NOT(%B)), %C)
def parse_to_ast(s):
    s = s.replace(" ", "")
    idx = 0
    L = len(s)

    # Função auxiliar recursiva para fazer parsing de tokens da expressão
    def parse_token():
        nonlocal idx
        if idx >= L:
            raise ValueError("Unexpected end of expression")

        # Operador (letras) ou variável (%...)
        if s[idx].isalpha():  # nome de operador: AND, OR, NOT
            start = idx
            while idx < L and s[idx].isalpha():
                idx += 1
            name = s[start:idx]
            if idx < L and s[idx] == '(':
                idx += 1  # pula '('
                args = []
                # faz parsing de argumentos separados por vírgula até encontrar ')'
                while True:
                    if idx >= L:
                        raise ValueError("Unclosed '(' after operator " + name)
                    args.append(parse_token())
                    # após um token, espera ',' ou ')'
                    if idx < L and s[idx] == ',':
                        idx += 1  # pula vírgula e continua
                        continue
                    elif idx < L and s[idx] == ')':
                        idx += 1  # pula ')'
                        break
                    else:
                        raise ValueError(f"Expected ',' or ')' at pos {idx} in {s}")
                return ('OP', name.upper(), args)
            else:
                # isolado (sem parênteses) - trata como variável de texto
                return ('VAR', name)
        elif s[idx] == '%':  # variável começando com %
            start = idx
            idx += 1
            # aceita dígitos, letras, pontos, underscores
            while idx < L and (s[idx].isalnum() or s[idx] in "._"):
                idx += 1
            token = s[start:idx]
            return ('VAR', token)
        elif s[idx] == '(':
            # expressão entre parênteses (aninhamento extra)
            idx += 1
            node = parse_token()
            if idx >= L or s[idx] != ')':
                raise ValueError("Missing closing ')' for parentheses group")
            idx += 1
            return node
        else:
            raise ValueError(f"Unexpected character '{s[idx]}' at position {idx}")

    node = parse_token()
    if idx != L:
        # se algo sobrou, pode haver um problema (ex: caracteres extras)
        raise ValueError(f"Extra characters after parse at pos {idx}: {s[idx:]}")
    return node

# ---- CONVERSÃO DE AST PARA EXPRESSÃO PYTHON ----

# Transforma '%I8.7' -> 'I8_7', '%M1.2' -> 'M1_2' (mantém letras/dígitos/underscore)
def sanitize_var(var_token):
    # remove '%' inicial se existir
    if var_token.startswith('%'):
        var_token = var_token[1:]
    # substitui pontos por underscores
    var_token = var_token.replace('.', '_')
    # remove caracteres indesejados (por segurança)
    var_token = re.sub(r'[^0-9A-Za-z_]', '_', var_token)
    # garante que não comece com dígito (prefixo se necessário)
    if re.match(r'^\d', var_token):
        var_token = 'v_' + var_token
    return var_token

# Converte AST (retornada por parse_to_ast) para string Python
def ast_to_python(node):
    ntype = node[0]
    if ntype == 'VAR':
        return sanitize_var(node[1])
    elif ntype == 'OP':
        op_name = node[1]
        children = node[2]
        if op_name == 'NOT':
            if len(children) != 1:
                raise ValueError("NOT must have exactly 1 argument")
            child_py = ast_to_python(children[0])
            return f"(not {child_py})"
        elif op_name == 'AND':
            parts = [ast_to_python(c) for c in children]
            return "(" + " and ".join(parts) + ")"
        elif op_name == 'OR':
            parts = [ast_to_python(c) for c in children]
            return "(" + " or ".join(parts) + ")"
        else:
            # operador desconhecido - IMNOTSURE sobre operadores extras
            raise ValueError(f"Unknown operator: {op_name}")
    else:
        raise ValueError("Invalid AST node: " + str(node))

# ---- EXTRAÇÃO DE EXPRESSÃO DE ARQUIVO ----

# Procura por uma linha contendo 'expr:' e retorna o texto após 'expr:'
def extract_expr_from_text_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            # busca por 'expr:' ou 'expr :'
            m = re.search(r'expr\s*:\s*(.+)$', line)
            if m:
                return m.group(1).strip()
    return None

# ---- PROCESSAMENTO DE ARQUIVO ----

# Processa um único arquivo, convertendo sua expressão lógica para Python
def process_file(path, output_dir):
    dbg("[*] File:", os.path.basename(path))
    expr = extract_expr_from_text_file(path)
    if not expr:
        dbg("[!] expr not found")
        return
    dbg("[>] expr:", expr)
    try:
        ast = parse_to_ast(expr)
        dbg("[>] AST:", ast)
        py_expr = ast_to_python(ast)
        dbg("[=] python:", py_expr)
    except Exception as e:
        dbg("[ERROR] parser:", e)
        # salva erro no arquivo de saída para inspeção
        out_data = {
            "original_expression": expr,
            "error": str(e)
        }
        out_name = os.path.basename(path).replace('_readable.txt', '_converted.json')
        out_path = os.path.join(output_dir, out_name)
        with open(out_path, 'w', encoding='utf-8') as fo:
            json.dump(out_data, fo, indent=2, ensure_ascii=False)
        dbg("[->] saved (with error):", out_path)
        return

    # Salva JSON com original + convertido
    out_data = {
        "original_expression": expr,
        "python_expression": py_expr
    }
    out_name = os.path.basename(path).replace('_readable.txt', '_converted.json')
    out_path = os.path.join(output_dir, out_name)
    with open(out_path, 'w', encoding='utf-8') as fo:
        json.dump(out_data, fo, indent=2, ensure_ascii=False)
    dbg("[->] saved:", out_path)

# ---- MAIN ----

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    dbg("Input directory:", INPUT_DIR)
    dbg("Output directory:", OUTPUT_DIR)
    files = [f for f in os.listdir(INPUT_DIR) if f.endswith('_readable.txt')]
    if not files:
        dbg("[!] No '*_readable.txt' files found")
        return
    for fn in files:
        path = os.path.join(INPUT_DIR, fn)
        try:
            process_file(path, OUTPUT_DIR)
        except Exception as e:
            dbg("[ERROR] processing file", fn, ":", e)

if __name__ == "__main__":
    main()