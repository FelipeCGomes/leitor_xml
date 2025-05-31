# =============================================================
#  Leitor Fiscal — CT-e & NF-e   (Streamlit ≥ 1.33)
# =============================================================
import io, os, zipfile, tempfile, re
from datetime import datetime
import pandas as pd
import streamlit as st
from   lxml import etree
# -------------------------------------------------------------
st.set_page_config(page_title="Leitor Fiscal", layout="wide")

# -------------------- XML helpers ----------------------------
NS_CTE = {"c": "http://www.portalfiscal.inf.br/cte"}
NS_NFE = {"n": "http://www.portalfiscal.inf.br/nfe"}
PARSER  = etree.XMLParser(ns_clean=True, recover=True)

def xml_float(t: str | None) -> float:
    return float(t.replace(",", ".")) if t else 0.0

def br_money(v: float | str) -> str:
    if isinstance(v, str): v = float(v.replace(",", "."))
    return f"{v:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")

def br_weight(kg: float) -> str:
    return f"{kg:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")

def str_to_float_br(s: str) -> float:
    return float(s.replace(".", "").replace(",", ".")) if s else 0.0

def frete_tipo(code: str) -> str:
    return {"0": "CIF (Emitente)","1": "FOB (Destinat.)",
            "2": "Terceiros","3": "Sem frete",
            "4": "Sem frete","9": "Sem frete",}.get(code.strip(), code or "--")

# =============================================================
#  XML → dict helpers
# =============================================================
def parse_cte(raw: bytes, fname: str) -> list[dict]:
    """
    Devolve lista (1¹ ou “várias linhas”, uma por NF) para montar DataFrame.
    """
    try: root = etree.fromstring(raw, PARSER)
    except Exception: return []

    inf = root.find(".//c:infCte", NS_CTE)
    if inf is None: return []

    data = datetime.fromisoformat(
        inf.findtext("c:ide/c:dhEmi", "", NS_CTE)).strftime("%d/%m/%Y")

    frete = xml_float(inf.findtext(".//c:vTPrest", "0", NS_CTE))
    peso  = sum({xml_float(n.text) for n in root.findall(".//c:qCarga", NS_CTE)})

    emit   = root.findtext(".//c:emit/c:xNome", "", NS_CTE)
    uf_o   = root.findtext(".//c:enderEmit/c:UF", "", NS_CTE)
    uf_d   = root.findtext(".//c:dest/c:enderDest/c:UF", "", NS_CTE)
    cidade = root.findtext(".//c:dest/c:enderDest/c:xMun", "", NS_CTE)
    n_cte  = inf.findtext("c:ide/c:nCT", "", NS_CTE)

    chaves = [n.findtext("c:chave", "", NS_CTE)
              for n in root.findall(".//c:infNFe", NS_CTE)] or [""]

    linhas=[]
    for chave in chaves:
        linhas.append({
            "Data": data,
            "Mês-Ano": pd.to_datetime(data, format="%d/%m/%Y").strftime("%Y-%m"),
            "Número CT-e": n_cte,
            "Emitente": emit,
            "UF Orig": uf_o,
            "UF Dest": uf_d,
            "Cidade Dest": cidade,
            "Frete (R$)": br_money(frete),
            "Peso (kg)": br_weight(peso),
            "R$/ton": br_money(frete/(peso/1000)) if peso else "",
            "Chave NF": chave,
            "Arquivo": fname
        })
    return linhas


def parse_nfe(raw: bytes, fname:str) -> dict|None:
    try: rt = etree.fromstring(raw, PARSER)
    except Exception: return None
    if etree.QName(rt.tag).localname == "nfeProc":
        rt = rt.find(".//n:NFe", NS_NFE) or rt

    inf = rt.find(".//n:infNFe", NS_NFE)
    if inf is None: return None

    ide  = inf.find("n:ide", NS_NFE)
    emit = inf.find("n:emit", NS_NFE)
    dest = inf.find("n:dest", NS_NFE)
    tot  = inf.find(".//n:ICMSTot", NS_NFE)

    data  = datetime.fromisoformat(
        ide.findtext("n:dhEmi", "", NS_NFE) or ide.findtext("n:dEmi", "", NS_NFE)
    ).strftime("%d/%m/%Y")

    chave = inf.get("Id","").lstrip("NFe")
    transp= inf.find("n:transp", NS_NFE)
    tnode = transp.find("n:transporta", NS_NFE) if transp is not None else None

    return {
        "Data": data,
        "Número NF": ide.findtext("n:nNF", "", NS_NFE),
        "Chave NF": chave,
        "Emitente NF": emit.findtext("n:xNome", "", NS_NFE),
        "Destinatário": dest.findtext("n:xNome", "", NS_NFE),
        "Valor NF (R$)": br_money(xml_float(tot.findtext("n:vNF", "0", NS_NFE))),
        "ICMS (R$)": br_money(xml_float(tot.findtext("n:vICMS","0",NS_NFE))),
        "Transportadora": tnode.findtext("n:xNome", "", NS_NFE) if tnode else "",
        "CNPJ Transp": tnode.findtext("n:CNPJ", "", NS_NFE) if tnode else "",
        "Tipo Frete": frete_tipo(transp.findtext("n:modFrete","",NS_NFE)) if transp else "",
        "Arquivo": fname
    }

