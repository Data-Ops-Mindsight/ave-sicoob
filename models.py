"""Normalização dos payloads da API Mindsight (formatos confirmados via --inspect).

Chave de junção: o `key` (CPF) é o único campo comum a participantes, respostas e pares.
Ele é convertido em um id pseudonimizado (HMAC) e o CPF NUNCA é gravado, exibido ou logado.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import re
from config import resolver_marco_papel, pepper, competencia


def g(d, *paths, default=None):
    """Primeiro valor não vazio entre caminhos 'a.b.c'."""
    for p in paths:
        cur = d
        for k in p.split("."):
            cur = cur.get(k) if isinstance(cur, dict) else None
            if cur is None:
                break
        if cur not in (None, ""):
            return cur
    return default


def pid_from_key(key) -> str | None:
    """CPF -> id estável e irreversível (sem o pepper). None se não houver key."""
    if key in (None, ""):
        return None
    k = re.sub(r"\D", "", str(key)) or str(key).strip().upper()
    return "p" + hmac.new(pepper(), k.encode(), hashlib.sha256).hexdigest()[:16]


def macro_area(area):
    return (area or "").split(" - ")[0].strip() if area else ""


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _txt(v):
    return v if isinstance(v, str) and v.strip() else None


def norm_participantes(items):
    out = []
    for it in items:
        p = it.get("participant") or {}
        pid = pid_from_key(p.get("key"))
        if not pid:
            continue
        ai = it.get("additional_info") or {}
        tags = it.get("tags") or []
        area = (ai.get("area") or "").strip()
        out.append(dict(
            pessoa_id=pid, nome=p.get("name"), email=g(p, "email", "username"),
            cargo=(ai.get("role") or "").strip(), area=area, macro_area=macro_area(area),
            tags=json.dumps(tags, ensure_ascii=False),
            is_gpc=int(any("GPC" in str(t).upper() for t in tags)),
        ))
    return out


def norm_pares(items):
    out = []
    for it in items:
        marco, papel = resolver_marco_papel(None, it.get("evaluation_group"))
        pid = pid_from_key(g(it, "evaluated.key"))
        if not pid or marco is None:
            continue
        out.append(dict(
            pessoa_id=pid, avaliador_id=pid_from_key(g(it, "appraiser.key")),
            avaliador_nome=g(it, "appraiser.name"), marco=marco, papel=papel,
            pendente=int(bool(it.get("is_pending", False))),
            _nome_avaliado=g(it, "evaluated.name"),
        ))
    return out


def _base(it, tipo):
    marco, papel = resolver_marco_papel(None, it.get("evaluation_group_key"))
    pid = pid_from_key(it.get("evaluated_key"))
    if not pid or marco is None:
        return None
    aid = pid_from_key(it.get("appraiser_key"))
    d = dict(
        pessoa_id=pid, avaliador_id=aid, marco=marco, papel=papel, tipo=tipo,
        question_set=None,  # a API devolve o NOME do formulário, não o id
        ordem=it.get("question_order") or 0, pergunta=it.get("question") or "",
        competencia=it.get("question") or "",  # sobrescrita pelo tema em norm_choice
        gestor_nome=_txt(it.get("manager")), _nome_avaliado=it.get("evaluated_name"),
    )
    if aid == pid:  # autoavaliação: role/area pertencem com certeza ao avaliado
        d["_cargo"], d["_area"] = _txt(it.get("role")), _txt(it.get("area"))
    return d


def norm_choice(items):
    out = []
    for it in items:
        b = _base(it, "escolha")
        if b:
            b["competencia"] = competencia(b["marco"], b["papel"], b["ordem"], default=b["pergunta"])
            b.update(nota=_num(it.get("answer_value")), resposta=_txt(it.get("answer")),
                     comentario=_txt(it.get("comment")), texto=None)
            out.append(b)
    return out


def norm_open(items):
    out = []
    for it in items:
        b = _base(it, "aberta")
        if b:
            b.update(nota=None, resposta=None, comentario=None, texto=_txt(it.get("answer")))
            out.append(b)
    return out
