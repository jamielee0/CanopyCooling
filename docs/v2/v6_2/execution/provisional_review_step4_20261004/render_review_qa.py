"""Offline readable source/table previews; not a claim about native Codex UI."""
import json
import re
import textwrap
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parents[5]
EXEC=Path(__file__).resolve().parent
QA=EXEC/"qa"
FONT="/System/Library/Fonts/Supplemental/Arial.ttf"
BODY=ImageFont.truetype(FONT,19)
HEAD=ImageFont.truetype(FONT,23)
TITLE=ImageFont.truetype(FONT,29)
SMALL=ImageFont.truetype(FONT,16)


def plain(text):
 text=re.sub(r"\[([^\]]+)\]\([^)]+\)",r"\1",text)
 return text.replace("**","").replace("`","")


def render(lines,prefix,title):
 pages=[];im=None;draw=None;y=0
 def newpage():
  nonlocal im,draw,y
  if im is not None:pages.append(im)
  im=Image.new("RGB",(1400,1680),"white");draw=ImageDraw.Draw(im);y=120
  draw.text((55,30),title,font=TITLE,fill="#20334D")
  draw.text((55,73),f"Offline text/table QA · page {len(pages)+1}",font=SMALL,fill="#667085")
 def space(height):
  if y+height>1590:newpage()
 newpage()
 for line in lines:
  if not line.strip():space(14);y+=14;continue
  if line.startswith("|"):
   cells=[plain(c.strip()) for c in line.strip().strip("|").split("|")]
   if all(re.fullmatch(r":?-+:?",c.replace(" ","")) for c in cells):continue
   n=len(cells);widths=([130,140,200,240,240,170] if n==6 else [330,500,460] if n==3 else [1290/n]*n)
   wrapped=[textwrap.wrap(c,width=max(8,int(w/8.4))) or [""] for c,w in zip(cells,widths)]
   height=10+24*max(len(c) for c in wrapped);space(height)
   x=55
   for w,parts in zip(widths,wrapped):
    draw.rectangle((x,y,x+w,y+height),outline="#D0D5DD",width=1)
    for j,part in enumerate(parts):draw.text((x+7,y+5+j*24),part,font=SMALL,fill="#172B4D")
    x+=w
   y+=height;continue
  heading=line.startswith("#")
  text=plain(line.lstrip("# ")) if heading else plain(line)
  font=HEAD if heading else BODY
  parts=textwrap.wrap(text,width=103 if heading else 119) or [""]
  height=(31 if heading else 27)*len(parts)+(10 if heading else 0);space(height)
  for part in parts:draw.text((55,y),part,font=font,fill="#20334D" if heading else "#172B4D");y+=31 if heading else 27
  if heading:y+=10
 if im is not None:pages.append(im)
 paths=[]
 for i,page in enumerate(pages,1):
  path=QA/f"{prefix}_{i:02d}.png";page.save(path);paths.append(str(path.relative_to(ROOT)))
 return paths


def run():
 QA.mkdir(parents=True,exist_ok=True)
 paths=render((ROOT/"docs/v2/v6_2/provisional_results_review_step4_20261004.md").read_text().splitlines(),"review_page","Provisional 2023 cooling pilot review")
 paths+=render((ROOT/"deliverables/Provisional_Results_Review_2023_v6_2_20261004/README.md").read_text().splitlines(),"deliverable_page","Step 4 deliverable overview")
 for i,item in enumerate(json.loads((EXEC/"document_additions.json").read_text()),1):
  paths+=render(item["lines"],f"document_{i:02d}_page",f"Step 4 additions · document {i}")
 (EXEC/"visual_qa_manifest.json").write_text(json.dumps(dict(status="RENDERED_PENDING_INSPECTION",renderer="PIL basic offline source/text/table layout",native_Codex_preview_inspected=False,headless_browser_available=False,paths=paths),indent=2)+"\n")
 print(json.dumps(dict(previews=len(paths),paths=paths),indent=2))


if __name__=="__main__":run()
