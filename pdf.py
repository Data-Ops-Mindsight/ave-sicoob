"""PDFs (reportlab): ficha individual, relatório consolidado (capa + sumário) e resumo executivo.

Identidade Sicoob: paleta do manual de marca; fonte Asap se os TTF estiverem em assets/fonts
(senão Helvetica, que cobre Latin-1/português).
"""
from __future__ import annotations
import io
from xml.sax.saxutils import escape
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, CondPageBreak, Flowable, Frame, Image, KeepTogether, PageBreak,
                                PageTemplate, Paragraph, Spacer, Table, TableStyle)
from reportlab.platypus.tableofcontents import TableOfContents
import brand as B
import db
from config import BASE, cfg
from ficha import ROTULO_PAPEL

H = colors.HexColor
C = dict(t=H(B.TURQUESA), ve=H(B.VERDE_ESCURO), vc=H(B.VERDE_CLARO), vm=H(B.VERDE_MEDIO), r=H(B.ROXO),
         f=H(B.FUNDO_SUAVE), linha=H("#D5E3E0"), cinza=H("#5E7378"), t_claro=H("#D9F1EE"), r_claro=H("#E4E3F1"))

F, FB = "Helvetica", "Helvetica-Bold"
_fd = BASE / "assets" / "fonts"
if (_fd / "Asap-Regular.ttf").exists() and (_fd / "Asap-Bold.ttf").exists():
    pdfmetrics.registerFont(TTFont("Asap", str(_fd / "Asap-Regular.ttf")))
    pdfmetrics.registerFont(TTFont("Asap-Bold", str(_fd / "Asap-Bold.ttf")))
    F, FB = "Asap", "Asap-Bold"

W, HP = A4
MARG = 1.8 * cm
LARG = W - 2 * MARG


def _st(nome, **kw):
    base = dict(fontName=F, fontSize=9, leading=12, textColor=C["ve"])
    base.update(kw)
    return ParagraphStyle(nome, **base)


S = dict(
    h1=_st("h1", fontName=FB, fontSize=18, leading=22, spaceAfter=6),
    h2=_st("h2", fontName=FB, fontSize=13, leading=16, textColor=C["t"], spaceBefore=12, spaceAfter=5),
    h3=_st("h3", fontName=FB, fontSize=10.5, leading=13, spaceBefore=10, spaceAfter=4),
    p=_st("p"),
    peq=_st("peq", fontSize=8, leading=10, textColor=C["cinza"]),
    cel=_st("cel", fontSize=8.5, leading=10.5),
    celb=_st("celb", fontName=FB, fontSize=8.5, leading=10.5, textColor=colors.white),
    cap=_st("cap", fontName=FB, fontSize=30, leading=36, textColor=colors.white),
    capp=_st("capp", fontSize=13, leading=18, textColor=colors.white),
)
_cache: dict = {}


def ps(cor=None, bold=False, align=0, size=8.5, leading=None):
    """Estilo de parágrafo sob medida (cacheado)."""
    k = (str(cor), bold, align, size, leading)
    if k not in _cache:
        _cache[k] = _st(f"x{len(_cache)}", fontName=FB if bold else F, fontSize=size, leading=leading or size + 2.2,
                        textColor=cor or C["ve"], alignment=align)
    return _cache[k]


def _t(txt) -> str:
    return escape(str(txt if txt is not None else "—")).replace("\n", "<br/>")


def P(txt, style="p"):
    return Paragraph(_t(txt), S[style] if isinstance(style, str) else style)


def _nota(v) -> str:
    return "—" if v is None or v != v else f"{v:.1f}".replace(".", ",")


def _cor_status(status):
    return {"Concluída": (C["vm"], C["ve"]), "Pendente": (C["r"], colors.white)}.get(status, (H("#9AA8AB"), C["ve"]))


class Marcador(Flowable):
    """Flowable invisível: define o contexto do cabeçalho e (opcional) entrada no sumário."""
    def __init__(self, texto, toc=False):
        super().__init__()
        self.texto, self.toc = texto, toc

    def wrap(self, *a):
        return 0, 0

    def draw(self):
        pass