# =============================================================
#  Loader: aceita XML direto ou ZIP de XMLs
# =============================================================
def load_files(label:str, key:str):
    """Devolve lista de (nome, bytes)."""
    up = st.file_uploader(label, accept_multiple_files=True,
                          type=["xml","zip"], key=f"upl_{key}")
    files=[]
    if up:
        for f in up:
            if f.name.lower().endswith(".xml"):
                files.append((f.name,f.read()))
            else:
                with tempfile.TemporaryDirectory() as td:
                    zpath=os.path.join(td,"tmp.zip")
                    open(zpath,"wb").write(f.read())
                    with zipfile.ZipFile(zpath) as zf:
                        for n in zf.namelist():
                            if n.lower().endswith(".xml"):
                                files.append((n, zf.read(n)))
    return files

# =============================================================
#  Aba layout
# =============================================================
tab_home, tab_cte, tab_nfe, tab_merge = st.tabs(
    ["🏠 HOME","🚚 CT-e","📦 NF-e","🔗 UNIFICAR"]
)

# ---------------- HOME ---------------------------------------
with tab_home:
    st.title("Leitor Fiscal")
    st.write("Carregue CT-e e NF-e (XML ou ZIP) e, se quiser, **unifique** os documentos usando a chave da NF.")

# ---------------- CT-e ---------------------------------------
with tab_cte:
    st.header("Upload CT-e")
    rows_cte=[]
    for n,raw in load_files("Selecione CT-e (XML ou ZIP):","cte"):
        rows_cte.extend(parse_cte(raw,n))
    if rows_cte:
        df_cte=pd.DataFrame(rows_cte)
        st.dataframe(df_cte, use_container_width=True)
        st.session_state["df_cte"]=df_cte
        buf=io.BytesIO(); df_cte.to_excel(buf,index=False)
        st.download_button("📥 Baixar CT-e.xlsx", buf.getvalue(),
                           "cte.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    else:
        st.info("Nenhum CT-e carregado.")

# ---------------- NF-e ---------------------------------------
with tab_nfe:
    st.header("Upload NF-e")
    rows_nfe=[]
    for n,raw in load_files("Selecione NF-e (XML ou ZIP):","nfe"):
        d=parse_nfe(raw,n)
        if d: rows_nfe.append(d)
    if rows_nfe:
        df_nfe=pd.DataFrame(rows_nfe)
        st.dataframe(df_nfe,use_container_width=True)
        st.session_state["df_nfe"]=df_nfe
        buf=io.BytesIO(); df_nfe.to_excel(buf,index=False)
        st.download_button("📥 Baixar NF-e.xlsx", buf.getvalue(),
                           "nfe.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    else:
        st.info("Nenhum NF-e carregado.")

# --------------- UNIFICAR ------------------------------------
with tab_merge:
    st.header("Unificar CT-e × NF-e (pela Chave NF)")
    df_cte = st.session_state.get("df_cte")
    df_nfe = st.session_state.get("df_nfe")

    if df_cte is None or df_nfe is None:
        st.info("Antes de unificar, carregue **pelo menos** um CT-e e uma NF-e.")
    else:
        merged = pd.merge(df_cte, df_nfe, on="Chave NF", how="inner",
                          suffixes=("_CTE","_NFE"))
        st.success(f"Documentos correspondentes: **{len(merged)}** registro(s)")
        st.dataframe(merged,use_container_width=True)

        buf = io.BytesIO(); merged.to_excel(buf,index=False)
        st.download_button("📥 Baixar Unificado.xlsx", buf.getvalue(),
                           "cte_nfe_unificado.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
