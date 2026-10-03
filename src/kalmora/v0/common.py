import os, re
from .kb import KB
from .parse_doc import parse_doc_dir

def load_phase(P):
    kb = KB(P)
    docs = {d: parse_doc_dir(f'{P}/inbox/ap/{d}') for d in sorted(os.listdir(P + '/inbox/ap')) if os.path.isdir(f'{P}/inbox/ap/{d}')}
    return kb, docs

def nn(s): return re.sub(r"[^0-9A-Z]", "", str(s or "").upper()).lstrip("0")