class _Doc(BaseDocTemplate):
    ctx = ""

    def afterFlowable(self, fl):
        if isinstance(fl, Marcador):
            self.ctx = fl.texto
            if fl.toc:
                self.notify("TOCEntry", (0, fl.texto, self.page))


def _decor(titulo):
    def fn(c, d):
        c.saveState()
        c.setFillColor(C["t"]); c.rect(0, HP - 0.3 * cm, W, 0.3 * cm, stroke=0, fill=1)
        c.setFillColor(C["ve"]); c.setFont(FB, 8); c.drawString(MARG, HP - 1.0 * cm, "Sicoob Cocred · Avaliação de Experiência")
        c.setFont(F, 8); c.setFillColor(C["cinza"]); c.drawRightString(W - MARG, HP - 1.0 * cm, d.ctx or titulo)
        c.setStrokeColor(C["linha"]); c.setLineWidth(0.6); c.line(MARG, HP - 1.2 * cm, W - MARG, HP - 1.2 * cm)
        c.line(MARG, 1.15 * cm, W - MARG, 1.15 * cm)
        c.setFont(F, 7.5); c.setFillColor(C["cinza"])
        c.drawRightString(W - MARG, 0.7 * cm, f"Página {d.page}")
        c.setFillColor(C["t"]); c.rect(0, 0, W, 0.2 * cm, stroke=0, fill=1)
        c.restoreState()
    return fn


def _novo_doc(buf, titulo, capa=None):
    d = _Doc(buf, pagesize=A4, leftMargin=MARG, rightMargin=MARG, topMargin=1.9 * cm, bottomMargin=1.7 * cm,
             title=titulo, author="Sicoob Cocred – RH")
    corpo = PageTemplate(id="corpo", frames=[Frame(d.leftMargin, d.bottomMargin, d.width, d.height, id="n")],
                         onPageEnd=_decor(titulo))
    pts = []
    if capa:
        pts.append(PageTemplate(id="capa", frames=[Frame(0, 0, 1, 1)], onPage=capa, autoNextPageTemplate="corpo"))
    d.addPageTemplates(pts + [corpo])
    return d


def _gerado(usuario):
    return f"{cfg()['rodada_nome']} · gerado em {db.agora_dt():%d/%m/%Y às %H:%M} por {usuario}"


def _faixa_titulo(titulo, linhas=()):
    """Bloco de abertura em verde escuro (nome do colaborador ou título do relatório)."""
    rows = [[Paragraph(_t(titulo), ps(colors.white, True, size=19, leading=23))]]
    for ln in linhas:
        rows.append([Paragraph(_t(ln), ps(H("#CFE9E5"), size=9, leading=12.5))])
    t = Table(rows, colWidths=[LARG])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), C["ve"]), ("LEFTPADDING", (0, 0), (-1, -1), 14),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 14), ("TOPPADDING", (0, 0), (-1, 0), 12),
                           ("BOTTOMPADDING", (0, 0), (-1, -2), 1), ("BOTTOMPADDING", (0, -1), (-1, -1), 11),
                           ("LINEBELOW", (0, -1), (-1, -1), 4, C["t"])]))
    return t


def _kpis(itens, ncol=4):
    """Cartões de indicador: itens = [(rótulo, valor, subtexto)]."""
    gap = 0.3 * cm
    w = (LARG - gap * (ncol - 1)) / ncol
    linhas = []
    for i in range(0, len(itens), ncol):
        grupo = itens[i:i + ncol]
        row, widths = [], []
        for k, (rot, val, sub) in enumerate(grupo):
            row.append([Paragraph(_t(rot), ps(C["cinza"], size=7.5, leading=9)),
                        Paragraph(_t(val), ps(C["ve"], True, size=19, leading=23)),
                        Paragraph(_t(sub or " "), ps(C["cinza"], size=7.5, leading=9))])
            widths.append(w)
            if k < len(grupo) - 1:
                row.append(""); widths.append(gap)
        linhas.append((row, widths))
    out = []
    for row, widths in linhas:
        t = Table([row], colWidths=widths)
        est = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]
        for c_ in range(0, len(row), 2):
            est += [("BACKGROUND", (c_, 0), (c_, 0), C["f"]), ("LINEABOVE", (c_, 0), (c_, 0), 3, C["t"]),
                    ("LEFTPADDING", (c_, 0), (c_, 0), 9)]
        t.setStyle(TableStyle(est))
        out += [t, Spacer(1, 5)]
    return out


