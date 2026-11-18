import re
from pathlib import Path
from .types import VaaniError

def prepare(text,mode="text"):
    if not isinstance(text,str):raise VaaniError(2,"Input must be UTF-8 text")
    text=text.lstrip("\ufeff").replace("\r\n","\n").replace("\r","\n")
    if len(text)>100000:raise VaaniError(2,"Input exceeds 100,000 characters")
    if any(ord(c)<32 and c not in "\n\t" for c in text):raise VaaniError(2,"Binary/control characters in input")
    if mode=="markdown":
        if text.startswith("---\n"):
            match=re.search(r"(?m)^---[ \t]*$",text[4:])
            if match is None:raise VaaniError(2,"Unclosed Markdown frontmatter")
            text=text[4+match.end():].lstrip("\n")
        text=re.sub(r"<!--[\s\S]*?-->","",text)
        lines=[];fence=None
        for line in text.splitlines():
            match=re.match(r"^\s*(`{3,}|~{3,})",line)
            if fence:
                if match and match.group(1)[0]==fence[0] and len(match.group(1))>=fence[1] and not line[match.end():].strip():fence=None
                continue
            if match:
                fence=(match.group(1)[0],len(match.group(1)))
                continue
            if re.match(r"^\s*#{1,6}\s",line):continue
            if re.match(r"^\s{0,3}(=+|-+)\s*$",line) and lines and lines[-1].strip():
                lines.pop();continue
            line=re.sub(r"!\[[^\]]*\]\([^)]*\)","",line)
            line=re.sub(r"\[([^\]]+)\]\([^)]*\)",r"\1",line)
            literals=[]
            def protect(match):
                literals.append(match.group(1));return f"VAANIINLINECODE{len(literals)-1}TOKEN"
            line=re.sub(r"`([^`]+)`",protect,line)
            if re.match(r"^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)+\|?\s*$",line) or (line.strip().startswith("|") and line.strip().endswith("|")):
                raise VaaniError(2,"Markdown tables are unsupported; provide final narration text")
            if re.search(r"</?[A-Za-z][^>]*>",line):raise VaaniError(2,"Embedded HTML is unsupported")
            line=re.sub(r"^\s*(?:[-+*]|\d+[.)])\s+","",line)
            line=re.sub(r"^\s*>\s?","",line)
            line=line.replace("**","").replace("__","")
            line=re.sub(r"(?<!\w)[*_]([^*_\n]+)[*_](?!\w)",r"\1",line)
            for index,literal in enumerate(literals):line=line.replace(f"VAANIINLINECODE{index}TOKEN",literal)
            lines.append(line)
        if fence:raise VaaniError(2,"Unclosed Markdown code fence")
        text="\n".join(lines)
    elif mode!="text":raise VaaniError(2,"Unsupported input format")
    paragraphs=[re.sub(r"\s+"," ",p).strip() for p in re.split(r"\n\s*\n",text)]
    result="\n\n".join(p for p in paragraphs if p)
    if not result:raise VaaniError(2,"Input contains no spoken content")
    if re.search(r"<\|[^>]+\|>",result):raise VaaniError(2,"Reserved model tokens are not narration text")
    return result

def read_source(request):
    if (request.input_path is None)==(request.text is None):raise VaaniError(2,"Provide exactly one input file or text/stdin source")
    mode=request.input_format
    if request.input_path is not None:
        p=Path(request.input_path)
        try:
            if p.stat().st_size>1_000_000:raise VaaniError(2,"Input file is too large")
            original=p.read_text(encoding="utf-8-sig")
        except (OSError,UnicodeError) as exc:raise VaaniError(2,"Cannot read input as UTF-8: "+str(exc)) from exc
        if mode=="auto":
            if p.suffix.lower() in (".md",".markdown"):mode="markdown"
            elif p.suffix.lower()==".txt":mode="text"
            else:raise VaaniError(2,"Unknown input extension; set --input-format text or markdown")
    else:
        original=request.text
        if mode=="auto":mode="text"
    return original,prepare(original,mode),mode
