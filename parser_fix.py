import re
from bs4 import BeautifulSoup
from urllib.parse import urlparse
MUNICIPALITIES=['Mariehamn','Jomala','Finström','Lemland','Hammarland','Saltvik','Sund','Eckerö','Geta','Vårdö','Föglö','Kumlinge','Kökar','Sottunga','Brändö','Lumparland']
def number(s):
 s=re.sub(r'[^\d,.\s\u00a0]','',str(s)).replace('\u00a0','').replace(' ','')
 if not s:return None
 if ',' in s:s=s.replace('.','').replace(',','.')
 elif s.count('.')==1 and len(s.split('.')[-1])==3:s=s.replace('.','')
 try:return float(s)
 except ValueError:return None
def extract(html,url):
 soup=BeautifulSoup(html,'html.parser')
 for el in soup(['script','style','nav','footer','header']):el.decompose()
 h=soup.find('h1');title=h.get_text(' ',strip=True) if h else urlparse(url).path.rsplit('/',1)[-1]
 txt=soup.get_text(' ',strip=True)
 def find(patterns):
  for p in patterns:
   m=re.search(p,txt,re.I)
   if m:return number(m.group(1))
  return None
 money=r'([\d][\d\s\u00a0.,]*)'
 price=find([r'(?:Utgångspris|Begärt pris|Försäljningspris)\s*:\s*'+money+r'\s*€',r'(?<!skuld)\bPris\s*:\s*'+money+r'\s*€'])
 debt=find([r'\(\s*skuldfritt(?:\s+pris)?\s*(?:ca\.?\s*)?'+money+r'\s*(?:€|euro|\))',r'Skuldfritt\s+pris\s*:\s*'+money])
 area=find([r'(?:Våningsyta|Boyta|Bostadsyta|Boarea)\s*:\s*(?:ca\.?\s*)?'+money+r'\s*m\s*(?:²|2|\b)',r'(?:Våningsyta|Boyta|Bostadsyta|Boarea)\s*:\s*(?:ca\.?\s*)?'+money+r'\s*m'])
 fee=find([r'(?:Bolagsvederlaget|Skötselvederlaget|Vederlaget)\s+uppgår\s+till\s*'+money+r'\s*(?:€|euro)\s*/\s*(?:månad|mån)',r'(?:Skötselvederlag|Bolagsvederlag|Vederlag)\s*:\s*'+money+r'\s*(?:€|euro)\s*/\s*(?:månad|mån)'])
 mun=next((m for m in MUNICIPALITIES if re.search(r'\b'+re.escape(m)+r'\b',txt[:700],re.I)),'Okänd')
 return dict(title=title,municipality=mun,price=price,debtfree=debt,area=area,fee=fee,description=txt[:15000])