def _pedacos(texto, limite=1000):
    """Divide um texto longo em blocos (parágrafos / ~1000 caracteres) para que a tabela possa quebrar de página."""
    out = []
    for par in str(texto).split("\n"):
        par = par.strip()
        while len(par) > limite:
            corte = par.rfind(" ", 0, limite)
            if corte < limite * 0.5:
                corte = limite
            out.append(par[:corte].strip())
            par = par[corte:].strip()
        if par:
            out.append(par)
    return out or ["—"]


def _caixa(titulo, texto, cor=None):
    """Resposta aberta / parecer: cartão com barra lateral. Uma linha por bloco de texto, para poder
    quebrar entre páginas (uma célula única maior que a página causa LayoutError)."""
    rows = [[Paragraph(_t(titulo), ps(C["ve"], True, size=9))]]
    rows += [[Paragraph(_t(p), ps(C["ve"], size=9, leading=13))] for p in _pedacos(texto)]
    t = Table(rows, colWidths=[LARG])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), C["f"]), ("LINEBEFORE", (0, 0), (0, -1), 4, cor or C["r"]),
                           ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                           ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                           ("TOPPADDING", (0, 0), (-1, 0), 7), ("BOTTOMPADDING", (0, -1), (-1, -1), 8)]))
    return t


def _aviso(texto):
    t = Table([[Paragraph(_t(texto), ps(C["cinza"], size=8.5))]], colWidths=[LARG])
    t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, C["linha"]), ("LEFTPADDING", (0, 0), (-1, -1), 10),
                           ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    return t


def _tabela(dados, larguras, header=True):
    t = Table(dados, colWidths=larguras, repeatRows=1 if header else 0)
    est = [("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LINEBELOW", (0, 0), (-1, -1), 0.4, C["linha"]),
           ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, C["f"]]),
           ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
           ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6)]
    if header:
        est.append(("BACKGROUND", (0, 0), (-1, 0), C["ve"]))
    t.setStyle(TableStyle(est))
    return t


def _cab(lista):
    return [Paragraph(_t(x), S["celb"]) for x in lista]


