import re
POLICY="coherent-v1"

def fits(text):return len(text)<=450 and len(text.split())<=70

def plan(text):
    """Preserve whole paragraphs when bounded; never discard or reorder a word."""
    chunks=[]
    for paragraph in text.split("\n\n"):
        if fits(paragraph):chunks.append(paragraph);continue
        pieces=re.split(r"(?<=[.!?।])\s+",paragraph)
        units=[]
        for piece in pieces:
            if fits(piece):units.append(piece);continue
            clauses=re.split(r"(?<=[,;:])\s+",piece)
            for clause in clauses:
                if fits(clause):units.append(clause);continue
                current=[]
                for word in clause.split():
                    if current and not fits(" ".join(current+[word])):
                        units.append(" ".join(current));current=[]
                    if len(word)>450:raise ValueError("An individual token exceeds the utterance budget")
                    current.append(word)
                if current:units.append(" ".join(current))
        current=""
        for unit in units:
            candidate=(current+" "+unit).strip()
            if current and not fits(candidate):chunks.append(current);current=unit
            else:current=candidate
        if current:chunks.append(current)
    assert " ".join(text.split())==" ".join(" ".join(chunks).split())
    offset=0;result=[]
    for index,chunk in enumerate(chunks):
        start=text.find(chunk,offset)
        if start<0:
            # Whitespace changes at source paragraph boundaries remain explicit.
            start=offset
        basis="paragraph" if chunk in text.split("\n\n") else "sentence_or_clause" if chunk[-1:] in ".!?।,;:" else "bounded_whitespace"
        result.append(dict(index=index,text=chunk,start_character=start,end_character=start+len(chunk),boundary_basis=basis))
        offset=start+len(chunk)
    return result