def _banner_marco(m, b):
    """Título do marco + situação de cada visão (cor + texto, nunca só cor)."""
    celulas = [Paragraph(f"Marco de {m} dias", ps(colors.white, True, size=13, leading=16))]
    for papel in ("gestor", "colaborador", "gpc"):
        bl = b[papel]
        fundo, txt = _cor_status(bl["status"])
        media = f" · {_nota(bl['media'])}" if bl["media"] is not None else ""
        celulas.append(Paragraph(f"<b>{_t(ROTULO_PAPEL[papel])}</b><br/>{_t(bl['status'])}{media}",
                                 ps(txt, size=7.8, leading=9.6, align=1)))
    larg = (LARG - 5.4 * cm) / 3
    t = Table([celulas], colWidths=[5.4 * cm, larg, larg, larg])
    est = [("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("BACKGROUND", (0, 0), (0, 0), C["ve"]),
           ("LEFTPADDING", (0, 0), (0, 0), 12), ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
           ("LINEAFTER", (0, 0), (-2, -1), 2, colors.white)]
    for i, papel in enumerate(("gestor", "colaborador", "gpc"), 1):
        est.append(("BACKGROUND", (i, 0), (i, 0), _cor_status(b[papel]["status"])[0]))
    t.setStyle(TableStyle(est))
    return t


def _tabela_respostas(itens, agrupar=True):
    """Perguntas de múltipla escolha com a nota em destaque; agrupadas por competência (ou em lista simples)."""
    wp, wr, wn = LARG - 7.2 * cm, 4.8 * cm, 2.4 * cm
    dados = [_cab(["Pergunta", "Resposta"]) + [Paragraph("Nota", ps(colors.white, True, 1, 8.5, 10.5))]]
    est = [("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("BACKGROUND", (0, 0), (-1, 0), C["ve"]),
           ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
           ("LINEBELOW", (0, 1), (-1, -1), 0.4, C["linha"])]
    grupos = {}
    for i in itens:
        grupos.setdefault(i["competencia"] if agrupar else "", []).append(i)
    for comp, its in grupos.items():
        notas = [i["nota"] for i in its if i["nota"] is not None]
        if agrupar and any(i["pergunta"] != comp for i in its):
            r = len(dados)
            media = f"média {_nota(sum(notas) / len(notas))}" if notas else ""
            dados.append([Paragraph(f"<b>{_t(comp)}</b>   <font color='#5E7378'>{media}</font>", ps(C["ve"], size=8.5)), "", ""])
            est += [("SPAN", (0, r), (-1, r)), ("BACKGROUND", (0, r), (-1, r), C["t_claro"]),
                    ("LINEABOVE", (0, r), (-1, r), 1.2, C["t"])]
        for i in its:
            r = len(dados)
            n = i["nota"]
            fundo, txt = B.NOTA_COR.get(int(round(n)), (B.VERDE_ESCURO, "#FFFFFF")) if n is not None else (None, None)
            dados.append([Paragraph(_t(i["pergunta"]), S["cel"]), Paragraph(_t(i["resposta"] or "—"), S["cel"]),
                          Paragraph(f"{n:.0f}" if n is not None else "—", ps(H(txt) if txt else C["ve"], True, 1, 10, 12))])
            if fundo:
                est.append(("BACKGROUND", (2, r), (2, r), H(fundo)))
            if i["comentario"]:
                for k, parte in enumerate(_pedacos(i["comentario"])):
                    r = len(dados)
                    pref = "<b>Justificativa:</b> " if k == 0 else ""
                    dados.append([Paragraph(pref + _t(parte), ps(C["ve"], size=8.3, leading=11)), "", ""])
                    est += [("SPAN", (0, r), (-1, r)), ("BACKGROUND", (0, r), (-1, r), C["f"]),
                            ("LINEBEFORE", (0, r), (0, r), 3, C["t"]), ("LEFTPADDING", (0, r), (0, r), 10),
                            ("TOPPADDING", (0, r), (0, r), 3 if k == 0 else 0), ("BOTTOMPADDING", (0, r), (0, r), 3)]
    t = Table(dados, colWidths=[wp, wr, wn], repeatRows=1)
    t.setStyle(TableStyle(est))
    return t


def _estilo(ax, xmax=None):
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color("#C5D3D1")
    ax.tick_params(colors=B.VERDE_ESCURO, labelsize=7.5, length=0)
    ax.xaxis.grid(True, color="#E3ECEA", linewidth=0.7); ax.set_axisbelow(True)
    if xmax:
        ax.set_xlim(0, xmax)


def _img(fig, largura=LARG):
    b = io.BytesIO()
    fig.savefig(b, format="png", dpi=190, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    b.seek(0)
    im = Image(b)
    r = im.imageHeight / im.imageWidth
    im.drawWidth, im.drawHeight = largura, largura * r
    return im


def _barras_duplas(ax, rotulos, v1, v2, nome1, nome2, cor1, cor2, xmax):
    n = len(rotulos)
    h = 0.36
    pos = list(range(n))
    b1 = ax.barh([p - h / 2 for p in pos], [0 if v is None or v != v else v for v in v1], height=h, color=cor1, label=nome1)
    b2 = ax.barh([p + h / 2 for p in pos], [0 if v is None or v != v else v for v in v2], height=h, color=cor2, label=nome2)
    for barras, vals in ((b1, v1), (b2, v2)):
        for bar, v in zip(barras, vals):
            if v is not None and v == v:
                ax.text(v + 0.04, bar.get_y() + h / 2, f"{v:.1f}".replace(".", ","), va="center", fontsize=6.8, color=B.VERDE_ESCURO)
    ax.set_yticks(pos); ax.set_yticklabels(rotulos); ax.invert_yaxis()
    _estilo(ax, xmax)


def grafico_comparativo(comp):
    """Gestor x autoavaliação por competência (um marco)."""
    if comp.empty:
        return None
    xmax = cfg()["escala_max"] + 0.35
    fig, ax = plt.subplots(figsize=(7.2, 0.34 * len(comp) * 1.25 + 0.9))
    _barras_duplas(ax, list(comp.competencia), list(comp.gestor), list(comp.colaborador),
                   "Gestor", "Autoavaliação", B.VERDE_ESCURO, B.TURQUESA, xmax)
    ax.legend(frameon=False, fontsize=7.5, ncol=2, loc="upper center", bbox_to_anchor=(0.5, -0.08 if len(comp) > 3 else -0.2))
    return _img(fig)


def grafico_evolucao(ev):
    """45 x 90 dias por competência, uma faixa para Gestor e outra para Autoavaliação."""
    paineis = []
    for papel, cor in (("gestor", B.VERDE_ESCURO), ("colaborador", B.TURQUESA)):
        sub = ev[ev.papel == papel]
        ok = sub.groupby("competencia")["marco"].nunique()
        sub = sub[sub.competencia.isin(ok[ok > 1].index)]
        if not sub.empty:
            paineis.append((papel, cor, sub.pivot_table(index="competencia", columns="marco", values="nota", sort=False)))
    if not paineis:
        return None
    altura = sum(0.26 * len(p[2]) * 1.2 + 0.8 for p in paineis)
    fig, axs = plt.subplots(len(paineis), 1, figsize=(7.2, altura), squeeze=False,
                            gridspec_kw=dict(height_ratios=[len(p[2]) + 2 for p in paineis]))
    for ax, (papel, cor, pv) in zip(axs[:, 0], paineis):
        _barras_duplas(ax, list(pv.index), list(pv[45]), list(pv[90]), "45 dias", "90 dias", "#7FD1C8" if cor == B.TURQUESA else "#6E9AA5", cor,
                       cfg()["escala_max"] + 0.35)
        ax.set_title(ROTULO_PAPEL[papel], fontsize=9, color=B.VERDE_ESCURO, loc="left", fontweight="bold")
        ax.legend(frameon=False, fontsize=7, ncol=2, loc="lower right", bbox_to_anchor=(1, 1.0))
    fig.tight_layout(h_pad=1.4)
    return _img(fig)


def grafico_andamento(a):
    sub = a.copy()
    sub["rot"] = [f"{m} dias · {ROTULO_PAPEL[p]}" for m, p in zip(sub.marco, sub.papel)]
    fig, ax = plt.subplots(figsize=(7.2, 0.36 * len(sub) + 0.8))
    y = list(range(len(sub)))
    ax.barh(y, sub.concluida, color=B.VERDE_MEDIO, height=0.62, label="Concluídas")
    ax.barh(y, sub.pendente, left=sub.concluida, color=B.ROXO, height=0.62, label="Pendentes")
    for i, r in enumerate(sub.itertuples()):
        if r.concluida:
            ax.text(r.concluida / 2, i, int(r.concluida), ha="center", va="center", fontsize=8, color=B.VERDE_ESCURO, fontweight="bold")
        if r.pendente:
            ax.text(r.concluida + r.pendente / 2, i, int(r.pendente), ha="center", va="center", fontsize=8, color="white", fontweight="bold")
    ax.set_yticks(y); ax.set_yticklabels(sub.rot); ax.invert_yaxis()
    _estilo(ax)
    ax.legend(frameon=False, fontsize=7.5, ncol=2, loc="upper center", bbox_to_anchor=(0.5, -0.1))
    return _img(fig)


def grafico_medias(m):
    pv = m.pivot_table(index="competencia", columns=["papel", "marco"], values="nota", sort=False)
    if pv.empty:
        return None
    series = [("gestor", 45, "Gestor 45d", "#6E9AA5"), ("gestor", 90, "Gestor 90d", B.VERDE_ESCURO),
              ("colaborador", 45, "Autoavaliação 45d", "#7FD1C8"), ("colaborador", 90, "Autoavaliação 90d", B.TURQUESA)]
    series = [s for s in series if (s[0], s[1]) in pv.columns]
    n, h = len(pv), 0.8 / len(series)
    fig, ax = plt.subplots(figsize=(7.2, 0.5 * n + 1.1))
    for k, (papel, marco, nome, cor) in enumerate(series):
        ys = [i - 0.4 + h * (k + 0.5) for i in range(n)]
        vals = pv[(papel, marco)]
        ax.barh(ys, vals.fillna(0), height=h * 0.92, color=cor, label=nome)
        for y_, v in zip(ys, vals):
            if v == v:
                ax.text(v + 0.04, y_, f"{v:.1f}".replace(".", ","), va="center", fontsize=6.3, color=B.VERDE_ESCURO)
    ax.set_yticks(range(n)); ax.set_yticklabels(list(pv.index)); ax.invert_yaxis()
    _estilo(ax, cfg()["escala_max"] + 0.35)
    ax.legend(frameon=False, fontsize=7.2, ncol=4, loc="upper center", bbox_to_anchor=(0.5, -0.06))
    return _img(fig)


def grafico_halteres(mel):
    if mel.empty or len(mel) > 30:
        return None
    mel = mel.sort_values("variacao")
    fig, ax = plt.subplots(figsize=(7.2, 0.3 * len(mel) + 0.9))
    y = list(range(len(mel)))
    ax.hlines(y, mel.media_45, mel.media_90, color=B.TURQUESA, linewidth=3, zorder=1)
    ax.scatter(mel.media_45, y, s=46, color=B.VERDE_ESCURO, zorder=2, label="45 dias")
    ax.scatter(mel.media_90, y, s=46, color=B.VERDE_MEDIO, zorder=2, label="90 dias")
    for i, r in enumerate(mel.itertuples()):
        ax.text(r.media_90 + 0.07, i, f"+{r.variacao:.1f}".replace(".", ","), va="center", fontsize=7, color=B.VERDE_ESCURO)
    ax.set_yticks(y); ax.set_yticklabels(list(mel.nome))
    _estilo(ax)
    ax.set_xlim(1, cfg()["escala_max"] + 0.4)
    ax.legend(frameon=False, fontsize=7.5, ncol=2, loc="upper center", bbox_to_anchor=(0.5, -0.07))
    return _img(fig)


def _flow_ficha(f: dict, gerado: str | None = None, toc=False) -> list:
    import pandas as pd
    from ficha import evolucao_competencias
    p, marcos = f["pessoa"], f["marcos"]
    por_comp = f.get("por_competencia", True)
    nome = p.get("nome") or "(sem nome)"
    fl = [Marcador(nome, toc)]
    meta = [" · ".join(x for x in (p.get("cargo"), p.get("area")) if x) or "—",
            f"Gestor: {p.get('gestor_nome') or '—'}   ·   E-mail: {p.get('email') or '—'}"]
    if gerado:
        meta.append(gerado)
    fl += [_faixa_titulo(nome, meta), Spacer(1, 9)]

    g45, g90 = marcos[45]["gestor"]["media"], marcos[90]["gestor"]["media"]
    a45, a90 = marcos[45]["colaborador"]["media"], marcos[90]["colaborador"]["media"]
    dl = lambda x, y: "—" if None in (x, y) else f"{y - x:+.1f}".replace(".", ",") + " vs. 45 dias"
    etapas = [b[k]["status"] for b in marcos.values() for k in ("gestor", "colaborador", "gpc") if b[k]["status"] != "Restrito"]
    fl += _kpis([("GESTOR · 45 DIAS", _nota(g45), "média das notas"), ("GESTOR · 90 DIAS", _nota(g90), dl(g45, g90)),
                 ("AUTOAVALIAÇÃO · 45 DIAS", _nota(a45), "média das notas"), ("AUTOAVALIAÇÃO · 90 DIAS", _nota(a90), dl(a45, a90))])
    fl.append(Paragraph(f"Etapas concluídas: <b>{sum(s == 'Concluída' for s in etapas)} de {len(etapas)}</b> "
                        f"(gestor, autoavaliação e GPC nos marcos de 45 e 90 dias).", S["peq"]))

    ev = evolucao_competencias(f)
    if por_comp:
        im = grafico_evolucao(ev) if not ev.empty else None
        if im is not None:
            fl += [CondPageBreak(7 * cm), Paragraph("Evolução por competência · 45 → 90 dias", S["h2"]), im]
    else:
        fl.append(Spacer(1, 4)); fl.append(_aviso("Análise por perguntas (competências desativadas): as notas aparecem pergunta a pergunta, "
                                                  "sem agrupamento e sem gráfico de evolução."))

    comp_all = f["comparativo"]
    for m, b in marcos.items():
        fl += [CondPageBreak(11 * cm), _banner_marco(m, b), Spacer(1, 8)]
        if por_comp:
            comp = comp_all[comp_all.marco == m] if not comp_all.empty else comp_all
            im = grafico_comparativo(comp)
            if im is not None:
                fl.append(KeepTogether([Paragraph("Gestor × Autoavaliação por competência", S["h3"]), im]))
        for papel, titulo, cor in (("gestor", "Avaliação do gestor", C["ve"]),
                                   ("colaborador", "Autoavaliação do colaborador", C["t"]),
                                   ("gpc", "Parecer / entrevista do RH (GPC)", C["r"])):
            bl = b[papel]
            fl += [CondPageBreak(4.5 * cm), Paragraph(titulo, S["h3"])]
            if bl["status"] == "Restrito":
                fl.append(_aviso("Conteúdo não disponível para este perfil."))
                continue
            if not bl["itens"] and not bl["abertas"]:
                fl.append(_aviso("Etapa pendente — ainda não preenchida." if bl["status"] == "Pendente"
                                 else "Sem respostas registradas."))
                continue
            if bl["itens"]:
                fl.append(_tabela_respostas(bl["itens"], agrupar=por_comp))
            for a in bl["abertas"]:
                fl += [Spacer(1, 5), _caixa(a["pergunta"], a["texto"], cor)]
        fl.append(Spacer(1, 6))
    return fl


def pdf_individual(f: dict, usuario: str) -> bytes:
    buf = io.BytesIO()
    d = _novo_doc(buf, "Ficha individual")
    d.build(_flow_ficha(f, gerado=_gerado(usuario)))
    return buf.getvalue()


def _capa(titulo, sub, linhas):
    def fn(c, d):
        c.saveState()
        c.setFillColor(C["ve"]); c.rect(0, 0, W, HP, stroke=0, fill=1)
        c.setFillColor(C["t"]); c.rect(0, HP * 0.40, W, 0.38 * cm, stroke=0, fill=1)
        c.setFont(FB, 10); c.setFillColor(C["vc"]); c.drawString(2.2 * cm, HP - 3.0 * cm, "SICOOB COCRED  ·  GESTÃO DE PESSOAS E CULTURA")
        y = HP * 0.66
        for txt, est in ((titulo, "cap"), (sub, "capp")):
            p = Paragraph(_t(txt), S[est]); _, h = p.wrap(W - 4.4 * cm, 10 * cm); p.drawOn(c, 2.2 * cm, y); y -= h + 10
        y = HP * 0.40 - 1.2 * cm
        for ln in linhas:
            p = Paragraph(_t(ln), ps(colors.white, size=11, leading=15)); _, h = p.wrap(W - 4.4 * cm, 5 * cm)
            p.drawOn(c, 2.2 * cm, y - h); y -= h + 5
        x = 0
        for cor in (B.TURQUESA, B.BRANCO, B.VERDE_CLARO, B.VERDE_MEDIO, B.ROXO):
            c.setFillColor(H(cor)); c.rect(x, 0, W / 5, 0.7 * cm, stroke=0, fill=1); x += W / 5
        c.setFillColor(C["t_claro"]); c.setFont(F, 8)
        c.restoreState()
    return fn


def pdf_lote(fichas: list[dict], filtros: str, usuario: str) -> bytes:
    buf = io.BytesIO()
    titulo = "Relatório consolidado"
    linhas = [cfg()["rodada_nome"], f"Recorte: {filtros or 'todos os colaboradores'}", f"{len(fichas)} colaboradores",
              f"Gerado em {db.agora_dt():%d/%m/%Y às %H:%M} por {usuario}"]
    d = _novo_doc(buf, titulo, capa=_capa("Avaliação de Experiência", "Relatório consolidado · Gestão de Pessoas", linhas))
    toc = TableOfContents()
    toc.levelStyles = [ParagraphStyle("t0", fontName=F, fontSize=9.5, leading=15, textColor=C["ve"], leftIndent=4)]
    toc.dotsMinLevel = 0
    fl = [PageBreak(), Marcador(titulo), Paragraph("Sumário", S["h1"]), Spacer(1, 6), toc, PageBreak()]
    for i, f in enumerate(fichas):
        fl += _flow_ficha(f, toc=True)
        if i < len(fichas) - 1:
            fl.append(PageBreak())
    d.multiBuild(fl)
    return buf.getvalue()


def pdf_executivo(ind: dict, filtros: str, usuario: str, ver_texto: bool) -> bytes:
    buf = io.BytesIO()
    d = _novo_doc(buf, "Resumo executivo")
    a, e, mel = ind["andamento"], ind["evolucao"], ind.get("melhoraram")
    fl = [Marcador("Resumo executivo"),
          _faixa_titulo("Resumo executivo", [cfg()["rodada_nome"], f"Recorte: {filtros or 'todos os colaboradores'}",
                                             f"{ind['total']} colaboradores · {_gerado(usuario)}"]), Spacer(1, 9)]
    g = lambda m, k: int(a[(a.marco == m) & (a.papel == "gestor")][k].sum()) if not a.empty else 0
    fl += _kpis([("COLABORADORES EM EXPERIÊNCIA", ind["total"], "no recorte"),
                 ("GESTOR CONCLUÍDO · 45 DIAS", g(45, "concluida"), f"{g(45, 'pendente')} pendentes"),
                 ("GESTOR CONCLUÍDO · 90 DIAS", g(90, "concluida"), f"{g(90, 'pendente')} pendentes"),
                 ("PENDÊNCIAS (TODAS AS ETAPAS)", int(a["pendente"].sum()) if not a.empty else 0, "gestor, autoaval. e GPC")])
    if not a.empty:
        fl += [Paragraph("Andamento por marco e visão", S["h2"]), grafico_andamento(a)]
    im = grafico_medias(ind["medias"]) if not ind["medias"].empty else None
    if im is not None:
        fl += [CondPageBreak(9 * cm), Paragraph("Médias por competência", S["h2"]), im]
    fl += [CondPageBreak(6 * cm), Paragraph("Evolução do 45º ao 90º dia (nota do gestor)", S["h2"])]
    if e["n"]:
        fl += _kpis([("COM OS DOIS MARCOS AVALIADOS", e["n"], "colaboradores"),
                     ("MÉDIA DO GESTOR 45 → 90 DIAS", f"{_nota(e['media_45'])} → {_nota(e['media_90'])}", "média do recorte"),
                     ("COLABORADORES QUE MELHORARAM", f"{e['melhoraram']} de {e['n']}", "média maior aos 90 dias")], ncol=3)
    else:
        fl.append(P("Ainda não há colaboradores com os dois marcos avaliados pelo gestor.", "peq"))
    if mel is not None and not mel.empty:
        fl += [CondPageBreak(7 * cm), Paragraph("Quem melhorou", S["h3"])]
        im = grafico_halteres(mel)
        if im is not None:
            fl += [im, Spacer(1, 6)]
        t = [_cab(["Colaborador", "Cargo", "Gestor", "45d", "90d", "Variação"])]
        for r in mel.itertuples():
            t.append([P(r.nome, "cel"), P(r.cargo, "cel"), P(r.gestor, "cel"), P(_nota(r.media_45), "cel"),
                      P(_nota(r.media_90), "cel"), Paragraph(f"+{r.variacao:.1f}".replace(".", ","), ps(C["ve"], True, 1))])
        tb = _tabela(t, [4.0 * cm, 4.2 * cm, 3.7 * cm, 1.6 * cm, 1.6 * cm, LARG - 15.1 * cm])
        tb.setStyle(TableStyle([("BACKGROUND", (5, 1), (5, -1), C["t_claro"])]))
        fl.append(tb)
    if ver_texto and not ind["decisoes"].empty:
        t = [_cab(["Marco", "Decisão do GPC", "Quantidade"])] + [
            [P(f"{r.marco} dias", "cel"), P(r.decisao, "cel"), P(r.qtd, "cel")] for r in ind["decisoes"].itertuples()]
        fl.append(KeepTogether([Paragraph("Decisões do GPC", S["h2"]), _tabela(t, [3 * cm, 9 * cm, 4 * cm])]))
    d.build(fl)
    return buf.getvalue()
